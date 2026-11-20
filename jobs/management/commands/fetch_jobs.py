from django.core.management.base import BaseCommand, CommandError

from jobs.sync import run_sync


class Command(BaseCommand):
    help = "Fetch India fresher jobs now: dedupe, tag with the LLM, retire stale posts. (Also runs nightly.)"

    def handle(self, *args, **options):
        result = run_sync()
        if result is None:
            self.stdout.write("Another sync is already running.")
            return
        for line in result.errors.splitlines():
            self.stderr.write(f"  note - {line}")
        self.stdout.write(
            f"{result.status.upper()}: added {result.added} | duplicates removed {result.duplicates} | "
            f"LLM-tagged {result.tagged_llm} (rules {result.tagged_rules}) | tokens {result.tokens_in} in / "
            f"{result.tokens_out} out (${result.llm_cost_usd:.4f}) | expired {result.expired} | active {result.total_active}"
        )
        if result.status == "failed":  # non-zero exit makes GitHub Actions / cron email you
            raise CommandError("Sync failed: " + (result.errors.splitlines() or ["no jobs fetched"])[0])
