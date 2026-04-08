"""
Incidents app forms.

Three forms handle the Unit In-Charge's incident workflow:

  1. IncidentDispatchForm
        The Unit In-Charge receives a call → fills this form to:
          a) create a new Incident record
          b) select volunteers to dispatch (required — at least one)
          c) select equipment from the unit's inventory (optional)
          d) select vehicles from the unit's fleet (optional)

        The volunteer / equipment / vehicle querysets are scoped to the
        user's own unit, so he only ever sees his district's resources.

  2. IncidentReportForm
        After operations conclude, the Unit In-Charge fills this to:
          a) write the full narrative report
          b) record the end time
          c) change status to CLOSED

  3. IncidentMediaUploadForm
        A standalone form rendered on the report page that lets the
        Unit In-Charge attach one or more photos / videos to the incident.
        Multiple files are collected from the HTTP request via
        request.FILES.getlist("files") in the view.
"""

from itertools import zip_longest

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM MULTI-FILE INPUT WIDGET
#
# Django 4.1+ raised a ValueError if you tried to set multiple=True on the
# built-in FileInput or ClearableFileInput widgets because they don't handle
# the resulting list of files internally.  We create a thin subclass that
# explicitly opts in to multi-file selection by setting the class attribute
# `allow_multiple_selected = True`.  The actual multi-file reading is then
# done in the view via  request.FILES.getlist("files").
# ─────────────────────────────────────────────────────────────────────────────


class MultipleFileInput(forms.FileInput):
    """FileInput subclass that allows selecting multiple files at once."""

    allow_multiple_selected = True


# Import the models from sibling apps using their full app paths.
# Django resolves these after all apps are loaded; this pattern avoids
# circular-import issues caused by importing at module level from another app.
from civil_defence_app.equipment.models import Equipment
from civil_defence_app.fleet.models import Vehicle
from civil_defence_app.personnel.models import Volunteer

from .models import Incident
from .models import IncidentAssignmentRole
from .models import IncidentStatus


def _multi_value_list(data, key: str) -> list:
    """
    Read a possibly repeated POST key as a list.

    ``request.POST`` is a QueryDict (has ``getlist``); unit tests often pass a
    plain dict with list values — this helper supports both.
    """
    if hasattr(data, "getlist"):
        return list(data.getlist(key))
    raw = data.get(key, [])
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT DISPATCH FORM
# ─────────────────────────────────────────────────────────────────────────────


