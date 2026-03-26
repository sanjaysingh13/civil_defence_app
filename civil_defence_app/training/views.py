"""
Training app views.

Two list views:
  TrainingListView        — paginated table of all Training programmes
  TrainingInstanceListView— paginated table of all TrainingInstances (batches)

Two stub detail views for future expansion.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.views.generic import DetailView
from django.views.generic import ListView

from .models import Training
from .models import TrainingInstance


class TrainingListView(LoginRequiredMixin, ListView):
    """
    Table of all defined Training programmes (the "syllabus" catalogue).
    Shows name, type, and how many batches (instances) have been run.
    """
    model               = Training
    template_name       = "training/training_list.html"
    context_object_name = "trainings"

    def get_queryset(self):
        return (
            Training.objects
            # annotate each Training row with a count of its linked TrainingInstances
            .annotate(instance_count=Count("instances"))
            .order_by("name")
        )


class TrainingDetailView(LoginRequiredMixin, DetailView):
    model         = Training
    template_name = "training/training_detail.html"


class TrainingInstanceListView(LoginRequiredMixin, ListView):
    """
    Paginated table of all training batches (a specific run of a programme
    at a particular venue / date / unit).

    Supports filtering by training programme and unit.
    """
    model               = TrainingInstance
    template_name       = "training/instance_list.html"
    context_object_name = "instances"
    paginate_by         = 50

    def get_queryset(self):
        qs = (
            TrainingInstance.objects
            # select_related pre-fetches foreign key objects in one SQL JOIN,
            # avoiding N+1 queries when the template accesses instance.training.name
            .select_related("training", "unit")
            .order_by("-start_date")
        )

        self.training_id = self.request.GET.get("training", "").strip()
        self.unit_id     = self.request.GET.get("unit", "").strip()

        if self.training_id:
            qs = qs.filter(training_id=self.training_id)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["trainings"]          = Training.objects.order_by("name")
        context["selected_training"]  = self.training_id
        context["selected_unit"]      = self.unit_id
        # Import Unit here to avoid circular imports at module level
        from civil_defence_app.personnel.models import Unit
        context["units"] = Unit.objects.order_by("name")
        return context


class TrainingInstanceDetailView(LoginRequiredMixin, DetailView):
    model         = TrainingInstance
    template_name = "training/instance_detail.html"
