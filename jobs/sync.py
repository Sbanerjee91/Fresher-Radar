"""One sync = fetch -> dedupe -> store -> LLM-tag the new posts -> retire stale ones -> SyncLog."""
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import fetchers, llm
from .dedupe import norm_company, norm_title, similar_titles
from .models import Job, SyncLog
from .tagging import rules_role

CHUNK = 500  # keeps SQL "IN (...)" lists small for SQLite
STALE_RUN_MINUTES = 30


def _chunks(items, size=CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _store(listings, now):
    """Insert genuinely new jobs, refresh `last_seen` on known ones.

    Returns (new Job objects, duplicates dropped, {hash: snippet} for the LLM).
    """
    # 1) exact duplicates inside this batch (same job on two boards / listed twice)
    unique, duplicates = {}, 0
    for item in listings:
        h = Job.make_hash(item.company, item.title, item.city)
        if h in unique:
            duplicates += 1
        else:
            unique[h] = item

    # 2) already in the database? just mark it as seen again (and active again)
    known = set()
    for chunk in _chunks(list(unique)):
        known.update(Job.objects.filter(job_hash__in=chunk).values_list("job_hash", flat=True))
        Job.objects.filter(job_hash__in=chunk).update(last_seen=now, is_active=True)

    # 3) fuzzy duplicates: same company + city and an almost identical title
    by_company = defaultdict(list)  # norm company -> [(norm title, city, db id or None)]
    for pk, company, title, city in Job.objects.filter(is_active=True).values_list("id", "company", "title", "city"):
        by_company[norm_company(company)].append((norm_title(title), city, pk))

    fresh, refresh_ids, snippets = [], [], {}
    for h, item in unique.items():
        if h in known:
            continue
        key, title = norm_company(item.company), norm_title(item.title)
        match = next((m for m in by_company[key] if m[1] == item.city and similar_titles(title, m[0])), None)
        if match:
            duplicates += 1
            if match[2]:
                refresh_ids.append(match[2])
            continue
        by_company[key].append((title, item.city, None))
        snippets[h] = item.snippet
        fresh.append(Job(
            title=item.title[:255], company=item.company[:255], location=item.location[:255], city=item.city,
            role=rules_role(item.title), source=item.source, apply_url=item.url[:500], job_hash=h,
            first_seen=now, last_seen=now,
        ))
    for chunk in _chunks(refresh_ids):
        Job.objects.filter(id__in=chunk).update(last_seen=now)
    Job.objects.bulk_create(fresh, batch_size=CHUNK)
    return fresh, duplicates, snippets


def tag_with_llm(jobs, snippets=None):
    """Upgrade rule-based tags to LLM tags. Returns (tagged, calls, tokens_in, tokens_out, cost_usd, errors).

    Jobs the model fails on keep their rule-based tags, so a post is never left untagged.
    """
    if not jobs or not llm.enabled():
        return 0, 0, 0, 0, 0.0, []
    snippets = snippets or {}
    posts = [
        {"id": j.id, "title": j.title, "company": j.company, "location": j.location,
         "about": snippets.get(j.job_hash, ""), "fallback_city": j.city}
        for j in jobs
    ]
    results, calls, tin, tout, cost, errors = llm.tag_all(posts)
    now, changed = timezone.now(), []
    for job in jobs:
        if job.id in results:
            job.role, job.city = results[job.id]
            job.tag_method, job.tagged_at = "llm", now
            changed.append(job)
    Job.objects.bulk_update(changed, ["role", "city", "tag_method", "tagged_at"], batch_size=CHUNK)
    return len(changed), calls, tin, tout, cost, errors


def run_sync():
    """Returns the finished SyncLog, or None if another sync is already running."""
    now = timezone.now()
    SyncLog.objects.filter(
        status=SyncLog.Status.RUNNING, started_at__lt=now - timedelta(minutes=STALE_RUN_MINUTES)
    ).update(status=SyncLog.Status.FAILED, finished_at=now, errors="Interrupted")
    if SyncLog.objects.filter(status=SyncLog.Status.RUNNING).exists():
        return None

    log = SyncLog.objects.create(started_at=now)
    try:
        listings, errors = fetchers.collect()
        finished = timezone.now()
        new_jobs, log.duplicates, snippets = _store(listings, finished)
        log.added = len(new_jobs)

        # tag the new posts, plus any older ones an earlier run could not tag (no key / API outage)
        pending = list(Job.objects.filter(is_active=True, tag_method="rules").exclude(id__in=[j.id for j in new_jobs])[:200])
        tagged, log.llm_calls, log.tokens_in, log.tokens_out, log.llm_cost_usd, llm_errors = tag_with_llm(new_jobs + pending, snippets)
        log.tagged_llm, log.tagged_rules = tagged, len(new_jobs) + len(pending) - tagged
        errors += llm_errors
        if not llm.enabled() and (new_jobs or pending):
            errors.append("LLM tagging skipped: OPENROUTER_API_KEY is not set (rule-based tags used)")

        if listings:  # never retire jobs because of an outage (no internet = no data, not "no jobs")
            log.expired = Job.objects.filter(
                is_active=True, last_seen__lt=finished - timedelta(days=settings.JOB_EXPIRY_DAYS)
            ).update(is_active=False)
        log.total_active = Job.objects.filter(is_active=True).count()
        log.errors = "\n".join(errors)
        if not listings:
            log.status = SyncLog.Status.FAILED
        else:
            log.status = SyncLog.Status.PARTIAL if errors else SyncLog.Status.SUCCESS
    except Exception as exc:
        log.status, log.errors = SyncLog.Status.FAILED, f"{type(exc).__name__}: {exc}"
    log.finished_at = timezone.now()
    log.save()
    return log
