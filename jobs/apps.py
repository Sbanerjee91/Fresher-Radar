import os
import sys

from django.apps import AppConfig
from django.conf import settings


class JobsConfig(AppConfig):
    name = "jobs"

    def ready(self):
        if settings.AUTO_SYNC and self._serving():
            from . import scheduler

            scheduler.start()

    @staticmethod
    def _serving():
        """Only inside the real `runserver` process (not migrate, shell, tests...).

        With the auto-reloader Django runs two processes; RUN_MAIN marks the one
        that serves requests. For gunicorn/waitress set AUTO_SYNC_FORCE=1 on a
        single worker, or use cron with `manage.py fetch_jobs`.
        """
        if os.environ.get("AUTO_SYNC_FORCE") == "1":
            return True
        return "runserver" in sys.argv and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv)
