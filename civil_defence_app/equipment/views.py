"""
Equipment app views.

EquipmentListView  — paginated, filterable table of all equipment items.
EquipmentDetailView— full detail card for a single equipment item.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from django.views.generic import ListView

from .models import Equipment
from .models import EquipmentCategory
from .models import EquipmentStatus


class EquipmentListView(LoginRequiredMixin, ListView):
    """Table of all equipment across all units with filters."""
    model               = Equipment
    template_name       = "equipment/equipment_list.html"
    context_object_name = "equipment_list"
    paginate_by         = 50

    def get_queryset(self):
        qs = (
            Equipment.objects
            .select_related("unit")
            .order_by("unit__name", "name")
        )

        self.q          = self.request.GET.get("q", "").strip()
        self.category   = self.request.GET.get("category", "").strip()
        self.status     = self.request.GET.get("status", "").strip()
        self.unit_id    = self.request.GET.get("unit", "").strip()

        if self.q:
            qs = qs.filter(name__icontains=self.q)
        if self.category:
            qs = qs.filter(category=self.category)
        if self.status:
            qs = qs.filter(status=self.status)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"]                  = self.q
        context["selected_category"]  = self.category
        context["selected_status"]    = self.status
        context["selected_unit"]      = self.unit_id
        context["category_choices"]   = EquipmentCategory.choices
        context["status_choices"]     = EquipmentStatus.choices
        from civil_defence_app.personnel.models import Unit
        context["units"] = Unit.objects.order_by("name")
        return context


class EquipmentDetailView(LoginRequiredMixin, DetailView):
    model         = Equipment
    template_name = "equipment/equipment_detail.html"

    def get_queryset(self):
        return Equipment.objects.select_related("unit")
