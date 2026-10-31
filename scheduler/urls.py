from django.urls import path
from . import views

app_name = "scheduler"

urlpatterns = [
    path(
        "timetable/",
        views.published_timetable,
        name="published_timetable",
    ),
    path(
        "proposals/",
        views.proposal_dashboard,
        name="proposal_dashboard",
    ),
    path(
    "proposals/generate/",
    views.generate_proposal_view,
    name="generate_proposal",
    ),
    path(
    "proposals/<int:proposal_id>/",
    views.proposal_detail,
    name="proposal_detail",
    ),
]