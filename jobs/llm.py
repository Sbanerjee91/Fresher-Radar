"""
LLM tagging through the Google Gemini Developer API.

Jobs are sent in small batches. A successful request contributes token usage and
an estimated cost to the caller. Rate limits and configuration errors stop the
remaining batches so one bad key/model cannot consume the daily request allowance.

This module keeps the existing tag_batch() and tag_all() interfaces used by
Fresher Radar's management command.
"""
from datetime import datetime, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
import json
import logging
import os
import re
import time

import requests
from django.conf import settings

from . import places
from .tagging import ROLES, clean_role

log = logging.getLogger(__name__)

BATCH_SIZE = 20
DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiAPIError(RuntimeError):
    """A safe-to-log Gemini API error; never includes request headers or API keys."""

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class GeminiRateLimitError(GeminiAPIError):
    """HTTP 429. The caller should stop sending further batches for this run."""

    def __init__(self, message, retry_after=None, limit_source=None):
        super().__init__(message, status_code=429)
        self.retry_after = retry_after
        self.limit_source = limit_source

OpenRouterAPIError = GeminiAPIError
OpenRouterRateLimitError = GeminiRateLimitError


SYSTEM_PROMPT = f"""You classify fresher and internship job posts from India.

Return one object per input post, preserving each input id exactly. Use this JSON shape:
{{"posts": [{{"id": 1, "role": "Frontend", "city": "Bengaluru"}}]}}

The role must be EXACTLY one of these values: {json.dumps(ROLES, ensure_ascii=False)}

Role rules:
- Classify the actual work, not the seniority or words like intern, trainee, or associate.
- Use Software Engineering only for generic software work (SDE, developer, programmer).
- Use a specific role (Frontend, Backend, Full Stack, Mobile, Data & Analytics, AI / ML,
  DevOps & Cloud, QA & Testing, Design (UI/UX), Product, etc.) when the title or description supports it.
- If no category fits, use Other. Never invent a role.

City rules:
- Use common modern spelling: Bengaluru, Gurugram, Mumbai, Chennai, Kolkata, Kochi,
  Thiruvananthapuram, Mysuru.
- If multiple cities are listed, choose the first one.
- For remote / work-from-home / anywhere in India, use Remote.
- If only India or a state is given, use India (unspecified).
- Never guess a city not stated in the post.

Return valid JSON only. Do not use Markdown fences or extra commentary."""


def _setting(name, default=None):
    """Read a Django setting, falling back to the environment and then default."""
    value = getattr(settings, name, None)
    if value in (None, ""):
        value = os.getenv(name)
    return default if value in (None, "") else value


def _api_key():
    return str(_setting("GEMINI_API_KEY", "") or "").strip()


