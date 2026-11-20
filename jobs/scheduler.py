"""Daily auto-sync, no cron or extra packages needed.

A background thread makes sure one sync happens every night just after 12:00 AM
(local time). If the computer was off or offline at that moment, the sync runs
as soon as the server is back, so the data is never a day behind.
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

log = logging.getLogger(__name__)
_stop = threading.Event()
_lock = threading.Lock()
_thread = None
RETRY_AFTER = timedelta(hours=1)


def _slot(day):
    hour, minute = settings.AUTO_SYNC_AT
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def previous_run(now=None):
    """The most recent scheduled moment that is not in the future."""
    now = timezone.localtime(now or timezone.now())
    today = _slot(now)
    return today if now >= today else today - timedelta(days=1)


def next_run(now=None):
    now = timezone.localtime(now or timezone.now())
    return previous_run(now) + timedelta(days=1)


def is_due(now=None):
    """True if no successful sync has happened since the last scheduled moment."""
    from .models import SyncLog

    return not SyncLog.objects.filter(
        finished_at__gte=previous_run(now),
        status__in=[SyncLog.Status.SUCCESS, SyncLog.Status.PARTIAL],
    ).exists()


def _sync_now():
    from .sync import run_sync

    close_old_connections()
    try:
        result = run_sync()
        if result:
            log.info("Auto-sync %s: +%s new, %s expired", result.status, result.added, result.expired)
    except Exception:
        log.exception("Auto-sync crashed")
    finally:
        close_old_connections()


def _loop():
    """Every minute: is today's sync missing? Then run it (and retry hourly if it fails).

    Checking the wall clock instead of sleeping until midnight means a laptop
    that slept through 12 AM, a restart, or a failed attempt all heal themselves.
    """
    last_try = None
    _stop.wait(5)  # let the server finish booting first
    while not _stop.is_set():
        now = timezone.now()
        try:
            if (last_try is None or now - last_try >= RETRY_AFTER) and is_due(now):
                last_try = now
                _sync_now()
        except Exception:  # e.g. migrations not applied yet
            log.exception("Auto-sync check failed")
        _stop.wait(60)


def start():
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="job-autosync", daemon=True)
        _thread.start()
