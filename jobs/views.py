from datetime import timedelta

from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from . import scheduler
from .models import Job, SyncLog

PAGE_SIZE = 24
MAX_PAGE_SIZE = 60
SYNC_OVERDUE_AFTER = timedelta(hours=36)

def _int(value, default, low, high):
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def _search(params):
    """Filter + paginate active jobs. Shared by the page and the JSON API."""
    now = timezone.now()
    qs = Job.objects.filter(is_active=True)

    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(company__icontains=q))
    loc = params.get("loc", "").strip()
    if loc:
        qs = qs.filter(Q(city__icontains=loc) | Q(location__icontains=loc))
    if params.get("role"):
        qs = qs.filter(role=params["role"])
    if params.get("city"):
        qs = qs.filter(city=params["city"])
    source = params.get("source", "").strip()
    if source:
        qs = qs.filter(source__iexact=source)
    if params.get("new") == "1":
        qs = qs.filter(first_seen__gte=now - timedelta(hours=24))

    offset = _int(params.get("offset"), 0, 0, 10**6)
    limit = _int(params.get("limit"), PAGE_SIZE, 1, MAX_PAGE_SIZE)
    total = qs.count()
    fresh_after = now - timedelta(hours=24)
    jobs = [
        {
            "id": j.id,
            "title": j.title,
            "company": j.company,
            "location": j.location,
            "source": j.source,
            "apply_url": j.apply_url,
            "posted_at": timezone.localtime(j.first_seen).strftime("%b %d, %Y"),
            "is_new": j.first_seen >= fresh_after,
            "role": j.role,
            "city": j.city,
            "ai": j.tag_method == "llm",
        }
        for j in qs[offset:offset + limit]
    ]
    return {"jobs": jobs, "total_count": total, "has_more": offset + limit < total}


def _top(qs, field, n, skip=("",)):
    """Most common values of a field, e.g. the 9 biggest cities, for the filter chips."""
    rows = qs.exclude(**{f"{field}__in": list(skip)}).values(field).annotate(n=Count("id")).order_by("-n", field)[:n]
    return [{"name": r[field], "count": r["n"]} for r in rows]


def index(request):
    active = Job.objects.filter(is_active=True)
    last_sync = SyncLog.objects.exclude(status__in=[SyncLog.Status.RUNNING, SyncLog.Status.FAILED]).first()
    # Databases from before sync logging existed have no SyncLog yet: fall back to the newest job.
    last_sync_at = last_sync.finished_at if last_sync else active.aggregate(t=Max("first_seen"))["t"]
    return render(request, "jobs/index.html", {
        "initial": _search({}),
        "sources": list(active.order_by("source").values_list("source", flat=True).distinct()),
        "roles": _top(active, "role", 9),
        "cities": _top(active, "city", 9, skip={"", "India (unspecified)"}),
        "city_count": active.exclude(city__in=["", "India (unspecified)", "Remote"]).values("city").distinct().count(),
        "total": active.count(),
        "new_today": active.filter(first_seen__gte=timezone.now() - timedelta(hours=24)).count(),
        "last_sync": last_sync_at,
        "next_sync": scheduler.next_run(),
        "sync_overdue": not last_sync_at or timezone.now() - last_sync_at > SYNC_OVERDUE_AFTER,
    })


def jobs_api(request):
    return JsonResponse(_search(request.GET))
