from django.db import migrations, models

INDIA_SOURCES = {"Adzuna India", "Jooble India"}


def backfill(apps, schema_editor):
    """Give every existing job a city + role, merge duplicates, retire non-India jobs."""
    from jobs.dedupe import dedupe_hash
    from jobs.places import parse_location
    from jobs.tagging import rules_role

    Job = apps.get_model("jobs", "Job")
    seen, drop, update = set(), [], []
    for job in Job.objects.order_by("first_seen", "id"):  # oldest first: it is the one we keep
        city, in_india = parse_location(job.location, job.source in INDIA_SOURCES)
        job.city, job.role = city, rules_role(job.title)
        job.job_hash = dedupe_hash(job.company, job.title, city)
        if job.job_hash in seen:
            drop.append(job.id)
            continue
        seen.add(job.job_hash)
        if not in_india:
            job.is_active = False
        update.append(job)
    Job.objects.filter(id__in=drop).delete()
    Job.objects.bulk_update(update, ["city", "role", "job_hash", "is_active"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("jobs", "0002_sync_tracking")]

    operations = [
        migrations.AddField("job", "city", models.CharField(blank=True, db_index=True, max_length=60)),
        migrations.AddField("job", "role", models.CharField(blank=True, db_index=True, max_length=40)),
        migrations.AddField(
            "job", "tag_method",
            models.CharField(choices=[("rules", "Rules"), ("llm", "LLM")], default="rules", max_length=5),
        ),
        migrations.AddField("job", "tagged_at", models.DateTimeField(blank=True, null=True)),
        migrations.AlterField("job", "location", models.CharField(default="India", max_length=255)),
        migrations.AddField("synclog", "duplicates", models.PositiveIntegerField(default=0)),
        migrations.AddField("synclog", "tagged_llm", models.PositiveIntegerField(default=0)),
        migrations.AddField("synclog", "tagged_rules", models.PositiveIntegerField(default=0)),
        migrations.AddField("synclog", "llm_calls", models.PositiveIntegerField(default=0)),
        migrations.AddField("synclog", "tokens_in", models.PositiveIntegerField(default=0)),
        migrations.AddField("synclog", "tokens_out", models.PositiveIntegerField(default=0)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
