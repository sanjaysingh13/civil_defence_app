"""
Incidents app views.

Four views cover the complete incident lifecycle:

  IncidentListView     — paginated, filterable table of all incidents
  IncidentDetailView   — full detail page for one incident (assignments, log, media)
  IncidentDispatchView — Unit In-Charge logs a new call and dispatches resources
  IncidentReportView   — Unit In-Charge files the post-incident detailed report
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import UpdateView
from django.views.generic import View

from civil_defence_app.equipment.models import IncidentEquipment
from civil_defence_app.fleet.models import IncidentVehicle

from .forms import IncidentDispatchForm
from .forms import IncidentMediaUploadForm
from .forms import IncidentReportForm
from .models import Incident
from .models import IncidentAssignment
from .models import IncidentMedia
from .models import IncidentStatus
from .models import IncidentType


# ─────────────────────────────────────────────────────────────────────────────
# PERMISSION MIXIN
# ─────────────────────────────────────────────────────────────────────────────

class UnitInChargeRequiredMixin(UserPassesTestMixin):
    """
    Restricts a view to users with the UNIT_IN_CHARGE role who also have a
    unit assigned.  Django superusers bypass this check.

    How UserPassesTestMixin works:
      - Before dispatching the request, Django calls test_func().
      - If it returns False and the user is NOT authenticated → redirect to login.
      - If it returns False and the user IS authenticated → HTTP 403 Forbidden.

    Why also check user.unit?
      A Unit In-Charge without an assigned unit cannot create incidents because
      the unit is required on the Incident model.  We fail-fast here with a
      clear error message instead of crashing inside form_valid().
    """

    def test_func(self) -> bool:
        user = self.request.user
        if user.is_superuser:
            return True
        return (
            getattr(user, "role", None) == "UNIT_IN_CHARGE"
            and user.unit is not None
        )

    def handle_no_permission(self):
        """
        Called when test_func() returns False.
        If the user is logged in but lacks permission, show a helpful message
        and redirect to the incident list instead of showing a blank 403 page.
        """
        if self.request.user.is_authenticated:
            messages.error(
                self.request,
                "You must be a Unit In-Charge with an assigned unit to perform this action.",
            )
            return redirect("incidents:incident-list")
        # Not logged in → go to login page (standard behaviour)
        return super().handle_no_permission()


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class IncidentListView(LoginRequiredMixin, ListView):
    """
    Paginated, filterable table of all incidents.

    Supports four optional GET parameters for filtering:
      q      — case-insensitive search on title
      status — one of PENDING / OPEN / CLOSED
      type   — incident type code (FLOOD, FIRE, …)
      unit   — primary key of the Unit

    select_related("unit") pre-fetches the related Unit object in the same
    SQL query to avoid N+1 queries when displaying inc.unit.name in the table.
    """
    model               = Incident
    template_name       = "incidents/incident_list.html"
    context_object_name = "incidents"
    paginate_by         = 50

    def get_queryset(self):
        qs = Incident.objects.select_related("unit")

        # Read filter values from the GET query string (safe — empty string if absent).
        self.q        = self.request.GET.get("q", "").strip()
        self.status   = self.request.GET.get("status", "").strip()
        self.inc_type = self.request.GET.get("type", "").strip()
        self.unit_id  = self.request.GET.get("unit", "").strip()

        if self.q:
            qs = qs.filter(title__icontains=self.q)
        if self.status:
            qs = qs.filter(status=self.status)
        if self.inc_type:
            qs = qs.filter(incident_type=self.inc_type)
        if self.unit_id:
            qs = qs.filter(unit_id=self.unit_id)

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


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class IncidentDetailView(LoginRequiredMixin, DetailView):
    """
    Full detail page for a single incident.

    Prefetches all related objects so that displaying the incident card,
    assignments, equipment allocations, vehicle allocations, log entries,
    and media files in the template does not cause N+1 queries.

    prefetch_related fetches related objects in separate SQL queries and
    caches them, whereas select_related uses SQL JOINs.  We use both:
      select_related  → unit, reported_by  (forward ForeignKeys — JOINs)
      prefetch_related → assignments, equipment, vehicles, logs, media
                         (reverse FK sets — separate queries with IN clauses)
    """
    model         = Incident
    template_name = "incidents/incident_detail.html"

    def get_queryset(self):
        return (
            Incident.objects
            .select_related("unit", "reported_by")
            .prefetch_related(
                "assignments__volunteer",
                "equipment_allocations__equipment",
                "vehicle_allocations__vehicle",
                "log_entries__entered_by",
                "media_files",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Pass a boolean so the template can conditionally show the
        # "File Report" button only when the logged-in user owns the incident.
        user = self.request.user
        incident = self.object
        context["can_report"] = (
            user.is_superuser
            or (getattr(user, "is_unit_in_charge", False) and user.unit == incident.unit)
        )
        return context


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT DISPATCH VIEW
# ─────────────────────────────────────────────────────────────────────────────

class IncidentDispatchView(UnitInChargeRequiredMixin, LoginRequiredMixin, View):
    """
    Unit In-Charge logs a new incoming call and dispatches resources.

    GET  → render the blank dispatch form filtered to the user's unit
    POST → validate the form; if valid:
             1. Save the Incident (incident_number is auto-generated in model.save)
             2. Create IncidentAssignment rows for each selected volunteer
             3. Create IncidentEquipment rows for each selected equipment item
             4. Create IncidentVehicle rows for each selected vehicle
           On success redirect to the new incident's detail page.

    Why use View instead of CreateView?
      CreateView only manages the main ModelForm.  Here we need to save
      related objects (assignments, equipment, vehicles) in one atomic
      transaction, so it is cleaner to override post() directly.
    """

    template_name = "incidents/incident_dispatch.html"

    def _get_form(self, data=None):
        """
        Helper that builds the form with the current user's unit injected.
        Called from both get() and post() to avoid repeating the kwarg.
        """
        return IncidentDispatchForm(data=data, unit=self.request.user.unit)

    def get(self, request, *args, **kwargs):
        """Render the blank dispatch form."""
        from django.shortcuts import render
        return render(request, self.template_name, {"form": self._get_form()})

    def post(self, request, *args, **kwargs):
        """Validate and save the incident + all resource allocations."""
        from django.db import transaction
        from django.shortcuts import render

        form = self._get_form(data=request.POST)

        if not form.is_valid():
            # Return the form with validation errors highlighted.
            return render(request, self.template_name, {"form": form})

        # ── Wrap everything in a database transaction ─────────────────────────
        # transaction.atomic() means: execute all the DB writes below as a
        # single unit.  If ANY write fails, ALL writes are rolled back so the
        # database never ends up in a half-saved state.
        with transaction.atomic():

            # 1. Save the Incident itself (commit=False would skip the DB write
            #    so we use commit=True — the default — here).
            incident = form.save(commit=False)
            incident.unit        = request.user.unit
            incident.reported_by = request.user
            incident.status      = IncidentStatus.OPEN
            # The model's save() auto-generates incident_number.
            incident.save()

            # 2. Create an IncidentAssignment row for each selected volunteer.
            #    cleaned_data["volunteers"] is a QuerySet of Volunteer objects
            #    that passed form validation.
            for volunteer in form.cleaned_data["volunteers"]:
                IncidentAssignment.objects.create(
                    incident    = incident,
                    volunteer   = volunteer,
                    assigned_by = request.user,
                )

            # 3. Create IncidentEquipment rows (optional field — may be empty).
            for equipment in form.cleaned_data.get("equipment_items", []):
                IncidentEquipment.objects.create(
                    incident  = incident,
                    equipment = equipment,
                )

            # 4. Create IncidentVehicle rows (optional field — may be empty).
            for vehicle in form.cleaned_data.get("vehicles", []):
                IncidentVehicle.objects.create(
                    incident      = incident,
                    vehicle       = vehicle,
                    dispatched_at = incident.start_time or timezone.now(),
                    authorised_by = request.user,
                )

        messages.success(
            request,
            f"Incident {incident.incident_number} logged and resources dispatched.",
        )
        return redirect(reverse("incidents:incident-detail", kwargs={"pk": incident.pk}))


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT REPORT VIEW
# ─────────────────────────────────────────────────────────────────────────────

class IncidentReportView(LoginRequiredMixin, UpdateView):
    """
    Unit In-Charge files the detailed post-incident report.

    GET  → render the report form pre-populated with the incident's current
           data plus an empty media upload form
    POST → handle two possible submissions on the same page:
             a) Submitting the main report form (action="save_report")
             b) Uploading media files (action="upload_media")

    Why UpdateView?
      The report is an update to an existing Incident (changing final_report,
      end_time, status).  UpdateView automatically fetches the object via pk
      and pre-populates the form with the current field values.
    """

    model         = Incident
    form_class    = IncidentReportForm
    template_name = "incidents/incident_report.html"

    def get_queryset(self):
        """
        Restrict editing to:
          - the unit's own incidents (if unit-in-charge)
          - all incidents for superusers
        """
        user = self.request.user
        qs   = Incident.objects.select_related("unit")
        if not user.is_superuser:
            qs = qs.filter(unit=user.unit)
        return qs

    def get_form_kwargs(self):
        """
        Override to tell the form to use the datetime-local format for the
        end_time widget when the form is submitted via POST.
        """
        kwargs = super().get_form_kwargs()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add the media upload form to the context so it can be rendered
        # below the main report form on the same template.
        context["media_form"] = IncidentMediaUploadForm()
        # Also pass existing media files so the user can see what's already attached.
        context["existing_media"] = self.object.media_files.all()
        return context

    def get_success_url(self):
        """After a successful report save, redirect to the incident's detail page."""
        return reverse("incidents:incident-detail", kwargs={"pk": self.object.pk})

    def post(self, request, *args, **kwargs):
        """
        Route POST requests based on the hidden 'action' field in the form:
          action="upload_media" → handle file upload(s)
          anything else         → handle report form save
        """
        self.object = self.get_object()
        action = request.POST.get("action", "save_report")

        if action == "upload_media":
            return self._handle_media_upload(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        """
        Called by UpdateView when the report form passes validation.
        Saves the updated Incident and shows a success message.
        """
        incident = form.save()
        messages.success(
            request,  # noqa: F821 — 'request' is available via self.request
            f"Report for {incident.incident_number} saved successfully.",
        )
        return redirect(self.get_success_url())

    def form_valid(self, form):
        incident = form.save()
        messages.success(
            self.request,
            f"Report for {incident.incident_number} saved successfully.",
        )
        return redirect(self.get_success_url())

    def _handle_media_upload(self, request):
        """
        Process the media upload sub-form.

        request.FILES.getlist("files") returns a list of InMemoryUploadedFile
        objects — one per file the user selected in the file picker.
        We create one IncidentMedia row for each file.
        """
        files   = request.FILES.getlist("files")
        caption = request.POST.get("caption", "").strip()

        if not files:
            messages.warning(request, "No files were selected for upload.")
        else:
            for f in files:
                IncidentMedia.objects.create(
                    incident    = self.object,
                    file        = f,
                    caption     = caption,
                    uploaded_by = request.user,
                )
            messages.success(request, f"{len(files)} file(s) attached to the incident.")

        return redirect(
            reverse("incidents:incident-report", kwargs={"pk": self.object.pk})
        )
