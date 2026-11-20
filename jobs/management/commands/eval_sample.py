import csv
import random

from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.tagging import rules_role
from jobs.places import parse_location


class Command(BaseCommand):
    help = ("Draw a random sample for hand-checking. Writes TWO files: a sheet with the tags hidden (so your own "
            "judgement is not anchored by the AI's answer) and a key with the AI + rule tags for scoring.")

    def add_arguments(self, parser):
        parser.add_argument("--n", type=int, default=50)
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument("--sheet", default="eval_sheet.csv")
        parser.add_argument("--key", default="eval_key.csv")

    def handle(self, *args, n=50, seed=2026, sheet="eval_sheet.csv", key="eval_key.csv", **options):
        ids = sorted(Job.objects.filter(is_active=True, tag_method="llm").values_list("id", flat=True))
        if len(ids) < n:
            self.stderr.write(f"Only {len(ids)} LLM-tagged jobs. Run a sync with OPENROUTER_API_KEY set first.")
            return
        chosen = Job.objects.filter(id__in=random.Random(seed).sample(ids, n)).order_by("id")
        with open(sheet, "w", newline="", encoding="utf-8-sig") as fs, open(key, "w", newline="", encoding="utf-8-sig") as fk:
            ws, wk = csv.writer(fs), csv.writer(fk)
            ws.writerow(["id", "title", "company", "location", "apply_url", "human_role", "human_city"])
            wk.writerow(["id", "llm_role", "llm_city", "rules_role", "rules_city"])
            for j in chosen:
                ws.writerow([j.id, j.title, j.company, j.location, j.apply_url, "", ""])
                wk.writerow([j.id, j.role, j.city, rules_role(j.title),
                             parse_location(j.location, j.source.endswith("India"))[0]])
        self.stdout.write(f"Fill human_role and human_city in {sheet} yourself (roles must match the list in "
                          f"jobs/tagging.py), then run: python manage.py eval_score --sheet {sheet} --key {key}")
