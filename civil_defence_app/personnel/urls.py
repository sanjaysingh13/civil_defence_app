"""
Personnel app URL configuration.

All URLs defined here are mounted under the "personnel/" prefix in
config/urls.py and share the namespace "personnel".

Namespace means you refer to these URLs in templates and reverse() calls as
  "personnel:unit-list"   instead of just   "unit-list"
which avoids name clashes across apps.

List and detail views are implemented; office-duty logging uses POST-only routes below.
"""

from django.urls import path

from . import views

# app_name is required for namespaced URLs.
# It must match the namespace= kwarg used in config/urls.py.
app_name = "personnel"

urlpatterns = [
    # ── Units ────────────────────────────────────────────────────────────────
    # GET /personnel/units/            → list all units
    path("units/",         views.UnitListView.as_view(),   name="unit-list"),
    # GET /personnel/units/<pk>/       → detail of one unit with its volunteers
    path("units/<int:pk>/", views.UnitDetailView.as_view(), name="unit-detail"),

    # ── Volunteers ────────────────────────────────────────────────────────────
    # GET /personnel/volunteers/       → paginated list with search/filter
    path("volunteers/",          views.VolunteerListView.as_view(),   name="volunteer-list"),
    # GET /personnel/volunteers/<pk>/  → detail of one volunteer
    path("volunteers/<int:pk>/",  views.VolunteerDetailView.as_view(), name="volunteer-detail"),
    # POST — start / end office duty (Admin + owning UIC only; see views)
    path(
        "volunteers/<int:pk>/office-duty/start/",
        views.VolunteerOfficeDutyStartView.as_view(),
        name="volunteer-office-duty-start",
    ),
    path(
        "volunteers/<int:pk>/office-duty/end/",
        views.VolunteerOfficeDutyEndView.as_view(),
        name="volunteer-office-duty-end",
    ),
]
