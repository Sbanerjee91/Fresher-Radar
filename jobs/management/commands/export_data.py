import csv

from django.core.management.base import BaseCommand

from jobs.models import Job


class Command(BaseCommand):
    help = "Export every active job to CSV (import it into Google Sheets for the submission)."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="jobs_dataset.csv")

    def handle(self, *args, out="jobs_dataset.csv", **options):
        cols = ["id", "title", "company", "city", "role", "tag_method", "source", "location", "apply_url", "first_seen"]
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            for j in Job.objects.filter(is_active=True).order_by("-first_seen"):
                writer.writerow([getattr(j, c) if c != "first_seen" else j.first_seen.date() for c in cols])
        self.stdout.write(f"Wrote {Job.objects.filter(is_active=True).count()} jobs to {out}")
