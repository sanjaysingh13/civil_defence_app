"""
Training app views.

TrainingListView               — catalogue of Training programmes.
TrainingDetailView             — one programme (stub template).
TrainingInstanceListView       — all batches / instances, filterable.
TrainingInstanceDetailView     — one batch (stub template).
TrainingCoverageSummaryView    — all units: volunteer + attendance coverage totals.
TrainingUnitSummaryView        — one unit: attendance counts per programme.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from .models import Training
from .models import TrainingInstance
from .models import TrainingType


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
            .annotate(instance_count=Count("instances"))
            .order_by("name")
        )


class TrainingDetailView(LoginRequiredMixin, DetailView):
    model         = Training
    template_name = "training/training_detail.html"

    def get_queryset(self):
        return Training.objects.prefetch_related("instances__unit")


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
        from civil_defence_app.personnel.models import Unit
        context["units"] = Unit.objects.order_by("name")
        return context


class TrainingInstanceDetailView(LoginRequiredMixin, DetailView):
    model         = TrainingInstance
    template_name = "training/instance_detail.html"

    def get_queryset(self):
        return (
            TrainingInstance.objects
            .select_related("training", "unit")
            .prefetch_related("attendances__volunteer")
        )


# ─────────────────────────────────────────────────────────────────────────────
# COVERAGE SUMMARY — ALL UNITS (Admin landing) / UIC redirect to own unit
# ─────────────────────────────────────────────────────────────────────────────

class TrainingCoverageSummaryView(LoginRequiredMixin, TemplateView):
    """
    One table: every district unit with volunteer counts and how many
    volunteers have structured TrainingAttendance rows (from seed/import).

    Admins see the full state.  UICs are redirected to TrainingUnitSummaryView
    for their own unit only — a single-row state-wide table is not useful.
    """

    template_name = "training/coverage_summary.html"

    def get(self, request, *args, **kwargs):
        user     = request.user
        is_admin = user.is_superuser or getattr(user, "is_admin_role", False)
        if not is_admin and getattr(user, "is_unit_in_charge", False) and user.unit_id:
            return redirect("training:training-unit-summary", unit_pk=user.unit_id)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from civil_defence_app.personnel.models import Unit

        units = (
            Unit.objects.annotate(
                volunteer_active=Count(
                    "volunteers",
                    filter=Q(volunteers__is_active=True),
                ),
                volunteers_with_basic=Count(
                    "volunteers",
                    filter=Q(
                        volunteers__training_attendances__training_instance__training__training_type=(
                            TrainingType.BASIC
                        ),
                    ),
                    distinct=True,
                ),
                volunteers_with_special=Count(
                    "volunteers",
                    filter=Q(
                        volunteers__training_attendances__training_instance__training__training_type__in=[
                            TrainingType.ADVANCED,
                            TrainingType.SPECIALIZED,
                            TrainingType.REFRESHER,
                        ],
                    ),
                    distinct=True,
                ),
                attendance_links=Count("volunteers__training_attendances"),
            )
            .order_by("name")
        )

        context["units"] = units
        context["grand_volunteers"] = sum(u.volunteer_active for u in units)
        context["grand_basic"]      = sum(u.volunteers_with_basic for u in units)
        context["grand_special"]    = sum(u.volunteers_with_special for u in units)
        context["grand_attendance"] = sum(u.attendance_links for u in units)

        context["all_units"] = Unit.objects.order_by("name")

        return context


# ─────────────────────────────────────────────────────────────────────────────
# UNIT SUMMARY — per-programme attendance counts for one district
# ─────────────────────────────────────────────────────────────────────────────

class TrainingUnitSummaryView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """
    Drill-down: for one Unit, show each Training programme that has at least
    one TrainingAttendance from a volunteer in this unit, with counts.

    Access: Admin (any unit) or UIC (own unit only).
    """

    template_name = "training/unit_training_summary.html"

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        from civil_defence_app.personnel.models import Unit
        self.unit = get_object_or_404(Unit, pk=kwargs["unit_pk"])

    def test_func(self) -> bool:
        user = self.request.user
        if user.is_superuser or getattr(user, "is_admin_role", False):
            return True
        return (
            getattr(user, "is_unit_in_charge", False)
            and user.unit_id == self.unit.pk
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unit"] = self.unit

        from civil_defence_app.personnel.models import Unit
        context["all_units"] = Unit.objects.order_by("name")

        programmes = (
            Training.objects.annotate(
                attendance_count=Count(
                    "instances__attendances",
                    filter=Q(instances__attendances__volunteer__unit_id=self.unit.pk),
                ),
            )
            .filter(attendance_count__gt=0)
            .order_by("training_type", "name")
        )
        context["programmes"] = programmes

        from civil_defence_app.personnel.models import Volunteer
        context["volunteer_active_count"] = Volunteer.objects.filter(
            unit=self.unit,
            is_active=True,
        ).count()

        return context
