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

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.db.models import Count
from django.db.models import Q
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from civil_defence_app.users.models import UserRole

from .forms import OfficeDutyEmailUICForm
from .forms import OfficeDutyMonthlySelectorForm
from .forms import OfficeDutyMonthlyStatusFilterForm
from .forms import OfficeDutyMonthlyUploadForm
from .forms import VolunteerDeRosterForm
from .models import OfficeDutyMonthSubmission
from .models import Unit
from .models import Volunteer
from .office_duty_csv import apply_office_duty_csv_upload
from .office_duty_csv import build_office_duty_template_csv_bytes
from .service_log import build_service_log_rows
from .service_log import build_year_summary

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY PERMISSIONS
# ─────────────────────────────────────────────────────────────────────────────


def is_personnel_admin_user(user) -> bool:
    """State-level Admin role or Django superuser."""
    return bool(
        user.is_authenticated
        and (user.is_superuser or getattr(user, "is_admin_role", False)),
    )


def can_access_office_duty_monthly_hub(user) -> bool:
    """Admins or UICs with an assigned unit may use the CSV office-duty workflow."""
    if not user.is_authenticated:
        return False
    if is_personnel_admin_user(user):
        return True
    return bool(getattr(user, "is_unit_in_charge", False) and user.unit_id)


def can_deroster_volunteer(user, volunteer) -> bool:
    """
    De-rostering is limited to state Admins (or superuser) and to Unit
    In-Charge users for volunteers in their own unit — same boundary as other
    personnel actions (office duty CSV, etc.).
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or is_personnel_admin_user(user):
        return True
    return bool(
        getattr(user, "is_unit_in_charge", False)
        and user.unit_id
        and user.unit_id == volunteer.unit_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# UNIT VIEWS
# ─────────────────────────────────────────────────────────────────────────────


class UnitListView(LoginRequiredMixin, ListView):
    """
    Displays all 23 Civil Defence units as a sortable table.
    Annotates each unit with its active volunteer count so we can show it
    in the table without an extra query per row.
    """

    model = Unit
    template_name = "personnel/unit_list.html"
    context_object_name = "units"

    def get_queryset(self):
        # annotate() adds a computed field (volunteer_count) to each object.
        # Count('volunteers') counts rows in the related Volunteer table for
        # each Unit.  filter(volunteers__is_active=True) restricts the count
        # to active volunteers only.
        return Unit.objects.annotate(
            volunteer_count=Count("volunteers", filter=Q(volunteers__is_active=True))
        ).order_by("name")


class UnitDetailView(LoginRequiredMixin, DetailView):
    """
    Detail page for a single Unit: shows metadata plus a paginated
    table of its volunteers.
    """

    model = Unit
    template_name = "personnel/unit_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass the unit's active volunteers to the template.
        context["volunteers"] = self.object.volunteers.filter(is_active=True).order_by(
            "serial_no"
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

    model = Volunteer
    template_name = "personnel/volunteer_list.html"
    context_object_name = "volunteers"
    paginate_by = 50  # 50 rows per page keeps the page fast

    def get_queryset(self):
        qs = (
            Volunteer.objects.select_related("unit")  # joins Unit in a single SQL query
            .filter(is_active=True)
            .order_by("unit__name", "serial_no")
        )

        self.q = self.request.GET.get("q", "").strip()
        self.unit_id = self.request.GET.get("unit", "").strip()
        self.gender = self.request.GET.get("gender", "").strip()

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
        context["q"] = self.q
        context["selected_unit"] = self.unit_id
        context["selected_gender"] = self.gender
        context["units"] = Unit.objects.order_by("name")
        context["total_count"] = self.get_queryset().count()
        return context


class VolunteerDetailView(LoginRequiredMixin, DetailView):
    """
    Full detail card for a single Volunteer.

    Adds a combined service log: *incident* deployments (team operation via
    IncidentAssignment) plus *individual* office duty (legacy periods and
    monthly CSV aggregates).  Year-wise day summaries for wage-style reporting.
    """

    model = Volunteer
    template_name = "personnel/volunteer_detail.html"

    def get_queryset(self):
        return Volunteer.objects.select_related("unit").prefetch_related(
            "training_attendances__training_instance__training",
            "incident_assignments__incident",
            "office_duty_periods",
            "office_duty_months",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vol = self.object
        rows = build_service_log_rows(vol)
        context["service_log_rows"] = rows
        context["service_year_summary"] = build_year_summary(rows)
        # Admin / owning UIC: de-roster modal when active; reinstate modal when inactive.
        context["can_deroster_volunteer"] = can_deroster_volunteer(
            self.request.user,
            vol,
        )
        return context


class VolunteerDeRosterView(LoginRequiredMixin, View):
    """
    POST-only: set is_active=False and store de-roster date + reason.

    Anonymous users never reach here (LoginRequiredMixin). Authenticated users
    who are not Admin/UIC for this volunteer's unit get HTTP 403.
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        # Resolve the volunteer from the URL primary key; 404 if missing.
        volunteer = get_object_or_404(
            Volunteer.objects.select_related("unit"), pk=kwargs["pk"]
        )
        # Authorisation: same rule as office-duty CSV — Admin/superuser or UIC of this unit only.
        if not can_deroster_volunteer(request.user, volunteer):
            raise PermissionDenied
        # Idempotent guard: inactive rows cannot be "de-rostered" again from this endpoint.
        if not volunteer.is_active:
            messages.info(request, "This volunteer is already de-rostered or inactive.")
            return redirect("personnel:volunteer-detail", pk=volunteer.pk)

        # Validate POST body (date + minimum-length reason); on failure, flash errors and stay on detail.
        form = VolunteerDeRosterForm(request.POST)
        if not form.is_valid():
            for _field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, err)
            return redirect("personnel:volunteer-detail", pk=volunteer.pk)

        # Persist soft removal + audit fields; full save() updates TimeStampedModel.updated_at.
        volunteer.is_active = False
        volunteer.derostered_on = form.cleaned_data["derostered_on"]
        volunteer.deroster_reason = form.cleaned_data["deroster_reason"].strip()
        volunteer.save()
        messages.success(
            request,
            f"{volunteer.name} has been de-rostered from active service.",
        )
        return redirect("personnel:volunteer-detail", pk=volunteer.pk)


