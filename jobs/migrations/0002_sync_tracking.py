import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    """Keeps all existing jobs: `posted_at` is renamed, not recreated."""

    dependencies = [("jobs", "0001_initial")]

    operations = [
        migrations.RenameField("job", "posted_at", "first_seen"),
        migrations.AddField(
            "job",
            "last_seen",
            models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AlterField(
            "job",
            "location",
            models.CharField(default="India / Remote", max_length=255),
        ),
        migrations.AlterField(
            "job",
            "job_hash",
            models.CharField(editable=False, max_length=64, unique=True),
        ),
        migrations.AlterModelOptions("job", options={"ordering": ["-first_seen"]}),
        migrations.AddIndex(
            "job",
            models.Index(fields=["is_active", "-first_seen"], name="jobs_job_is_acti_34d2f4_idx"),
        ),
        migrations.CreateModel(
            name="SyncLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Running"),
                            ("success", "Success"),
                            ("partial", "Partial (some sources failed)"),
                            ("failed", "Failed"),
                        ],
                        default="running",
                        max_length=10,
                    ),
                ),
                ("added", models.PositiveIntegerField(default=0)),
                ("expired", models.PositiveIntegerField(default=0)),
                ("total_active", models.PositiveIntegerField(default=0)),
                ("errors", models.TextField(blank=True)),
            ],
            options={"ordering": ["-started_at"]},
        ),
    ]
