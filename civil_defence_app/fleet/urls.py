"""
Fleet app URL configuration.
Mounted under "fleet/" prefix with namespace "fleet".
"""

from django.urls import path

from . import views

app_name = "fleet"

urlpatterns = [
    # GET /fleet/                       → list all vehicles
    path("",              views.VehicleListView.as_view(),   name="vehicle-list"),
    # GET /fleet/<pk>/                  → detail with maintenance log
    path("<int:pk>/",     views.VehicleDetailView.as_view(), name="vehicle-detail"),
]
