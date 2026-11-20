"""Display safe OpenRouter API-key quota metadata without making an LLM call."""
import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Check OpenRouter key status and free-model daily quota without using inference credits."

    def handle(self, *args, **options):
        key = str(getattr(settings, "OPENROUTER_API_KEY", "") or "").strip()
        if not key:
            raise CommandError("OPENROUTER_API_KEY is missing. Add it to .env first.")

        try:
            response = requests.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {key}"},
                timeout=(5, 20),
            )
        except requests.RequestException as exc:
            raise CommandError(f"Could not reach OpenRouter ({type(exc).__name__}).") from exc

        if response.status_code != 200:
            # Do not print headers, the API key, or the full response payload.
            raise CommandError(f"OpenRouter key check failed with HTTP {response.status_code}.")

        try:
            data = response.json().get("data", {})
        except (ValueError, AttributeError) as exc:
            raise CommandError("OpenRouter returned an unexpected key-metadata response.") from exc

        quota = data.get("free_model_daily_requests") or {}
        self.stdout.write(self.style.SUCCESS("OpenRouter key is valid."))
        self.stdout.write(f"Free-tier account: {data.get('is_free_tier', 'not reported')}")
        if quota:
            self.stdout.write(
                "Free-model requests today (UTC): "
                f"{quota.get('used', '?')} used / {quota.get('limit', '?')} allowed; "
                f"{quota.get('remaining', '?')} remaining"
            )
        else:
            self.stdout.write("Free-model daily quota: not reported for this key/account.")
        remaining = data.get("limit_remaining")
        if remaining is not None:
            self.stdout.write(f"Key credit-limit remaining: {remaining}")
        self.stdout.write(f"Model configured in Fresher Radar: {settings.LLM_MODEL}")