class IncidentDispatchForm(forms.ModelForm):
    """
    Form for logging a new incident call and dispatching resources.

    How it works:
      - Volunteer dispatch is *not* a ModelForm field: the template posts
        parallel lists ``assignment_volunteer`` (primary keys) and
        ``assignment_role`` (IncidentAssignmentRole values).  :meth:`clean`
        zips them into ``cleaned_data["dispatch_assignments"]`` as
        ``list[tuple[Volunteer, str]]``.

      - The extra fields ``equipment_items`` and ``vehicles`` are not on the
        Incident model; the view creates IncidentEquipment / IncidentVehicle
        rows after the Incident is saved.

      - ``__init__`` receives ``unit=`` from the view to scope equipment and
        vehicles querysets.  Use :meth:`volunteers_for_dispatch` and
        :attr:`assignment_role_choices` in the template for the autocomplete
        and per-row role dropdowns.

    Widget choices:
      - Equipment and vehicles use SelectMultiple list-boxes (Ctrl/Cmd multi-select).
      - Standard Incident fields use Bootstrap 5 ``form-control`` / ``form-select``.
    """

    # ── Equipment multi-select (OPTIONAL) ─────────────────────────────────────
    equipment_items = forms.ModelMultipleChoiceField(
        queryset=Equipment.objects.none(),
        required=False,
        label=_("Equipment to Deploy (optional)"),
        help_text=_(
            "Select one or more functional equipment items from your unit's inventory."
        ),
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select",
                "size": "6",
                "id": "id_equipment_items",
            }
        ),
    )

    # ── Vehicle multi-select (OPTIONAL) ───────────────────────────────────────
    vehicles = forms.ModelMultipleChoiceField(
        queryset=Vehicle.objects.none(),
        required=False,
        label=_("Vehicles to Dispatch (optional)"),
        help_text=_("Select one or more available vehicles from your unit's fleet."),
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select",
                "size": "5",
                "id": "id_vehicles",
            }
        ),
    )

    class Meta:
        # Tell Django this ModelForm is backed by the Incident model.
        # Only the fields listed here are rendered in the HTML form;
        # the rest (unit, reported_by, incident_number, status) are set
        # programmatically inside the view's form_valid() method.
        model = Incident
        fields = [
            "title",
            "incident_type",
            "location_text",
            "start_time",
            "description",
        ]

        # widgets dict maps field names to custom widget instances.
        # Bootstrap's 'form-control' class gives consistent styling.
        # 'type': 'datetime-local' renders a native date+time picker in browsers.
        widgets = {
            "title": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Flash flood in Alipurduar Block I",
                    "autofocus": True,
                }
            ),
            "incident_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "location_text": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Village, Block, PS, nearest landmark…",
                }
            ),
            "start_time": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Brief description of the situation as reported…",
                }
            ),
        }

    def __init__(self, *args, unit=None, **kwargs):
        """
        Override __init__ to inject the unit and filter all three
        resource querysets to that unit's inventory.

        Parameters
        ----------
        unit : personnel.Unit | None
            The Unit object of the logged-in Unit In-Charge.
            Passed as a keyword argument from the view.
        """
        # Call the parent __init__ first so self.fields is populated.
        super().__init__(*args, **kwargs)

        # Unit is required for validating assignment_volunteer PKs and for
        # volunteers_for_dispatch in the template.
        self._unit = unit

        if unit:
            # Equipment that is functional (status="OK") — don't show items under repair.
            self.fields["equipment_items"].queryset = Equipment.objects.filter(
                unit=unit, status="OK"
            ).order_by("category", "name")
            # Only AVAILABLE vehicles — deployed or maintenance vehicles can't be sent.
            self.fields["vehicles"].queryset = Vehicle.objects.filter(
                unit=unit, status="AVAILABLE"
            ).order_by("vehicle_type", "registration_no")

        # Pre-populate start_time with the current local time so the user
        # doesn't have to type it manually for an urgent dispatch.
        # The format must match the datetime-local HTML input: "YYYY-MM-DDTHH:MM"
        if not self.initial.get("start_time"):
            self.initial["start_time"] = timezone.now().strftime("%Y-%m-%dT%H:%M")

    @property
    def assignment_role_choices(self):
        """(value, label) tuples for IncidentAssignmentRole — template role <select>s."""
        return IncidentAssignmentRole.choices

    def volunteers_for_dispatch(self):
        """
        Active volunteers in the UIC's unit, ordered by name.

        Used by the dispatch template for autocomplete source data and empty-state checks.
        """
        if self._unit is None:
            return Volunteer.objects.none()
        return Volunteer.objects.filter(unit=self._unit, is_active=True).order_by(
            "name"
        )

    def posted_dispatch_rows(self) -> list[dict[str, str]]:
        """
        After a failed POST, rebuild assignment rows so the user does not lose
        their volunteer picks (each dict: value=PK, label=name, role=role value).
        """
        if not self.is_bound:
            return []
        ids = _multi_value_list(self.data, "assignment_volunteer")
        roles = _multi_value_list(self.data, "assignment_role")
        rows: list[dict[str, str]] = []
        default_role = IncidentAssignmentRole.FIREFIGHTER
        for pk_str, role in zip_longest(ids, roles, fillvalue=""):
            if not pk_str:
                continue
            display_name = str(pk_str)
            try:
                pk_int = int(pk_str)
            except (TypeError, ValueError):
                rows.append(
                    {
                        "value": str(pk_str),
                        "label": display_name,
                        "role": role or default_role,
                    },
                )
                continue
            vol = Volunteer.objects.filter(pk=pk_int).first()
            if vol is not None:
                display_name = vol.name
            rows.append(
                {
                    "value": str(pk_int),
                    "label": display_name,
                    "role": role or default_role,
                },
            )
        return rows

    def clean(self):
        """
        Build ``dispatch_assignments`` from POST lists ``assignment_volunteer``
        and ``assignment_role`` (same length, one role per volunteer).
        """
        cleaned_data = super().clean()

        if self._unit is None:
            raise ValidationError(_("Cannot validate dispatch without a unit context."))

        raw_ids = _multi_value_list(self.data, "assignment_volunteer")
        raw_roles = _multi_value_list(self.data, "assignment_role")

        if len(raw_ids) != len(raw_roles):
            raise ValidationError(
                _("Each dispatched volunteer must have exactly one role selected."),
            )

        if not raw_ids:
            raise ValidationError(
                _("Add at least one volunteer to dispatch."),
            )

        if len(raw_ids) != len(set(raw_ids)):
            raise ValidationError(_("The same volunteer cannot be added twice."))

        valid_roles = {choice for choice, _label in IncidentAssignmentRole.choices}

        parsed_ids: list[int] = []
        for pk_str in raw_ids:
            try:
                parsed_ids.append(int(pk_str))
            except (TypeError, ValueError) as exc:
                raise ValidationError(_("Invalid volunteer selection.")) from exc

        allowed_volunteers = {
            v.pk: v
            for v in Volunteer.objects.filter(
                unit=self._unit,
                is_active=True,
                pk__in=parsed_ids,
            )
        }

        pairs: list[tuple[Volunteer, str]] = []
        for pk, role in zip(parsed_ids, raw_roles, strict=True):
            volunteer = allowed_volunteers.get(pk)
            if volunteer is None:
                raise ValidationError(
                    _("Unknown or inactive volunteer selected for this unit."),
                )
            if role not in valid_roles:
                raise ValidationError(_("Invalid role selection."))
            pairs.append((volunteer, role))

        cleaned_data["dispatch_assignments"] = pairs
        return cleaned_data


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT REPORT FORM
# ─────────────────────────────────────────────────────────────────────────────


