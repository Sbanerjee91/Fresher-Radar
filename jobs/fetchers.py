"""Where jobs come from. India only, official/public APIs only (no scraping).

Every fetcher returns a list of `Listing`s that already passed the India check and the
fresher filter. Failures raise, and `collect()` records them instead of crashing the sync.

Sources and why they are allowed:
- Adzuna, Jooble: official job-search APIs, used with our own free API keys and credited in the footer.
- Greenhouse, Lever: the public JSON job-board endpoints companies publish for exactly this use.
Sites whose terms forbid automated collection (Naukri, LinkedIn, Internshala, Indeed...) are NOT used.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .places import parse_location

TIMEOUT = (3, 10)  # connect, read (seconds)

GREENHOUSE_BOARDS = [
    "razorpay", "phonepe", "groww", "cred", "meesho", "postman", "browserstack",
    "chargebee", "freshworks", "clevertap", "druva", "rubrik", "nutanix",
    "databricks", "stripe", "coinbase", "figma", "gitlab", "cloudflare",
    "datadog", "mongodb", "elastic", "twilio", "okta", "hubspot", "asana",
    "notion", "discord", "reddit", "robinhood", "plaid", "brex", "ramp",
    "airtable", "miro",
]
LEVER_BOARDS = [
    "cred", "zeta", "atherenergy", "spinny", "khatabook", "plivo", "hasura",
    "highlevel", "leenaai", "yellowai", "moengage", "gupshup",
]
ADZUNA_QUERIES = [
    "fresher", "intern", "internship", "graduate trainee", "entry level", "junior developer",
    "trainee", "campus hiring", "associate software engineer", "data analyst fresher",
]
ADZUNA_PAGES = 3
INDIA_SOURCES = {"Adzuna India", "Jooble India"}  # queried for India only, so a bare "Remote" is trusted


class Listing(NamedTuple):
    title: str
    company: str
    location: str
    source: str
    url: str
    city: str = ""      # canonical city, filled by _listing()
    snippet: str = ""   # first ~250 chars of the description, only used as extra context for the LLM


# --- fresher filter ----------------------------------------------------------
# Word-boundary matching: "intern" must not match "internal" or "international".
def _words(*terms):
    return re.compile(r"(?<![a-z])(?:" + "|".join(terms) + r")(?![a-z])", re.I)


INCLUDE_TITLE = _words(
    r"intern(?:ship)?s?", "fresher", "junior", r"jr\.?", r"entry[- ]level", "graduate",
    "trainee", "associate", "apprentice", r"new grad", "campus",
)
EXCLUDE_TITLE = _words(
    "senior", r"sr\.?", "lead", "principal", "staff", "manager", "director",
    r"head of", "vp", r"vice president", "architect", r"[3-9]\+ years",
)
FRESHER_IN_DESCRIPTION = _words(r"0-1 years?", r"0-2 years?", "freshers can apply", r"entry[- ]level", r"recent graduates?")


_YEARS = r"(\d{1,2})\s*(?:\+|(?:-|–|to)\s*\d{1,2})?\s*(?:years?|yrs?)"
_YEARS_THEN_EXP = re.compile(_YEARS + r"[^.\n]{0,40}?experience", re.I)
_EXP_THEN_YEARS = re.compile(r"experience[^.\n]{0,30}?" + _YEARS, re.I)


def min_years_required(description):
    """Lowest "N years of experience" figure mentioned (e.g. "3-5 years" -> 3), or None."""
    text = re.sub(r"<[^>]+>", " ", (description or "")[:4000])
    found = [int(m.group(1)) for rx in (_YEARS_THEN_EXP, _EXP_THEN_YEARS) for m in rx.finditer(text)]
    return min(found) if found else None


def is_fresher_job(title, description=""):
    if EXCLUDE_TITLE.search(title):
        return False
    years = min_years_required(description)
    if years is not None and years >= 3:  # "Developer" + "3+ years experience" is not a fresher job
        return False
    if INCLUDE_TITLE.search(title):
        return True
    return bool(FRESHER_IN_DESCRIPTION.search(re.sub(r"<[^>]+>", " ", description or "")[:600]))


# --- http --------------------------------------------------------------------
def _session():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (compatible; FresherRadar/2.0)"
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _get_json(session, url, **params):
    response = session.get(url, params=params or None, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def _listing(title, company, location, source, url, description=""):
    """Build a Listing, or None if it is not in India, not a fresher job, or has no usable link."""
    title, url = (title or "").strip(), (url or "").strip()
    if not title or not url.lower().startswith(("http://", "https://")):
        return None
    city, in_india = parse_location(location, source in INDIA_SOURCES)
    if not in_india or not is_fresher_job(title, description):
        return None
    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", description or "")).strip()[:250]
    return Listing(title, (company or "Company").strip(), (location or "India").strip(), source, url, city, snippet)


def _compact(items):
    return [i for i in items if i]


# --- sources -----------------------------------------------------------------
def fetch_adzuna():
    session, out = _session(), []
    for query in ADZUNA_QUERIES:
        for page in range(1, ADZUNA_PAGES + 1):
            data = _get_json(
                session, f"https://api.adzuna.com/v1/api/jobs/in/search/{page}",
                app_id=settings.ADZUNA_APP_ID, app_key=settings.ADZUNA_APP_KEY,
                results_per_page=50, what=query,
            )
            results = data.get("results", [])
            for j in results:
                out.append(_listing(
                    j.get("title"), (j.get("company") or {}).get("display_name"),
                    (j.get("location") or {}).get("display_name") or "India",
                    "Adzuna India", j.get("redirect_url"), j.get("description"),
                ))
            if len(results) < 50:  # last page for this query
                break
    return _compact(out)


JOOBLE_QUERIES = ["fresher", "intern", "graduate trainee", "entry level"]


def fetch_jooble():
    session, out = _session(), []
    for query in JOOBLE_QUERIES:
        for page in (1, 2):
            response = session.post(
                f"https://jooble.org/api/{settings.JOOBLE_API_KEY}",
                json={"keywords": query, "location": "India", "page": str(page)}, timeout=TIMEOUT,
            )
            response.raise_for_status()
            for j in response.json().get("jobs", []):
                out.append(_listing(j.get("title"), j.get("company"), j.get("location") or "India",
                                    "Jooble India", j.get("link"), j.get("snippet")))
    return _compact(out)


def _board_name(slug):
    return slug.replace("-", " ").title()


def fetch_greenhouse(slug):
    response = _session().get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=TIMEOUT)
    if response.status_code == 404:  # company has no board (any more): not an error
        return []
    response.raise_for_status()
    return _compact(
        _listing(j.get("title"), _board_name(slug), (j.get("location") or {}).get("name"),
                 "Greenhouse", j.get("absolute_url"))
        for j in response.json().get("jobs", [])
    )


def fetch_lever(slug):
    response = _session().get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=TIMEOUT)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    return _compact(
        _listing(j.get("text"), _board_name(slug), (j.get("categories") or {}).get("location"),
                 "Lever", j.get("hostedUrl"), j.get("descriptionPlain"))
        for j in response.json()
    )


def _tasks():
    tasks = []
    if settings.ADZUNA_APP_ID and settings.ADZUNA_APP_KEY:
        tasks.append(("Adzuna India", fetch_adzuna))
    if settings.JOOBLE_API_KEY:
        tasks.append(("Jooble India", fetch_jooble))
    tasks += [(f"Greenhouse:{s}", lambda s=s: fetch_greenhouse(s)) for s in GREENHOUSE_BOARDS]
    tasks += [(f"Lever:{s}", lambda s=s: fetch_lever(s)) for s in LEVER_BOARDS]
    return tasks


def collect():
    """Run every source in parallel. Returns (listings, errors)."""
    listings, errors = [], []
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [(name, pool.submit(fn)) for name, fn in _tasks()]
        for name, future in futures:
            try:
                listings.extend(future.result())
            except Exception as exc:  # one broken source must not stop the others
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
    return listings, errors
