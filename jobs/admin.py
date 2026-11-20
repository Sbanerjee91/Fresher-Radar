from django.contrib import admin

from .models import Job, SyncLog


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "location", "source", "is_active", "first_seen")
    list_filter = ("source", "is_active")
    search_fields = ("title", "company", "location")
    date_hierarchy = "first_seen"


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ("started_at", "status", "added", "expired", "total_active")
    readonly_fields = [f.name for f in SyncLog._meta.fields]

    def has_add_permission(self, request):
        return False