class IncidentReportForm(forms.ModelForm):
    """
    Form for filing the detailed post-incident report.

    Rendered on the Incident Report page after operations conclude.
    The Unit In-Charge:
      - writes the full narrative in 'final_report'
      - records the exact time the response ended in 'end_time'
      - sets the status to CLOSED (or keeps it OPEN if still ongoing)

    Media files (photos / videos) are handled by IncidentMediaUploadForm
    rendered below this form on the same page.
    """

    class Meta:
        model = Incident
        fields = ["final_report", "end_time", "status"]
        widgets = {
            # Large textarea — reports can be detailed multi-paragraph narratives.
            "final_report": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 12,
                    "placeholder": (
                        "Write the complete incident report:\n\n"
                        "1. Nature and scope of the incident\n"
                        "2. Actions taken by the response team\n"
                        "3. Resources utilised (personnel, equipment, vehicles)\n"
                        "4. Outcome and damage/casualty assessment\n"
                        "5. Handover / follow-up actions required\n"
                        "6. Recommendations"
                    ),
                }
            ),
            "end_time": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Pre-populate end_time with the current time as a sensible default,
        and set the status initial value to CLOSED.
        """
        super().__init__(*args, **kwargs)

        # If the incident already has an end_time, show it in the field.
        # Otherwise default to now (the report is usually filed at the end).
        if self.instance and self.instance.end_time:
            self.initial["end_time"] = self.instance.end_time.strftime("%Y-%m-%dT%H:%M")
        else:
            self.initial["end_time"] = timezone.now().strftime("%Y-%m-%dT%H:%M")

        # Default the status dropdown to CLOSED unless already set.
        if not self.instance or self.instance.status != IncidentStatus.OPEN:
            pass  # keep existing status
        else:
            self.initial.setdefault("status", IncidentStatus.CLOSED)


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT MEDIA UPLOAD FORM
# ─────────────────────────────────────────────────────────────────────────────


class IncidentMediaUploadForm(forms.Form):
    """
    Standalone form for attaching one or more photo / video files
    to an existing Incident record.

    Why a separate form?
      Django ModelForms handle only a single FileField cleanly.  For
      multiple file uploads we use a plain Form with a single <input
      type="file" multiple> element, then collect all the uploaded files
      via  request.FILES.getlist("files")  in the view.

    The 'files' field itself is optional (required=False) so the report
    form can be submitted without any media if the user has no files.
    """

    files = forms.FileField(
        label=_("Attach Photos / Videos"),
        required=False,
        # Use our custom MultipleFileInput widget (defined at the top of this file)
        # which sets allow_multiple_selected=True to satisfy Django's check.
        # The view reads all uploaded files via request.FILES.getlist("files").
        widget=MultipleFileInput(
            attrs={
                "class": "form-control",
                "multiple": True,
                "accept": "image/jpeg,image/png,image/gif,video/mp4,video/webm",
            }
        ),
    )

    caption = forms.CharField(
        max_length=255,
        required=False,
        label=_("Caption (applied to all uploaded files)"),
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "e.g. 'Scene at arrival' or 'Team in action'…",
            }
        ),
    )
