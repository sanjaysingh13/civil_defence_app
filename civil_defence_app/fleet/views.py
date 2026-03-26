"""
Fleet app views.

VehicleListView   — paginated, filterable table of all vehicles.
VehicleDetailView — full detail card for a single vehicle.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from django.views.generic import ListView

from .models import Vehicle
from .models import VehicleStatus
from .models import VehicleType


class VehicleListView(LoginRequiredMixin, ListView):
    """Table of all vehicles with filters for type, status, and unit."""
    model               = Vehicle
    template_name       = "fleet/vehicle_list.html"
    context_object_name = "vehicles"
    paginate_by         = 50

    def get_queryset(self):
        qs = (
            Vehicle.objects
            .select_related("unit")
            .order_by("unit__name", "registration_no")
        )

        self.q          = self.request.GET.get("q", "").strip()
        self.vtype      = self.request.GET.get("type", "").strip()
        self.status     = self.request.GET.get("status", "").strip()
        self.unit_id    = self.request.GET.get("unit", "").strip()

        if self.q:
            qs = qs.filter(registration_no__icontains=self.q)
        if self.vtype:
            qs = qs.filter(vehicle_type=self.vtype)
        if self.status:
            qs = qs.filter(status=self.status)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"]               = self.q
        context["selected_type"]   = self.vtype
        context["selected_status"] = self.status
        context["selected_unit"]   = self.unit_id
        context["type_choices"]    = VehicleType.choices
        context["status_choices"]  = VehicleStatus.choices
        from civil_defence_app.personnel.models import Unit
        context["units"] = Unit.objects.order_by("name")
        return context


class VehicleDetailView(LoginRequiredMixin, DetailView):
    model         = Vehicle
    template_name = "fleet/vehicle_detail.html"

    def get_queryset(self):
        return Vehicle.objects.select_related("unit")
