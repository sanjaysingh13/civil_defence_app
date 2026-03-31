"""
Training app views.

TrainingListView               — catalogue of Training programmes (scoped for UIC).
TrainingProgrammeCreateView  — Admin: new programme from the website.
TrainingDetailView             — one programme.
TrainingInstanceListView       — batches (scoped for UIC to own unit).
TrainingInstanceCreateView     — Admin or UIC: new batch + attendance from the website.
TrainingInstanceDetailView     — one batch.
VolunteerSearchView            — JSON for volunteer autocomplete (Admin or UIC).
TrainingCoverageSummaryView    — all units: volunteer + attendance coverage totals.
TrainingUnitSummaryView        — one unit: attendance counts per programme.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.db.models import Count
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView
from django.views.generic import FormView
from django.views.generic import ListView
from django.views.generic import TemplateView
from django.views.generic.edit import CreateView

from civil_defence_app.personnel.models import Volunteer

from .forms import TrainingInstanceWithVolunteersForm
from .forms import TrainingProgrammeForm
from .models import Training
from .models import TrainingAttendance
from .models import TrainingInstance
from .models import TrainingType


def _is_admin(user) -> bool:
    return bool(user.is_superuser or getattr(user, "is_admin_role", False))


def _can_manage_training_instances(user) -> bool:
    """Admin/superuser or Unit In-Charge with an assigned unit."""
    if user.is_superuser or getattr(user, "is_admin_role", False):
        return True
    return bool(
        getattr(user, "is_unit_in_charge", False) and user.unit_id is not None
    )


class TrainingListView(LoginRequiredMixin, ListView):
    """
    Table of Training programmes. Admins see global batch counts; UICs see counts
    only for batches organised by their unit.
    """

    model = Training
    template_name = "training/training_list.html"
    context_object_name = "trainings"

    def get_queryset(self):
        user = self.request.user
        base = Training.objects.all()
        if _is_admin(user):
            return (
                base.annotate(instance_count=Count("instances")).order_by("name")
            )
        if getattr(user, "is_unit_in_charge", False) and user.unit_id:
            return (
                base.annotate(
                    instance_count=Count(
                        "instances",
                        filter=Q(instances__unit_id=user.unit_id),
                    ),
                ).order_by("name")
            )
        return base.annotate(instance_count=Count("instances")).order_by("name")


class TrainingProgrammeCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    """Admin-only: define a new Training programme without using Django Admin."""

    model = Training
    form_class = TrainingProgrammeForm
    template_name = "training/training_programme_form.html"

    def test_func(self) -> bool:
        return _is_admin(self.request.user)

    def get_success_url(self):
        return reverse_lazy("training:training-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Training programme created.")
        return super().form_valid(form)


class TrainingDetailView(LoginRequiredMixin, DetailView):
    model = Training
    template_name = "training/training_detail.html"

    def get_queryset(self):
        return Training.objects.prefetch_related("instances__unit")


class TrainingInstanceListView(LoginRequiredMixin, ListView):
    """
    Paginated table of training batches. UICs only see batches for their unit;
    Admins see all batches (optional filters).
    """

    model = TrainingInstance
    template_name = "training/instance_list.html"
    context_object_name = "instances"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            TrainingInstance.objects.select_related("training", "unit")
            .annotate(attendance_n=Count("attendances"))
            .order_by("-start_date")
        )

        user = self.request.user
        if not _is_admin(user) and getattr(user, "is_unit_in_charge", False) and user.unit_id:
            qs = qs.filter(unit_id=user.unit_id)

        self.training_id = self.request.GET.get("training", "").strip()
        self.unit_id = self.request.GET.get("unit", "").strip()

        if self.training_id:
            qs = qs.filter(training_id=self.training_id)
        if self.unit_id and _is_admin(user):
            qs = qs.filter(unit_id=self.unit_id)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["trainings"] = Training.objects.order_by("name")
        context["selected_training"] = self.training_id
        context["selected_unit"] = self.unit_id
        from civil_defence_app.personnel.models import Unit

        context["units"] = Unit.objects.order_by("name")
        context["is_admin"] = _is_admin(self.request.user)
        context["scope_unit_only"] = (
            not _is_admin(self.request.user)
            and getattr(self.request.user, "is_unit_in_charge", False)
            and self.request.user.unit_id
        )
        return context


class TrainingInstanceCreateView(LoginRequiredMixin, UserPassesTestMixin, FormView):
    """Create a batch and enrol volunteers (autocomplete + chips in template)."""

    form_class = TrainingInstanceWithVolunteersForm
    template_name = "training/training_instance_form.html"

    def test_func(self) -> bool:
        return _can_manage_training_instances(self.request.user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            instance = form.save_instance()
            volunteers = form.cleaned_data["volunteers"]
            TrainingAttendance.objects.bulk_create(
                [
                    TrainingAttendance(
                        volunteer=v,
                        training_instance=instance,
                        enrolled_by=self.request.user,
                    )
                    for v in volunteers
                ],
            )
        messages.success(
            self.request,
            f"Training batch created with {len(volunteers)} volunteer(s) enrolled.",
        )
        return redirect("training:instance-detail", pk=instance.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_admin"] = _is_admin(self.request.user)
        return context


class VolunteerSearchView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    JSON helper for jQuery UI Autocomplete: { "results": [ { "id", "label" }, ... ] }.
    Admins search all active volunteers; UICs only their unit.
    """

    def test_func(self) -> bool:
        return _can_manage_training_instances(self.request.user)

    def handle_no_permission(self):
        # Anonymous users must hit LoginRequiredMixin behaviour (redirect to login),
        # not return JSON — otherwise our JSON body overrides the redirect chain.
        if not self.request.user.is_authenticated:
            return LoginRequiredMixin.handle_no_permission(self)
        return JsonResponse({"results": [], "detail": "forbidden"}, status=403)

    def get(self, request, *args, **kwargs):
        q = request.GET.get("q", "").strip()
        if len(q) < 1:
            return JsonResponse({"results": []})

        user = request.user
        qs = Volunteer.objects.filter(is_active=True).order_by("name")
        if not _is_admin(user):
            qs = qs.filter(unit_id=user.unit_id)

        qs = qs.filter(name__icontains=q)[:40]
        results = [{"id": v.pk, "label": str(v)} for v in qs]
        return JsonResponse({"results": results})


class TrainingInstanceDetailView(LoginRequiredMixin, DetailView):
    model = TrainingInstance
    template_name = "training/instance_detail.html"

    def get_queryset(self):
        return (
            TrainingInstance.objects.select_related("training", "unit")
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
        user = request.user
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
        context["grand_basic"] = sum(u.volunteers_with_basic for u in units)
        context["grand_special"] = sum(u.volunteers_with_special for u in units)
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
