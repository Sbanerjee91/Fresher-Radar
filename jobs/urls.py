from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/jobs/", views.jobs_api, name="jobs_api"),
]