def _model_name():
    # Keep the model ID plain, e.g. gemini-2.5-flash-lite (no "models/" prefix).
    return str(_setting("LLM_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL).strip()


def _base_url():
    # This must be the native Gemini API base URL, not the /openai compatibility URL.
    return str(_setting("GEMINI_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")


def enabled():
    """Return True when a Gemini API key is configured."""
    return bool(_api_key())


def _session():
    """Use a plain session: status-code retries are handled explicitly below."""
    return requests.Session()


def _retry_after_seconds(value):
    """Parse Retry-After as seconds or an HTTP date; return None if absent/invalid."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        when = parsedate_to_datetime(str(value))
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime_timezone.utc)
        return max(0.0, (when - datetime.now(datetime_timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _header_value(headers, wanted):
    if not hasattr(headers, "items"):
        return None
    for name, value in headers.items():
        if str(name).lower() == wanted.lower():
            return value
    return None


def _response_error_info(response):
    """Extract safe Gemini error fields; never expose request headers or API keys."""
    try:
        body = response.json()
    except (ValueError, requests.RequestException):
        body = {}

    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        message = error.get("message") or error.get("status") or "Gemini returned an API error"
        status = error.get("status")
        error_code = error.get("code")
        details = error.get("details") if isinstance(error.get("details"), list) else []
    else:
        message = str(error) if error else (
            body.get("message") if isinstance(body, dict) else None
        )
        status = None
        error_code = None
        details = []

    if not message:
        message = getattr(response, "text", "") or "No error details returned"

    retry_after = _header_value(getattr(response, "headers", {}) or {}, "Retry-After")

    # Google can return quota metadata in the structured error details.
    detail_text = []
    for detail in details:
        if isinstance(detail, dict):
            quota_failure = detail.get("quotaFailure")
            if isinstance(quota_failure, dict):
                for violation in quota_failure.get("violations", [])[:3]:
                    if isinstance(violation, dict):
                        description = violation.get("description")
                        if description:
                            detail_text.append(str(description)[:160])

    safe_message = re.sub(r"\s+", " ", str(message)).strip()[:300]
    return {
        "message": safe_message,
        "status": status,
        "error_code": error_code,
        "retry_after": retry_after,
        "quota_details": "; ".join(detail_text)[:300],
    }


def _response_message(response):
    """Extract a short error message without exposing request headers/secrets."""
    return _response_error_info(response)["message"]


def _format_rate_limit_error(response):
    info = _response_error_info(response)
    wait = _retry_after_seconds(info["retry_after"])
    diagnosis = "Google Gemini API quota/rate limit reached"

    if info["status"]:
        diagnosis += f" ({str(info['status'])[:50]})"
    if info["error_code"] is not None:
        diagnosis += f"; Google error code: {str(info['error_code'])[:40]}"
    if info["quota_details"]:
        diagnosis += f"; quota detail: {info['quota_details']}"
    if wait is not None:
        diagnosis += f"; retry after about {wait:.0f} seconds"

    return f"{diagnosis}. Original message: {info['message']}", wait, info["status"]


def _extract_items(text):
    """Parse an array or the preferred {"posts": [...]} JSON response."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("model returned an empty response")

    # Be defensive in case the model surrounds its JSON with Markdown fences.
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I)
    decoder = json.JSONDecoder()
    candidates = [i for i, char in enumerate(cleaned) if char in "[{"]
    data = None

    for start in candidates:
        try:
            data, _ = decoder.raw_decode(cleaned[start:])
            break
        except json.JSONDecodeError:
            continue

    if data is None:
        raise ValueError("model response did not contain valid JSON")

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("posts") or data.get("results") or data.get("items")
    else:
        items = None

    if not isinstance(items, list):
        raise ValueError('model JSON must be an array or an object containing a "posts" array')
    return items


def _clean_city(value, fallback):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return fallback
    city = places.canonical_city(text)
    if city:
        return city
    for known in places.KNOWN_CITIES:
        if known.lower() == text.lower():
            return known
    return text.title()[:60]


def _response_text(body):
    """Get text from Gemini's candidates/content/parts response shape."""
    candidates = body.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        prompt_feedback = body.get("promptFeedback") or {}
        reason = prompt_feedback.get("blockReason")
        if reason:
            raise GeminiAPIError(f"Gemini blocked the request: {str(reason)[:100]}")
        raise GeminiAPIError("Gemini returned no candidate response.")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    chunks = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    text = "\n".join(chunk for chunk in chunks if chunk).strip()
    if not text:
        finish_reason = candidates[0].get("finishReason")
        suffix = f" (finish reason: {finish_reason})" if finish_reason else ""
        raise GeminiAPIError(f"Gemini returned no text content{suffix}.")
    return text


def _estimate_cost_usd(input_tokens, output_tokens):
    """
    Estimate USD cost from configurable per-million-token rates.

    Keep both settings at 0.0 when using the free tier. For paid standard
    Gemini 2.5 Flash-Lite pricing, use 0.10 input and 0.40 output USD per
    million tokens. The API response itself does not include a billed-cost field.
    """
    input_price = float(_setting("GEMINI_INPUT_PRICE_PER_MILLION", 0.0) or 0.0)
    output_price = float(_setting("GEMINI_OUTPUT_PRICE_PER_MILLION", 0.0) or 0.0)
    return (
        (int(input_tokens) * input_price) +
        (int(output_tokens) * output_price)
    ) / 1_000_000.0


def tag_batch(session, posts):
    """Tag one batch.

    Returns ({job_id: (role, city)}, input_tokens, output_tokens, cost_usd).
    """
    if not posts:
        return {}, 0, 0, 0.0

    api_key = _api_key()
    if not api_key:
        raise GeminiAPIError("GEMINI_API_KEY is not configured.")

    payload = [
        {
            "id": p["id"],
            "title": str(p.get("title") or "")[:255],
            "company": str(p.get("company") or "")[:180],
            "location": str(p.get("location") or "")[:180],
            "about": str(p.get("about") or "")[:1800],
        }
        for p in posts
    ]

    model = _model_name()
    url = f"{_base_url()}/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    request_body = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": json.dumps(payload, ensure_ascii=False)}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2000,
            "responseMimeType": "application/json",
        },
    }

    try:
        response = session.post(
            url,
            headers=headers,
            json=request_body,
            timeout=(10, 90),
        )
    except requests.Timeout as exc:
        raise GeminiAPIError("Gemini API request timed out.") from exc
    except requests.RequestException as exc:
        raise GeminiAPIError(
            f"Could not reach Gemini API: {type(exc).__name__}."
        ) from exc

    status = int(getattr(response, "status_code", 200))
    if status == 429:
        detail, wait, source = _format_rate_limit_error(response)
        raise GeminiRateLimitError(
            f"Gemini API rate limit (HTTP 429): {detail}",
            retry_after=wait,
            limit_source=source,
        )
    if status >= 400:
        detail = _response_message(response)
        raise GeminiAPIError(
            f"Gemini API HTTP {status}: {detail}",
            status_code=status,
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise GeminiAPIError(
            "Gemini returned invalid JSON.",
            status_code=status,
        ) from exc

    if not isinstance(body, dict):
        raise GeminiAPIError(
            "Gemini returned an unexpected response shape.",
            status_code=status,
        )
    if body.get("error"):
        error = body["error"]
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message") or "Gemini returned an API error"
        else:
            code, message = None, str(error)
        if str(code) == "429":
            raise GeminiRateLimitError(str(message))
        raise GeminiAPIError(
            str(message),
            status_code=int(code) if str(code).isdigit() else None,
        )

    model_text = _response_text(body)
    items = _extract_items(model_text)

    usage = body.get("usageMetadata") or {}
    input_tokens = int(usage.get("promptTokenCount") or 0)
    output_tokens = int(usage.get("candidatesTokenCount") or 0)

    fallback = {
        p["id"]: p.get("fallback_city", "India (unspecified)")
        for p in posts
    }
    out = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue

        if pid in fallback:
            out[pid] = (
                clean_role(item.get("role")),
                _clean_city(item.get("city"), fallback[pid]),
            )

    cost = _estimate_cost_usd(input_tokens, output_tokens)
    return out, input_tokens, output_tokens, cost


def tag_all(posts):
    """Tag posts in batches and return results plus usage totals and errors.

    If Gemini rate-limits the request or reports a configuration/provider outage,
    stop sending more batches in this run. Failed jobs retain their rule-based tags.
    """
    if not posts:
        return {}, 0, 0, 0, 0.0, []

    if not enabled():
        return (
            {},
            0,
            0,
            0,
            0.0,
            ["GEMINI_API_KEY is not set; rule-based tags were retained."],
        )

    session = _session()
    results, calls, input_total, output_total, cost_total, errors = (
        {}, 0, 0, 0, 0.0, []
    )
    stop_statuses = {400, 401, 402, 403, 404, 413, 422, 429}
    min_interval = max(
        0.0,
        float(_setting("LLM_MIN_REQUEST_INTERVAL_SECONDS", 5.0)),
    )
    last_request_at = None

    try:
        for i in range(0, len(posts), BATCH_SIZE):
            if last_request_at is not None and min_interval:
                remaining = min_interval - (time.monotonic() - last_request_at)
                if remaining > 0:
                    time.sleep(remaining)

            last_request_at = time.monotonic()
            batch = posts[i:i + BATCH_SIZE]

            try:
                got, input_tokens, output_tokens, cost = tag_batch(session, batch)
                results.update(got)
                calls += 1
                input_total += input_tokens
                output_total += output_tokens
                cost_total += cost

            except GeminiRateLimitError as exc:
                errors.append(
                    f"LLM batch {i // BATCH_SIZE + 1}: {exc} "
                    "Remaining batches were not sent."
                )
                log.warning("Gemini rate-limited Fresher Radar; stopping this tagging run.")
                break

            except GeminiAPIError as exc:
                errors.append(f"LLM batch {i // BATCH_SIZE + 1}: {exc}")
                if (
                    exc.status_code in stop_statuses
                    or (exc.status_code and exc.status_code >= 500)
                ):
                    errors.append(
                        "Remaining batches were not sent; fix the Gemini API error "
                        "and retry later."
                    )
                    break

            except Exception as exc:
                log.warning("LLM batch failed (%s)", type(exc).__name__)
                errors.append(
                    f"LLM batch {i // BATCH_SIZE + 1}: "
                    f"{type(exc).__name__}: {str(exc)[:250]}"
                )

    finally:
        session.close()

    return (
        results,
        calls,
        input_total,
        output_total,
        cost_total,
        errors,
    )
