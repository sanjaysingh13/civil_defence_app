"""
Training app URL configuration.
Mounted under "training/" prefix with namespace "training".

Order note: static path segments ("coverage/", "programme/add/", "instances/add/",
"api/…", "instances/", "unit/…") must appear before "<int:pk>/" so they are not
captured as integer primary keys.
"""

from django.urls import path

from . import views

app_name = "training"

urlpatterns = [
    path("", views.TrainingListView.as_view(), name="training-list"),

    path(
        "programme/add/",
        views.TrainingProgrammeCreateView.as_view(),
        name="training-programme-create",
    ),

    path(
        "instances/add/",
        views.TrainingInstanceCreateView.as_view(),
        name="training-instance-create",
    ),

    path(
        "api/volunteers/search/",
        views.VolunteerSearchView.as_view(),
        name="volunteer-search",
    ),

    path(
        "coverage/",
        views.TrainingCoverageSummaryView.as_view(),
        name="training-coverage-summary",
    ),
    path(
        "unit/<int:unit_pk>/summary/",
        views.TrainingUnitSummaryView.as_view(),
        name="training-unit-summary",
    ),

    path("<int:pk>/", views.TrainingDetailView.as_view(), name="training-detail"),

    path("instances/", views.TrainingInstanceListView.as_view(), name="instance-list"),
    path(
        "instances/<int:pk>/",
        views.TrainingInstanceDetailView.as_view(),
        name="instance-detail",
    ),
]
