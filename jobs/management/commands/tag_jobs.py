from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs import llm
from jobs.models import Job, SyncLog
from jobs.sync import tag_with_llm


class Command(BaseCommand):
    help = "Tag active jobs with OpenRouter. Default: rule-tagged jobs only; --all re-tags every active job."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Re-tag every active job")
        parser.add_argument("--limit", type=int, default=200, help="Maximum jobs to process (default: 200)")

    def handle(self, *args, all=False, limit=200, **options):
        if not llm.enabled():
            self.stderr.write("OPENROUTER_API_KEY is not set. Add a valid OpenRouter key to .env.")
            return
        if limit < 1:
            self.stderr.write("--limit must be at least 1.")
            return

        qs = Job.objects.filter(is_active=True)
        if not all:
            qs = qs.filter(tag_method="rules")
        jobs = list(qs[:limit])
        if not jobs:
            self.stdout.write("No jobs need tagging.")
            return

        started = timezone.now()
        run_log = SyncLog.objects.create(started_at=started)
        try:
            tagged, calls, tin, tout, cost, errors = tag_with_llm(jobs)
            run_log.tagged_llm = tagged
            run_log.tagged_rules = len(jobs) - tagged
            run_log.llm_calls = calls
            run_log.tokens_in = tin
            run_log.tokens_out = tout
            run_log.llm_cost_usd = cost
            run_log.total_active = Job.objects.filter(is_active=True).count()
            run_log.errors = "\n".join(errors)
            run_log.status = SyncLog.Status.PARTIAL if errors else SyncLog.Status.SUCCESS
            self.stdout.write(
                f"{run_log.status.upper()}: LLM-tagged {tagged}/{len(jobs)} jobs in {calls} successful calls "
                f"({tin:,} input tokens, {tout:,} output tokens, ${cost:.6f})."
            )
            for error in errors:
                self.stderr.write(f"  note - {error}")
        except Exception as exc:
            run_log.status = SyncLog.Status.FAILED
            run_log.errors = f"{type(exc).__name__}: {str(exc)[:500]}"
            raise
        finally:
            run_log.finished_at = timezone.now()
            run_log.save()

        self.stdout.write(f"Run metrics saved in SyncLog #{run_log.pk}; run `python manage.py cost_report` to inspect cost.")