class VolunteerReinstateView(LoginRequiredMixin, View):
    """
    POST-only: return a volunteer to the active roster.

    Clears de-roster audit fields so the UI no longer shows "De-rostered";
    historical fact of a past de-roster is not retained on the row (use Django
    admin history / backups if a permanent audit trail is required).
    """

    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        volunteer = get_object_or_404(
            Volunteer.objects.select_related("unit"), pk=kwargs["pk"]
        )
        if not can_deroster_volunteer(request.user, volunteer):
            raise PermissionDenied
        if volunteer.is_active:
            messages.info(request, "This volunteer is already on the active roster.")
            return redirect("personnel:volunteer-detail", pk=volunteer.pk)

        volunteer.is_active = True
        volunteer.derostered_on = None
        volunteer.deroster_reason = ""
        volunteer.save()
        messages.success(
            request,
            f"{volunteer.name} has been reinstated to the active roster.",
        )
        return redirect("personnel:volunteer-detail", pk=volunteer.pk)


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY — MONTHLY CSV (template download, upload, admin status, email UIC)
# ─────────────────────────────────────────────────────────────────────────────


class OfficeDutyMonthlyHubView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """
    Landing page: download blank CSV (GET to separate URL) and upload filled CSV.

    UICs work only for their unit; Admins pick any unit.
    """

    template_name = "personnel/office_duty_monthly.html"

    def test_func(self) -> bool:
        return can_access_office_duty_monthly_hub(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        initial = {"year": today.year, "month": today.month}
        if getattr(self.request.user, "unit_id", None):
            initial["unit"] = self.request.user.unit
        context["download_form"] = OfficeDutyMonthlySelectorForm(
            initial=initial,
            user=self.request.user,
            prefix="dl",
        )
        context["upload_form"] = OfficeDutyMonthlyUploadForm(
            initial=initial,
            user=self.request.user,
            prefix="up",
        )
        context["is_personnel_admin"] = is_personnel_admin_user(self.request.user)
        return context


class OfficeDutyMonthlyTemplateDownloadView(
    LoginRequiredMixin, UserPassesTestMixin, View
):
    """GET: validated unit/year/month → CSV attachment."""

    def test_func(self) -> bool:
        return can_access_office_duty_monthly_hub(self.request.user)

    def get(self, request, *args, **kwargs):
        form = OfficeDutyMonthlySelectorForm(
            request.GET, user=request.user, prefix="dl"
        )
        if not form.is_valid():
            return HttpResponseBadRequest("Invalid or incomplete parameters.")
        unit = form.cleaned_data["unit"]
        year = form.cleaned_data["year"]
        month = form.cleaned_data["month"]
        body = build_office_duty_template_csv_bytes(unit, year, month)
        filename = f"office-duty_{unit.slug}_{year}_{month:02d}.csv"
        response = HttpResponse(body, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class OfficeDutyMonthlyUploadView(LoginRequiredMixin, UserPassesTestMixin, View):
    """POST: multipart CSV → upsert monthly rows + submission record."""

    http_method_names = ["post"]

    def test_func(self) -> bool:
        return can_access_office_duty_monthly_hub(self.request.user)

    def post(self, request, *args, **kwargs):
        form = OfficeDutyMonthlyUploadForm(
            request.POST,
            request.FILES,
            user=request.user,
            prefix="up",
        )
        if not form.is_valid():
            for _field, errs in form.errors.items():
                for err in errs:
                    messages.error(request, err)
            return redirect("personnel:office-duty-monthly")
        unit = form.cleaned_data["unit"]
        year = form.cleaned_data["year"]
        month = form.cleaned_data["month"]
        upload = form.cleaned_data["csv_file"]
        try:
            raw = upload.read()
            count = apply_office_duty_csv_upload(
                raw,
                unit,
                year,
                month,
                request.user,
            )
        except DjangoValidationError as exc:
            err_dict = getattr(exc, "message_dict", None)
            if isinstance(err_dict, dict):
                for parts in err_dict.values():
                    for part in parts:
                        messages.error(request, part)
            else:
                for part in exc.messages:
                    messages.error(request, part)
            return redirect("personnel:office-duty-monthly")
        messages.success(
            request,
            f"Imported office duty for {count} volunteer(s) — {unit.name} {year}-{month:02d}.",
        )
        return redirect("personnel:office-duty-monthly")


class OfficeDutyMonthlyStatusView(
    LoginRequiredMixin, UserPassesTestMixin, TemplateView
):
    """
    Admin-only matrix: each unit shows whether a submission exists for the
    selected calendar month, plus optional email-template action for one unit.
    """

    template_name = "personnel/office_duty_status.html"

    def test_func(self) -> bool:
        return is_personnel_admin_user(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        filt = OfficeDutyMonthlyStatusFilterForm(
            self.request.GET or None,
            initial={"year": today.year, "month": today.month},
            prefix="st",
        )
        year, month = today.year, today.month
        if filt.is_valid():
            year = filt.cleaned_data["year"]
            month = filt.cleaned_data["month"]
        subs = {
            s.unit_id: s
            for s in OfficeDutyMonthSubmission.objects.filter(
                year=year,
                month=month,
            ).select_related("unit", "submitted_by")
        }
        rows = []
        for unit in Unit.objects.order_by("name"):
            sub = subs.get(unit.pk)
            rows.append(
                {
                    "unit": unit,
                    "submission": sub,
                    "submitted": sub is not None,
                },
            )
        context["filter_form"] = filt
        context["status_year"] = year
        context["status_month"] = month
        context["unit_rows"] = rows
        context["email_form"] = OfficeDutyEmailUICForm(
            initial={"year": year, "month": month},
            prefix="em",
        )
        return context


class OfficeDutyEmailTemplateToUICView(LoginRequiredMixin, UserPassesTestMixin, View):
    """
    POST: build the same blank CSV as download and email each UIC for the unit.

    If there is no UIC or no usable email, do not send mail (choice B): message
    + admin must download the template and contact the UIC manually.
    """

    http_method_names = ["post"]

    def test_func(self) -> bool:
        return is_personnel_admin_user(self.request.user)

    def post(self, request, *args, **kwargs):
        form = OfficeDutyEmailUICForm(request.POST, prefix="em")
        if not form.is_valid():
            for _f, errs in form.errors.items():
                for err in errs:
                    messages.error(request, err)
            return redirect("personnel:office-duty-status")

        unit = form.cleaned_data["unit"]
        year = form.cleaned_data["year"]
        month = form.cleaned_data["month"]
        uics = list(
            User.objects.filter(
                role=UserRole.UNIT_IN_CHARGE,
                unit_id=unit.pk,
                is_active=True,
            ),
        )
        attachment = build_office_duty_template_csv_bytes(unit, year, month)
        filename = f"office-duty_{unit.slug}_{year}_{month:02d}.csv"

        if not uics:
            messages.warning(
                request,
                "No active Unit In-Charge user is linked to this unit. "
                "Download the template below and contact the UIC manually.",
            )
            return redirect(
                f"{reverse('personnel:office-duty-status')}?st-year={year}&st-month={month}"
            )

        recipients = [u for u in uics if (u.email or "").strip()]
        if not recipients:
            messages.warning(
                request,
                "No UIC email address on file. Download the template and contact the UIC manually.",
            )
            return redirect(
                f"{reverse('personnel:office-duty-status')}?st-year={year}&st-month={month}"
            )

        subject = (
            f"[Civil Defence] Office duty CSV template — {unit.name} {year}-{month:02d}"
        )
        body = (
            f"Please fill the attached CSV with days worked in office for {year}-{month:02d} "
            f"and upload it via Personnel → Office duty (CSV) on the web portal.\n\n"
            f"Unit: {unit.name}\n"
        )
        from_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", None) or "webmaster@localhost"
        )
        sent = 0
        for u in recipients:
            msg = EmailMessage(subject, body, from_email, [u.email.strip()])
            msg.attach(filename, attachment, "text/csv")
            msg.send(fail_silently=False)
            sent += 1
        messages.success(request, f"Sent template by email to {sent} UIC recipient(s).")
        return redirect(
            f"{reverse('personnel:office-duty-status')}?st-year={year}&st-month={month}"
        )
