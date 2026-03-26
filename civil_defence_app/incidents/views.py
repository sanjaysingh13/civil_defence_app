"""
Incidents app views.

IncidentListView — paginated, filterable table of all incidents.
IncidentDetailView — full detail card for a single incident.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from django.views.generic import ListView

from .models import Incident
from .models import IncidentStatus
from .models import IncidentType


class IncidentListView(LoginRequiredMixin, ListView):
    """
    Table of all incidents with filters for status, type, and unit.
    Ordered newest first (descending started_at).
    """
    model               = Incident
    template_name       = "incidents/incident_list.html"
    context_object_name = "incidents"
    paginate_by         = 50

    def get_queryset(self):
        qs = (
            Incident.objects
            .select_related("unit")
        )

        self.q         = self.request.GET.get("q", "").strip()
        self.status    = self.request.GET.get("status", "").strip()
        self.inc_type  = self.request.GET.get("type", "").strip()
        self.unit_id   = self.request.GET.get("unit", "").strip()

        if self.q:
            qs = qs.filter(title__icontains=self.q)
        if self.status:
            qs = qs.filter(status=self.status)
        if self.inc_type:
            qs = qs.filter(incident_type=self.inc_type)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)

        # Order newest first using start_time (the model's actual field name)
        return qs.order_by("-start_time", "-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"]               = self.q
        context["selected_status"] = self.status
        context["selected_type"]   = self.inc_type
        context["selected_unit"]   = self.unit_id
        context["status_choices"]  = IncidentStatus.choices
        context["type_choices"]    = IncidentType.choices
        from civil_defence_app.personnel.models import Unit
        context["units"] = Unit.objects.order_by("name")
        return context


class IncidentDetailView(LoginRequiredMixin, DetailView):
    model         = Incident
    template_name = "incidents/incident_detail.html"

    def get_queryset(self):
        return Incident.objects.select_related("unit", "reported_by")
