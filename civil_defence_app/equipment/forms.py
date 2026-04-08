"""
Equipment app forms.

EquipmentMaintenanceLogForm
    Used by Unit In-Charges to record a maintenance inspection result
    for a specific equipment item.  The form is intentionally simple:
      • check_date  — date of inspection (defaults to today)
      • is_fit      — boolean checkbox: "Equipment is fit for service?"
      • remarks     — free-text observations / work done

    The view that processes this form is responsible for:
      1. Stamping `checked_by` = request.user (set outside the form).
      2. Updating Equipment.is_functional = is_fit.
      3. Updating Equipment.last_check_date = check_date.
      4. Updating Equipment.status to OK or REPAIR accordingly.

EquipmentCreateForm
    Admin web flow: unit + equipment type (+ optional quantity/notes). The view
    sets name, category, unique_id, is_functional, and status on save.
"""

import datetime

from django import forms

from .models import Equipment
from .models import EquipmentMaintenanceLog


class EquipmentMaintenanceLogForm(forms.ModelForm):
    """
    ModelForm for creating a new EquipmentMaintenanceLog entry.

    ModelForm automatically generates fields from the model definition and
    handles validation.  We customise three things:
      1. Restrict fields to only what the UIC needs (exclude auto-managed ones).
      2. Set a sensible default for check_date (today).
      3. Add Bootstrap-friendly CSS classes and clear labels via widgets.
    """

    class Meta:
        model = EquipmentMaintenanceLog
        # We deliberately exclude:
        #   equipment   — set by the view from the URL kwargs, not user input
        #   checked_by  — set by the view from request.user
        #   status_after_check — auto-derived in the view from is_fit
        fields = ["check_date", "is_fit", "remarks"]
        widgets = {
            # DateInput renders an HTML5 date picker (<input type="date">)
            # which all modern browsers support natively.
            "check_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"},
            ),
            # CheckboxInput renders a single <input type="checkbox">.
            # We give it a Bootstrap utility class for consistent spacing.
            "is_fit": forms.CheckboxInput(
                attrs={"class": "form-check-input"},
            ),
            # Textarea for free-text observations.
            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Describe the condition, work done, parts replaced, etc.",
                },
            ),
        }
        labels = {
            "check_date": "Inspection Date",
            "is_fit": "Equipment is fit for service",
            "remarks": "Remarks / Observations",
        }
        help_texts = {
            "is_fit": (
                "Tick this box if the equipment is in working order after "
                "this inspection.  Untick to mark it as non-functional — "
                "this will update the equipment record immediately."
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        Override __init__ to set check_date to today's date by default.

        forms.DateInput doesn't auto-populate `initial` from model defaults,
        so we inject the today value into the form's initial data here.
        `initial` only affects unbound forms (no POST data yet); once the
        user submits, the POSTed value takes over.
        """
        super().__init__(*args, **kwargs)
        # Only pre-fill if no initial value was provided by the caller
        if not self.initial.get("check_date"):
            self.initial["check_date"] = datetime.date.today().isoformat()


class EquipmentCreateForm(forms.ModelForm):
    """
    Admin-only create: operator selects district unit and master equipment type.
    Long description text lives on ``EquipmentType`` only; this form does not
    duplicate it per physical item.
    """

    class Meta:
        model = Equipment
        fields = ["unit", "equipment_type", "quantity", "notes"]
        widgets = {
            "unit": forms.Select(attrs={"class": "form-select"}),
            "equipment_type": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control", "min": 1},
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Optional notes for this specific item…",
                },
            ),
        }
        labels = {
            "unit": "District unit",
            "equipment_type": "Equipment type",
            "quantity": "Quantity",
            "notes": "Notes (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["equipment_type"].required = True
