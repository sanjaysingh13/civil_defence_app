"""
Incidents app URL configuration.
Mounted under "incident/" prefix with namespace "incidents".
"""

from django.urls import path

from . import views

app_name = "incidents"

urlpatterns = [
    # GET /incident/                    → list all incidents
    path("",              views.IncidentListView.as_view(),   name="incident-list"),
    # GET /incident/<pk>/               → detail of one incident (with log + assignments)
    path("<int:pk>/",     views.IncidentDetailView.as_view(), name="incident-detail"),
]
