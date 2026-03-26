"""
Equipment app URL configuration.
Mounted under "equipment/" prefix with namespace "equipment".
"""

from django.urls import path

from . import views

app_name = "equipment"

urlpatterns = [
    # GET /equipment/                   → list all equipment items
    path("",              views.EquipmentListView.as_view(),   name="equipment-list"),
    # GET /equipment/<pk>/              → detail with maintenance log
    path("<int:pk>/",     views.EquipmentDetailView.as_view(), name="equipment-detail"),
]
