# Fresher Radar 🚀

**Fresher Radar** is an AI-assisted job discovery platform that brings fresher and internship opportunities in India into one searchable place. It collects listings from configured public job APIs and public company job-board endpoints, filters for relevant India-based entry-level opportunities, removes duplicates, classifies jobs by **role** and **city** using Google's Gemini API, and displays the results in a Django-powered web application.

> **Live demo:** [Add your deployed website URL here]  
> **Repository:** [Add your GitHub repository URL here]

---

## Table of contents

- [Why Fresher Radar?](#why-fresher-radar)
- [Features](#features)
- [How it works](#how-it-works)
- [How AI tagging works](#how-ai-tagging-works)
- [Technology stack](#technology-stack)
- [Data sources](#data-sources)
- [Run locally](#run-locally)
- [Environment variables](#environment-variables)
- [Management commands](#management-commands)
- [Evaluation and cost measurement](#evaluation-and-cost-measurement)
- [Daily refresh and deployment](#daily-refresh-and-deployment)
- [Project structure](#project-structure)
- [API endpoint](#api-endpoint)
- [Responsible data collection and security](#responsible-data-collection-and-security)
- [Limitations](#limitations)

---

## Why Fresher Radar?

Students and recent graduates often need to search across several platforms to find internships and entry-level jobs. The same listing may appear on more than one source, and job titles and locations are not always written consistently.

Fresher Radar addresses this by:

1. Collecting fresher and internship listings from multiple configured sources.
2. Filtering out listings that do not match the India and fresher criteria.
3. Detecting duplicate listings before storing them.
4. Assigning a consistent role and city to each job using an LLM, with a rule-based fallback.
5. Making the resulting listings searchable and filterable from one website.

The aim is to reduce the effort required to discover relevant early-career opportunities. Fresher Radar does not guarantee that a listing is still open; users should verify details on the original application page.

## Features

- **Multi-source collection:** fetches jobs from Adzuna, Jooble, Greenhouse and Lever sources configured in the project.
- **India and fresher filtering:** applies location and entry-level relevance checks before a listing is saved.
- **Duplicate detection:** combines normalized SHA-256 keys with fuzzy title similarity checks.
- **AI job classification:** uses Gemini to classify the work into a predefined role taxonomy and standardize the city.
- **Rule-based fallback:** keeps a basic classification when the Gemini key is missing or an API request fails.
- **Batch processing:** sends jobs to the LLM in batches rather than making one request per listing.
- **Search and filters:** search by title/company and filter by role, city, source and recently added jobs.
- **Saved jobs:** lets users save listings in the browser.
- **Sync tracking:** records collection and tagging statistics, token usage, estimated cost and errors.
- **Evaluation utilities:** supports a blind manual sample and comparison of AI tags with human labels and a rule-based baseline.
- **Scheduled refresh:** supports a daily GitHub Actions workflow.

## How it works

```text
Adzuna / Jooble / Greenhouse / Lever
                 │
                 ▼
          Collect job listings
                 │
                 ▼
       India + fresher filtering
                 │
                 ▼
          Deduplication
                 │
                 ▼
       Initial rule-based tags
                 │
                 ▼
      Gemini role + city tagging
          (batches of 20)
                 │
                 ▼
       Validate and save results
                 │
                 ▼
       Django database (SQLite /
            PostgreSQL)
                 │
                 ▼
      Searchable Fresher Radar UI
```

A sync is designed to process new listings and retry older active listings that still have rule-based tags. Existing listings are marked inactive when they have not been seen for the configured expiry period. The system avoids expiring all listings when a collection run returns no data, because an upstream outage should not be treated as proof that every job has closed.

### Filtering vs. deduplication vs. tagging

These are separate stages:

| Stage | What it answers | Example |
|---|---|---|
| Filtering | Should this listing be included? | An internship in India is included; a senior role is excluded. |
| Deduplication | Have we already stored this job? | Two copies of the same company role are reduced to one record. |
| Tagging | What category and city describe this job? | `Frontend Developer Intern` → role `Frontend`, city `Bengaluru`. |

## How AI tagging works

AI tagging is the classification stage of Fresher Radar. It does **not** fetch jobs or decide whether a job is a duplicate. It labels a job that has already passed the collection and filtering stages.

### 1. Prepare the input

For each job, the backend prepares a compact payload containing fields such as:

- Database job ID
- Job title
- Company
- Original location text
- A short description or summary, when available

### 2. Apply the classification instructions

The system prompt instructs Gemini to:

- Classify the actual work rather than relying only on words such as `intern`, `trainee` or `associate`.
- Choose a role from the project's predefined role taxonomy.
- Use a specific category such as Frontend, Backend, Full Stack, Mobile, Data & Analytics, AI / ML, DevOps & Cloud, QA & Testing, Design (UI/UX) or another supported category when the listing provides enough evidence.
- Use `Other` when no category fits.
- Standardize city spellings, for example `Bangalore` to `Bengaluru`.
- Use `Remote` for remote or work-from-home listings and avoid inventing a city that is not stated.

### 3. Send jobs in batches

The current LLM module uses a batch size of **20 jobs**. It sends the prepared data to Google's Gemini Interactions API using the model configured by `LLM_MODEL` (currently set to `gemini-3.5-flash-lite` in the project configuration). A request interval is configured to reduce the chance of exceeding rate limits.

### 4. Receive structured results

The expected response contains the original job ID and its classification, for example:

```json
{
  "posts": [
    {
      "id": 123,
      "role": "Frontend",
      "city": "Bengaluru"
    }
  ]
}
```

The backend matches each result to its original database record using the ID, validates the role against the supported taxonomy, normalizes the city and updates the job's tag fields.

### 5. Keep a fallback

New jobs receive an initial rule-based role. When Gemini successfully classifies a job, the record is marked as LLM-tagged. If the API key is unavailable or a request fails, the rule-based tag is retained. The website can distinguish LLM-tagged jobs from rule-tagged jobs.

## Technology stack

| Area | Technology |
|---|---|
| Backend | Python, Django |
| Frontend | HTML, CSS, JavaScript, Django Templates |
| AI classification | Google Gemini API — Interactions API |
| HTTP/API requests | `requests` |
| Local database | SQLite |
| Production database | PostgreSQL (configured through `DATABASE_URL`) |
| Production app server | Gunicorn |
| Static files | WhiteNoise |
| Scheduled sync | GitHub Actions |
| Hosting configuration | Render Blueprint (`render.yaml`) |

## Data sources

The project is configured to use:

- **Adzuna:** official job-search API; requires an application ID and key.
- **Jooble:** official job-search API; requires an API key.
- **Greenhouse:** public JSON job-board endpoints for configured company boards.
- **Lever:** public JSON postings endpoints for configured company boards.

The Greenhouse and Lever company board identifiers are maintained in `jobs/fetchers.py`. The set of boards and the number of available jobs can change over time. A source may also fail temporarily or return no matching listings.

The project is designed around APIs and public job-board endpoints rather than scraping sites whose terms may prohibit automated collection. Always review the current terms and API requirements of each source before using or extending a connector.

## Run locally

### Prerequisites

- Python 3.12 or a compatible version supported by the dependencies.
- Git.
- API credentials for Gemini and, optionally, Adzuna and Jooble.

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

Replace the URL with your repository URL.

### 2. Create and activate a virtual environment

**Windows PowerShell / Command Prompt:**

```bash
python -m venv venv
venv\Scripts\activate
```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the same directory as `manage.py`. Add the variables shown in the next section. Do not commit this file.

### 5. Run database migrations

```bash
python manage.py migrate
```

### 6. Collect jobs

```bash
python manage.py fetch_jobs
```

This runs the full synchronization pipeline: collection, filtering, deduplication, storage, tagging and stale-listing expiry. API credentials are optional for sources that require them, but each missing source credential reduces the available source coverage.

### 7. Start the development server

```bash
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.

### 8. Run project tests

```bash
python manage.py check
python manage.py test
```

## Environment variables

Example `.env` configuration:

```env
# Django
DJANGO_DEBUG=True
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_TIME_ZONE=Asia/Kolkata

# Database (leave unset for local SQLite)
# DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

# Gemini API
GEMINI_API_KEY=your_gemini_api_key
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
LLM_MODEL=gemini-3.5-flash-lite
LLM_MIN_REQUEST_INTERVAL_SECONDS=5

# Price per one million tokens, in USD.
# Set these to the rates that match the billing tier actually used.
# Zero is appropriate only when reporting a free-tier estimate.
GEMINI_INPUT_PRICE_PER_MILLION=0.0
GEMINI_OUTPUT_PRICE_PER_MILLION=0.0

# Optional job-source credentials
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
JOOBLE_API_KEY=

# Sync behaviour
AUTO_SYNC=True
```

**Important:** The API key must be stored in `.env` locally or in the hosting/workflow secret manager. Never paste a real key into source code, screenshots, README files or public issue trackers. If a key has ever been committed or exposed, revoke it and create a replacement.

## Management commands

Run commands from the directory containing `manage.py`.

| Command | Purpose |
|---|---|
| `python manage.py check` | Run Django's configuration checks. |
| `python manage.py migrate` | Apply database migrations. |
| `python manage.py fetch_jobs` | Run the full fetch, filter, deduplicate, tag and expiry sync. |
| `python manage.py tag_jobs --limit 20` | Tag up to 20 active jobs that still have rule-based tags. |
| `python manage.py tag_jobs --all --limit 100` | Re-tag up to 100 active jobs, including previously LLM-tagged records. |
| `python manage.py export_data --out jobs_dataset.csv` | Export active job records to CSV. |
| `python manage.py eval_sample --n 50` | Create a blind 50-job evaluation sheet and a separate answer key. |
| `python manage.py eval_score` | Score the manually labelled sample against AI and rule-based tags. |
| `python manage.py cost_report` | Report recorded token usage and estimated tagging cost per 1,000 posts. |
| `python manage.py test` | Run the Django test suite. |

The `tag_jobs` command can be useful for retrying jobs that were left with rule-based tags after a previous API or quota failure. Start with a small `--limit` while checking a new API configuration.

## Evaluation and cost measurement

### Manual tagging evaluation

The project includes a blind-sample workflow so the person checking the predictions does not see the model's tags while entering their own labels.

1. First ensure that at least 50 active jobs have `tag_method="llm"`.
2. Run `python manage.py eval_sample --n 50`.
3. Open `eval_sheet.csv` and fill in `human_role` and `human_city` for each sampled job using the project's role taxonomy and the location information in the source listing.
4. Keep `eval_key.csv` separate while labelling. It contains the AI predictions and the rule-based baseline.
5. Run `python manage.py eval_score` to compare AI and rule-based labels with the human labels.
6. Report the measured role accuracy and city accuracy, the sample size, and any relevant confidence interval shown by the evaluation command.

Do not claim an accuracy percentage until the 50 labels have actually been reviewed and the scoring command has been run. Mention ambiguous or incomplete source locations when interpreting city accuracy.

### Cost per 1,000 tagged posts

The LLM module records token usage returned by the API and estimates cost using the configured per-million-token prices. The `cost_report` command aggregates the sync logs and calculates:

```text
estimated cost per 1,000 posts
  = (input-token cost + output-token cost)
    / number of LLM-tagged posts
    × 1,000
```

Use pricing values for the billing tier and model that were actually used. If you use a free tier and set the prices to zero, describe the result as a **free-tier cost estimate**, not as a general commercial cost. For comparison, you can also calculate a paid-tier estimate using the applicable published prices. Include the model ID, date of measurement, input/output tokens, number of tagged posts and the pricing assumptions in your report.

## Daily refresh and deployment

The repository includes:

- `render.yaml` for the Render web service configuration.
- `.github/workflows/daily-sync.yml` for the scheduled data refresh.

The workflow's cron expression is `35 18 * * *`, which corresponds to **00:05 IST** on the next calendar day. It can also be started manually from the GitHub Actions tab.

### Deployment outline

1. Push the project to GitHub. Confirm `.env`, `db.sqlite3`, API keys and local evaluation key files are excluded from version control.
2. Create a PostgreSQL database, for example on Neon, and copy its connection string.
3. In Render, create a new Blueprint from the GitHub repository and provide `DATABASE_URL`.
4. Set production secrets and variables in Render as needed, including `DJANGO_SECRET_KEY`, allowed hosts/CSRF origins and any credentials required by the web process.
5. In GitHub repository **Settings → Secrets and variables → Actions**, add the secrets used by the workflow:
   - `DATABASE_URL`
   - `GEMINI_API_KEY`
   - `ADZUNA_APP_ID`
   - `ADZUNA_APP_KEY`
   - `JOOBLE_API_KEY`
   - `DJANGO_SECRET_KEY`
6. Update `.github/workflows/daily-sync.yml` to pass `GEMINI_API_KEY` to the sync process (and remove the old `OPENROUTER_API_KEY` reference if it is still present).
7. Verify that the workflow uses the intended `LLM_MODEL` value and sets `DJANGO_DEBUG=0` and `AUTO_SYNC=0` for the scheduled process.
8. Run the workflow manually once. Check the Actions log and the `SyncLog` records for source failures, Gemini errors, token usage and the number of LLM-tagged jobs.
9. Open the deployed website and test search, filters, pagination and application links.

The website and scheduled worker are separate: the website serves the job board, while GitHub Actions runs the periodic sync against the shared PostgreSQL database. A successful deployment should be verified with a real workflow run; adding the workflow file alone does not prove that daily refresh is working.

## Project structure

```text
.
├── fresher_radar/
│   ├── settings.py          # Django settings and environment configuration
│   ├── urls.py              # Root URL configuration
│   └── wsgi.py              # WSGI entry point
├── jobs/
│   ├── fetchers.py          # Source connectors and fresher/India filters
│   ├── dedupe.py            # Exact and fuzzy duplicate detection
│   ├── llm.py               # Gemini API integration and batch tagging
│   ├── tagging.py           # Role taxonomy and rule-based classification
│   ├── places.py            # Location parsing and city normalization
│   ├── sync.py              # End-to-end synchronization orchestration
│   ├── models.py            # Job and SyncLog database models
│   ├── views.py             # Website view and job-search JSON API
│   ├── templates/jobs/      # Django HTML templates
│   ├── static/jobs/         # CSS and JavaScript assets
│   └── management/commands/
│       ├── fetch_jobs.py
│       ├── tag_jobs.py
│       ├── export_data.py
│       ├── eval_sample.py
│       ├── eval_score.py
│       └── cost_report.py
├── .github/workflows/
│   └── daily-sync.yml       # Scheduled job refresh
├── docs/
│   └── SUBMISSION.md        # Submission/evaluation notes
├── render.yaml              # Render deployment blueprint
├── requirements.txt
├── manage.py
└── README.md
```

## API endpoint

The project exposes a JSON endpoint for the job listings:

```text
GET /api/jobs/
```

Supported query parameters include:

| Parameter | Purpose |
|---|---|
| `q` | Search job title or company. |
| `loc` | Search city or original location text. |
| `role` | Filter by role. |
| `city` | Filter by normalized city. |
| `source` | Filter by source name. |
| `new=1` | Show jobs first seen in the last 24 hours. |
| `offset` | Pagination offset. |
| `limit` | Number of results (server-side maximum applies). |

Example:

```text
/api/jobs/?role=Frontend&city=Bengaluru&limit=24
```

## Responsible data collection and security

- Use official APIs and public job-board endpoints, and follow the applicable source terms, rate limits and attribution requirements.
- Preserve the original application URL so users can verify details and apply at the source.
- Do not collect from sites whose terms prohibit automated collection.
- Keep API keys, database URLs and Django secret keys in environment variables or secret managers.
- Do not commit `.env`, database files, generated exports containing personal data, or `eval_key.csv` unless there is a clear reason and permission to share them.
- Avoid logging full request URLs or headers if they could contain credentials.
- Use HTTPS and secure production settings when deploying.

## Limitations

- Source coverage depends on API access, credentials, configured company boards and each source's current availability.
- A fresher keyword filter can produce false positives or miss relevant jobs; it is a practical filter, not a guarantee of eligibility.
- LLM role and city tags are predictions. They should be measured against a manually reviewed sample and may require corrections.
- A city cannot be reliably inferred when the original listing does not provide one; such posts may be tagged as `Remote` or `India (unspecified)` according to the prompt and location parser.
- A listing may expire or be removed at its original source before the next refresh. Always verify on the application page.
- Scheduled refresh is only confirmed after the GitHub Actions workflow has been configured and a successful run has been observed.

---

## Acknowledgements

- [Django](https://www.djangoproject.com/)
- [Google Gemini API](https://ai.google.dev/)
- [Adzuna](https://developer.adzuna.com/)
- [Jooble](https://jooble.org/api/about)
- [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Render](https://render.com/)
- [Neon](https://neon.com/)

---

**Built as a fresher-focused job discovery project.**
