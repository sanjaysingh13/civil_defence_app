"""
Training app URL configuration.
Mounted under "training/" prefix with namespace "training".
"""

from django.urls import path

from . import views

app_name = "training"

urlpatterns = [
    # GET /training/                        → list all training programmes
    path("",                           views.TrainingListView.as_view(),         name="training-list"),
    # GET /training/<pk>/                   → detail of one programme + its batches
    path("<int:pk>/",                  views.TrainingDetailView.as_view(),        name="training-detail"),

    # GET /training/instances/              → list all training instances / batches
    path("instances/",                 views.TrainingInstanceListView.as_view(),  name="instance-list"),
    # GET /training/instances/<pk>/         → detail of one batch + attendance roll
    path("instances/<int:pk>/",        views.TrainingInstanceDetailView.as_view(),name="instance-detail"),
]
