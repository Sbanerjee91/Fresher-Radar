import csv
import math

from django.core.management.base import BaseCommand

from jobs.tagging import ROLES


def wilson(correct, n, z=1.96):
    """95% confidence interval for an accuracy measured on n samples."""
    if not n:
        return 0.0, 0.0
    p = correct / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


class Command(BaseCommand):
    help = "Score the AI tags (and the rule-based baseline) against your hand-checked labels."

    def add_arguments(self, parser):
        parser.add_argument("--sheet", default="eval_sheet.csv")
        parser.add_argument("--key", default="eval_key.csv")

    def handle(self, *args, sheet="eval_sheet.csv", key="eval_key.csv", **options):
        norm = lambda v: (v or "").strip().lower()
        with open(key, encoding="utf-8-sig") as f:
            keys = {int(r["id"]): r for r in csv.DictReader(f)}
        with open(sheet, encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if norm(r["human_role"]) and norm(r["human_city"])]
        if not rows:
            self.stderr.write("No fully labelled rows found. Fill human_role and human_city first.")
            return
        valid = {r.lower() for r in ROLES}
        for r in rows:
            if norm(r["human_role"]) not in valid:
                self.stderr.write(f"  warning: id {r['id']} has a role that is not in the taxonomy: {r['human_role']!r}")

        n = len(rows)
        self.stdout.write(f"\nHand-checked posts: {n}\n")
        for field, llm_col, rules_col in (("role", "llm_role", "rules_role"), ("city", "llm_city", "rules_city")):
            for label, col in (("AI (LLM)", llm_col), ("Rules baseline", rules_col)):
                right = sum(norm(r[f"human_{field}"]) == norm(keys[int(r["id"])][col]) for r in rows)
                lo, hi = wilson(right, n)
                self.stdout.write(f"{field:5} {label:15} {right}/{n} = {right / n:6.1%}   (95% CI {lo:.0%} to {hi:.0%})")
        self.stdout.write("\nWhere the AI disagreed with you:")
        for r in rows:
            k = keys[int(r["id"])]
            for field in ("role", "city"):
                if norm(r[f"human_{field}"]) != norm(k[f"llm_{field}"]):
                    self.stdout.write(f"  id {r['id']:>5} {field}: you={r[f'human_{field}']!r} ai={k[f'llm_{field}']!r}  | {r['title'][:55]} | {r['location'][:30]}")
