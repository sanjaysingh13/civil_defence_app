"""
Incidents app URL configuration.
Mounted under "incident/" prefix with namespace "incidents".

URL patterns:
  /incident/                    → incident-list   — paginated table of all incidents
  /incident/dispatch/           → incident-dispatch — log new incident + dispatch resources
  /incident/<pk>/               → incident-detail — full detail card for one incident
  /incident/<pk>/report/        → incident-report — file post-incident report + upload media
"""

from django.urls import path

from . import views

app_name = "incidents"

urlpatterns = [
    # ── List all incidents ────────────────────────────────────────────────────
    # GET /incident/
    path(
        "",
        views.IncidentListView.as_view(),
        name="incident-list",
    ),

    # ── Unit In-Charge: log new incident and dispatch resources ───────────────
    # GET  /incident/dispatch/ → blank dispatch form
    # POST /incident/dispatch/ → create incident + assignments + equipment + vehicles
    # Note: "dispatch/" is defined BEFORE "<int:pk>/" so Django's URL resolver
    # doesn't try to match the string "dispatch" as an integer pk.
    path(
        "dispatch/",
        views.IncidentDispatchView.as_view(),
        name="incident-dispatch",
    ),

    # ── Full detail of a single incident ─────────────────────────────────────
    # GET /incident/<pk>/
    path(
        "<int:pk>/",
        views.IncidentDetailView.as_view(),
        name="incident-detail",
    ),

    # ── Unit In-Charge: file post-incident report + attach media ──────────────
    # GET  /incident/<pk>/report/ → report form pre-filled with incident data
    # POST /incident/<pk>/report/ → save report text OR upload media files
    path(
        "<int:pk>/report/",
        views.IncidentReportView.as_view(),
        name="incident-report",
    ),
]
