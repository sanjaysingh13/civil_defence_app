"""
Personnel app URL configuration.

All URLs defined here are mounted under the "personnel/" prefix in
config/urls.py and share the namespace "personnel".

Namespace means you refer to these URLs in templates and reverse() calls as
  "personnel:unit-list"   instead of just   "unit-list"
which avoids name clashes across apps.

List and detail views are implemented; monthly office-duty CSV routes are under office-duty/.
"""

from django.urls import path

from . import views

# app_name is required for namespaced URLs.
# It must match the namespace= kwarg used in config/urls.py.
app_name = "personnel"

urlpatterns = [
    # ── Units ────────────────────────────────────────────────────────────────
    # GET /personnel/units/            → list all units
    path("units/", views.UnitListView.as_view(), name="unit-list"),
    # GET /personnel/units/<pk>/       → detail of one unit with its volunteers
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit-detail"),
    # ── Volunteers ────────────────────────────────────────────────────────────
    # GET /personnel/volunteers/       → paginated list with search/filter
    path("volunteers/", views.VolunteerListView.as_view(), name="volunteer-list"),
    # GET /personnel/volunteers/<pk>/  → detail of one volunteer
    path(
        "volunteers/<int:pk>/",
        views.VolunteerDetailView.as_view(),
        name="volunteer-detail",
    ),
    path(
        "volunteers/<int:pk>/deroster/",
        views.VolunteerDeRosterView.as_view(),
        name="volunteer-deroster",
    ),
    path(
        "volunteers/<int:pk>/reinstate/",
        views.VolunteerReinstateView.as_view(),
        name="volunteer-reinstate",
    ),
    # Monthly office duty CSV (Admin + UIC with unit)
    path(
        "office-duty/",
        views.OfficeDutyMonthlyHubView.as_view(),
        name="office-duty-monthly",
    ),
    path(
        "office-duty/template/",
        views.OfficeDutyMonthlyTemplateDownloadView.as_view(),
        name="office-duty-template-download",
    ),
    path(
        "office-duty/upload/",
        views.OfficeDutyMonthlyUploadView.as_view(),
        name="office-duty-upload",
    ),
    path(
        "office-duty/status/",
        views.OfficeDutyMonthlyStatusView.as_view(),
        name="office-duty-status",
    ),
    path(
        "office-duty/email-uic/",
        views.OfficeDutyEmailTemplateToUICView.as_view(),
        name="office-duty-email-uic",
    ),
]
