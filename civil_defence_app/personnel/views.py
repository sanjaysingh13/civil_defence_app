"""
Personnel app views.

We use Django's generic class-based views (ListView, DetailView) instead of
writing the list/detail logic from scratch.  These base classes provide:
  - ListView  : fetches a queryset, paginates it, passes it to a template
  - DetailView: fetches a single object by pk, passes it to a template

LoginRequiredMixin redirects anonymous visitors to the login page before
allowing access to any view that inherits from it.

get_queryset() lets us customise which rows are returned (e.g. apply search
filters from GET parameters).

get_context_data() lets us pass extra variables to the template on top of
the default ones (the paginated list / single object).
"""

from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView

from .forms import OfficeDutyStartForm
from .models import OfficeDutyPeriod
from .models import Unit
from .models import Volunteer
from .service_log import build_service_log_rows
from .service_log import build_year_summary


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY PERMISSIONS
# ─────────────────────────────────────────────────────────────────────────────


def user_can_log_office_duty(user, volunteer: Volunteer) -> bool:
    """
    Only Admin (role or superuser) and the owning Unit In-Charge may start or
    end office duty for a volunteer in their unit.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or getattr(user, "is_admin_role", False):
        return True
    if getattr(user, "is_unit_in_charge", False) and user.unit_id == volunteer.unit_id:
        return True
    return False


class OfficeDutyPermissionMixin(UserPassesTestMixin):
    """
    Loads the volunteer from the URL and gates POST handlers on
    user_can_log_office_duty.  Anonymous users are sent to login by
    LoginRequiredMixin on the same view.
    """

    volunteer: Volunteer

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.volunteer = get_object_or_404(
            Volunteer.objects.select_related("unit"),
            pk=kwargs["pk"],
        )

    def test_func(self) -> bool:
        return user_can_log_office_duty(self.request.user, self.volunteer)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(
                self.request,
                "You do not have permission to log office duty for this volunteer.",
            )
            return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)
        return super().handle_no_permission()


# ─────────────────────────────────────────────────────────────────────────────
# UNIT VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class UnitListView(LoginRequiredMixin, ListView):
    """
    Displays all 23 Civil Defence units as a sortable table.
    Annotates each unit with its active volunteer count so we can show it
    in the table without an extra query per row.
    """
    model               = Unit
    template_name       = "personnel/unit_list.html"
    context_object_name = "units"

    def get_queryset(self):
        # annotate() adds a computed field (volunteer_count) to each object.
        # Count('volunteers') counts rows in the related Volunteer table for
        # each Unit.  filter(volunteers__is_active=True) restricts the count
        # to active volunteers only.
        return (
            Unit.objects
            .annotate(volunteer_count=Count("volunteers", filter=Q(volunteers__is_active=True)))
            .order_by("name")
        )


class UnitDetailView(LoginRequiredMixin, DetailView):
    """
    Detail page for a single Unit: shows metadata plus a paginated
    table of its volunteers.
    """
    model         = Unit
    template_name = "personnel/unit_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass the unit's active volunteers to the template.
        context["volunteers"] = (
            self.object.volunteers
            .filter(is_active=True)
            .order_by("serial_no")
        )
        return context


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER VIEWS
# ─────────────────────────────────────────────────────────────────────────────

class VolunteerListView(LoginRequiredMixin, ListView):
    """
    Paginated, searchable, filterable table of all volunteers.

    Supported GET parameters:
      ?q=<name>      — case-insensitive name search
      ?unit=<id>     — filter to a specific unit
      ?gender=<M|F>  — filter by gender
    """
    model               = Volunteer
    template_name       = "personnel/volunteer_list.html"
    context_object_name = "volunteers"
    paginate_by         = 50       # 50 rows per page keeps the page fast

    def get_queryset(self):
        qs = (
            Volunteer.objects
            .select_related("unit")   # joins Unit in a single SQL query
            .filter(is_active=True)
            .order_by("unit__name", "serial_no")
        )

        self.q       = self.request.GET.get("q", "").strip()
        self.unit_id = self.request.GET.get("unit", "").strip()
        self.gender  = self.request.GET.get("gender", "").strip()

        if self.q:
            qs = qs.filter(name__icontains=self.q)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)
        if self.gender:
            qs = qs.filter(gender=self.gender)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass filter state back so the template can pre-fill the form
        # and build correct pagination URLs that preserve the filters.
        context["q"]            = self.q
        context["selected_unit"]= self.unit_id
        context["selected_gender"] = self.gender
        context["units"]        = Unit.objects.order_by("name")
        context["total_count"]  = self.get_queryset().count()
        return context


class VolunteerDetailView(LoginRequiredMixin, DetailView):
    """
    Full detail card for a single Volunteer.

    Adds a combined service log: *incident* deployments (team operation via
    IncidentAssignment) plus *individual* office-duty periods.  Year-wise day
    summaries and office Start/End controls when the viewer may log office duty
    for this volunteer (Admin or owning UIC).
    """
    model         = Volunteer
    template_name = "personnel/volunteer_detail.html"

    def get_queryset(self):
        return (
            Volunteer.objects
            .select_related("unit")
            .prefetch_related(
                "training_attendances__training_instance__training",
                "incident_assignments__incident",
                "office_duty_periods",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vol = self.object
        rows = build_service_log_rows(vol)
        context["service_log_rows"] = rows
        context["service_year_summary"] = build_year_summary(rows)
        context["open_office_duty"] = (
            OfficeDutyPeriod.objects.filter(volunteer=vol, ended_at__isnull=True).first()
        )
        context["can_log_office_duty"] = user_can_log_office_duty(self.request.user, vol)
        context["office_duty_start_form"] = OfficeDutyStartForm()
        return context


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY LOGGING (POST endpoints)
# ─────────────────────────────────────────────────────────────────────────────


class VolunteerOfficeDutyStartView(LoginRequiredMixin, OfficeDutyPermissionMixin, View):
    """
    Start an office-duty period: one POST with a local calendar start date.

    Creates a row with started_at at the beginning of that day in the active
    timezone.  Fails if an open office-duty row already exists for this volunteer.
    """

    http_method_names = ["post"]

    def post(self, request, pk):
        form = OfficeDutyStartForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid start date.")
            return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)

        start_date = form.cleaned_data["start_date"]
        today = timezone.localdate()
        if start_date > today:
            messages.error(request, "Start date cannot be in the future.")
            return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)

        if OfficeDutyPeriod.objects.filter(volunteer=self.volunteer, ended_at__isnull=True).exists():
            messages.error(request, "This volunteer already has an open office duty period.")
            return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)

        tz = timezone.get_current_timezone()
        naive_start = datetime.combine(start_date, datetime.min.time())
        started_at = timezone.make_aware(naive_start, tz)

        OfficeDutyPeriod.objects.create(
            volunteer=self.volunteer,
            started_at=started_at,
            recorded_by=request.user if request.user.is_authenticated else None,
        )
        messages.success(request, "Office duty started.")
        return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)


class VolunteerOfficeDutyEndView(LoginRequiredMixin, OfficeDutyPermissionMixin, View):
    """End the current open office-duty period (sets ended_at to now)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        open_period = (
            OfficeDutyPeriod.objects.filter(volunteer=self.volunteer, ended_at__isnull=True)
            .order_by("-started_at")
            .first()
        )
        if not open_period:
            messages.error(request, "There is no open office duty period to end.")
            return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)

        open_period.ended_at = timezone.now()
        open_period.save(update_fields=["ended_at", "updated_at"])
        messages.success(request, "Office duty ended.")
        return redirect("personnel:volunteer-detail", pk=self.volunteer.pk)
