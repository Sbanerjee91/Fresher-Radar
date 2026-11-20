from django.db import models
from django.utils import timezone

from . import dedupe


class Job(models.Model):
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255, default="India")
    city = models.CharField(max_length=60, blank=True, db_index=True)
    role = models.CharField(max_length=40, blank=True, db_index=True)
    tag_method = models.CharField(max_length=5, choices=[("rules", "Rules"), ("llm", "LLM")], default="rules")
    tagged_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=100)
    apply_url = models.URLField(max_length=500)
    job_hash = models.CharField(max_length=64, unique=True, editable=False)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-first_seen"]
        indexes = [models.Index(fields=["is_active", "-first_seen"])]

    @staticmethod
    def make_hash(company, title, city):
        """Same company + same role + same city = one row, however it is spelled."""
        return dedupe.dedupe_hash(company, title, city)

    def save(self, *args, **kwargs):
        if not self.job_hash:
            self.job_hash = self.make_hash(self.company, self.title, self.city)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} at {self.company}"


class SyncLog(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running"
        SUCCESS = "success"
        PARTIAL = "partial", "Partial (some sources failed)"
        FAILED = "failed"

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status, default=Status.RUNNING)
    added = models.PositiveIntegerField(default=0)
    expired = models.PositiveIntegerField(default=0)
    total_active = models.PositiveIntegerField(default=0)
    duplicates = models.PositiveIntegerField(default=0)
    tagged_llm = models.PositiveIntegerField(default=0)
    tagged_rules = models.PositiveIntegerField(default=0)
    llm_calls = models.PositiveIntegerField(default=0)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    llm_cost_usd = models.FloatField(default=0)  # real cost reported by OpenRouter
    errors = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.started_at:%Y-%m-%d %H:%M} - {self.status}"
