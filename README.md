# Fresher Radar

A live job board of fresher / internship posts across India. It pulls jobs from public APIs, removes
duplicates, tags every post by **role** and **city** with an LLM (via OpenRouter), and refreshes itself every night
just after 12:00 AM IST. UI controls are from [Sakuga VFX](https://github.com/finktheartist/sakuga-vfx) (MIT).

```
Adzuna / Jooble / Greenhouse / Lever  ->  India filter -> fresher filter -> dedupe -> LLM tags -> DB -> web page
                       ^ GitHub Actions cron, 00:05 IST                                             (Postgres)
```

## Run locally

```bash
python -m venv venv && venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                               # add your API keys
python manage.py migrate
python manage.py fetch_jobs                          # first sync (also runs nightly while runserver is up)
python manage.py runserver
python manage.py test                                # 34 tests
```

## Commands

| Command | What it does |
|---|---|
| `fetch_jobs` | Full sync: fetch, dedupe, tag, retire stale posts. Exits non-zero on failure. |
| `tag_jobs [--all] [--limit N]` | Tag jobs and save run usage metrics (default limit: 200). |
| `export_data --out jobs.csv` | All active jobs as CSV, for the Google Sheet. |
| `eval_sample` / `eval_score` | Blind 50-post hand-check and accuracy scoring (see `docs/SUBMISSION.md`). |
| `cost_report` | Real LLM cost per 1,000 posts from the logged token counts. |

## Deploy (free): Render + Neon + GitHub Actions

1. **Database:** create a free Postgres at [neon.tech](https://neon.tech), copy the connection string.
2. **Repo:** push this folder to GitHub (`.env` and `db.sqlite3` are git-ignored).
3. **Website:** on [render.com](https://render.com) choose *New > Blueprint*, pick the repo (it reads `render.yaml`),
   and paste the Neon string as `DATABASE_URL`.
4. **Nightly sync:** in the repo go to *Settings > Secrets and variables > Actions* and add
   `DATABASE_URL`, `OPENROUTER_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `DJANGO_SECRET_KEY`.
   Optionally add a repository *variable* `LLM_MODEL` to pick the model. Then run the workflow once by hand (*Actions > Daily job sync > Run workflow*) to fill the database.
   After that it runs by itself at 12:05 AM IST.

Why Actions and not a scheduler inside the website? Free web hosts sleep when idle, and a sleeping site
cannot run a midnight job. Actions wakes up on its own, writes to the shared database, and emails you if a sync fails.

## OpenRouter LLM setup

1. Create an API key at [OpenRouter API Keys](https://openrouter.ai/keys).
2. Copy `.env.example` to `.env` and put the OpenRouter key in `OPENROUTER_API_KEY`.
3. Use a **chat-completions** model ID. The default is `google/gemma-4-26b-a4b-it:free`, which currently supports JSON output on OpenRouter. Do not set `LLM_BASE_URL`; this project uses the fixed OpenRouter URL `https://openrouter.ai/api/v1`.
4. Test with `python manage.py tag_jobs --limit 20` before tagging a larger group.

Changing the model is one setting: `LLM_MODEL=<model id from openrouter.ai/models>`. `temperature=0`, JSON response mode, a 3.1-second minimum between requests,
and usage/cost reporting are enabled by the client. Compare candidate models with `eval_score` on the same 50 hand-labelled
posts. Set `LLM_PRICE_IN` and `LLM_PRICE_OUT` in USD per million tokens if your selected model requires fallback cost
estimation and the response does not report a cost.

**Free-tier note:** OpenRouter currently documents 20 requests/minute and 50 requests/day for `:free` model variants on
accounts without the qualifying credit top-up. Failed attempts count toward the daily limit. A batch contains 20 jobs, so
200 posts require about 10 successful requests. See [OpenRouter free-model limits](https://openrouter.ai/collections/free-models/).

## Data sources (respecting each site's terms)

Only official APIs and public job-board endpoints: Adzuna and Jooble (own API keys, credited in the footer),
Greenhouse and Lever (the public JSON endpoints companies publish). No scraping of Naukri, LinkedIn,
Internshala or Indeed, whose terms forbid it.
