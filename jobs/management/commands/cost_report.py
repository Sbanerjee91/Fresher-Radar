from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Sum

from jobs.models import SyncLog


class Command(BaseCommand):
    help = "What does LLM tagging cost? Uses the real cost and token counts stored by every sync."

    def handle(self, *args, **options):
        runs = SyncLog.objects.filter(tagged_llm__gt=0)
        t = runs.aggregate(posts=Sum("tagged_llm"), calls=Sum("llm_calls"), tin=Sum("tokens_in"), tout=Sum("tokens_out"), real=Sum("llm_cost_usd"))
        posts, tin, tout, real = t["posts"] or 0, t["tin"] or 0, t["tout"] or 0, t["real"] or 0
        if not posts:
            self.stderr.write("No LLM-tagged posts in the sync logs yet. Run `fetch_jobs` with OPENROUTER_API_KEY set.")
            return
        estimated = tin / 1e6 * settings.LLM_PRICE_IN + tout / 1e6 * settings.LLM_PRICE_OUT
        # A :free OpenRouter model is explicitly zero-priced. Do not mistake a genuine $0
        # usage.cost for missing telemetry and apply stale paid-model fallback prices.
        if real > 0:
            cost, basis = real, "billed by OpenRouter"
        elif str(settings.LLM_MODEL).endswith(":free"):
            cost, basis = 0.0, "zero-priced OpenRouter free model"
        else:
            cost, basis = estimated, "tokens x LLM_PRICE_IN/OUT"
        per_k = cost / posts * 1000
        self.stdout.write(
            f"Model: {settings.LLM_MODEL}\n"
            f"Posts tagged: {posts}   API calls: {t['calls']}   tokens: {tin:,} in / {tout:,} out\n"
            f"Tokens per post: {tin / posts:.0f} in / {tout / posts:.0f} out\n"
            f"Total cost: ${cost:.4f}  ({basis})\n"
            f"COST PER 1,000 POSTS: ${per_k:.4f}  (about Rs {per_k * 90:.2f} at Rs 90/USD)"
        )
