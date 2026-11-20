"""Django settings for Fresher Radar.

Secrets and per-machine options come from environment variables or a local
`.env` file (see `.env.example`). Nothing sensitive lives in this file.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Tiny .env reader so no extra package is needed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


DEBUG = _env_bool("DJANGO_DEBUG", True)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "jobs",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fresher_radar.urls"
WSGI_APPLICATION = "fresher_radar.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

def _database():
    """SQLite locally; any Postgres (Neon, Supabase, Render...) via DATABASE_URL in production."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    from urllib.parse import parse_qs, unquote, urlparse

    u = urlparse(url)
    config = {
        "ENGINE": "django.db.backends.postgresql", "NAME": u.path.lstrip("/"), "USER": unquote(u.username or ""),
        "PASSWORD": unquote(u.password or ""), "HOST": u.hostname or "", "PORT": u.port or "",
        "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True,
    }
    sslmode = parse_qs(u.query).get("sslmode", [""])[0]
    if sslmode:
        config["OPTIONS"] = {"sslmode": sslmode}
    return config


DATABASES = {"default": _database()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"django.contrib.auth.password_validation.{n}"}
    for n in (
        "UserAttributeSimilarityValidator",
        "MinimumLengthValidator",
        "CommonPasswordValidator",
        "NumericPasswordValidator",
    )
]

LANGUAGE_CODE = "en-us"
# "12 AM" in this project means midnight in India. Dates are still stored as UTC.
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = False
USE_TZ = True

if not DEBUG:  # production: serve static files from the app itself, behind the host's HTTPS proxy
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    }
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_ORIGINS", "").split(",") if o]
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_BASE_URL = os.getenv(
    "GEMINI_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta"
)

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "gemini-3.5-flash-lite"
)

LLM_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.getenv("LLM_MIN_REQUEST_INTERVAL_SECONDS", "5")
)

GEMINI_INPUT_PRICE_PER_MILLION = float(
    os.getenv("GEMINI_INPUT_PRICE_PER_MILLION", "0")
)

GEMINI_OUTPUT_PRICE_PER_MILLION = float(
    os.getenv("GEMINI_OUTPUT_PRICE_PER_MILLION", "0")
)

LLM_PRICE_IN = GEMINI_INPUT_PRICE_PER_MILLION
LLM_PRICE_OUT = GEMINI_OUTPUT_PRICE_PER_MILLION

AUTO_SYNC = _env_bool("AUTO_SYNC", True)
AUTO_SYNC_AT = (0, 5)          # local time (hour, minute): just after 12:00 AM
JOB_EXPIRY_DAYS = 7            # hide a job once no source has listed it for this long

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")        # https://developer.adzuna.com/
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
JOOBLE_API_KEY = os.environ.get("JOOBLE_API_KEY", "")      # https://jooble.org/api/about
