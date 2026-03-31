"""
Forms for creating training programmes and training instances (batches) from the web UI.

Admin users can pick any unit and any active volunteer. Unit In-Charge users are
scoped to their own unit for both the organising unit (fixed) and volunteer selection.
"""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from civil_defence_app.personnel.models import Unit
from civil_defence_app.personnel.models import Volunteer

from .models import Training
from .models import TrainingInstance


class TrainingProgrammeForm(forms.ModelForm):
    """Create a Training programme definition (Admin-only in the UI)."""

    class Meta:
        model = Training
        fields = ("name", "training_type", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "training_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }


class TrainingInstanceWithVolunteersForm(forms.Form):
    """
    Create one TrainingInstance plus TrainingAttendance rows for selected volunteers.

    The volunteers field is validated against a queryset set in __init__ (all active
    volunteers for Admin; this unit only for UIC). The template pairs it with
    autocomplete UI; submitted values are standard POST multi-values for volunteer PKs.
    """

    training = forms.ModelChoiceField(
        label=_("Training programme"),
        queryset=Training.objects.all(),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_training"}),
    )

    unit = forms.ModelChoiceField(
        label=_("Organising unit"),
        queryset=Unit.objects.all(),
        required=False,
        empty_label=_("Inter-district / not specified"),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_unit"}),
    )

    batch_no = forms.CharField(
        label=_("Batch / certificate prefix"),
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    location = forms.CharField(
        label=_("Venue / location"),
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    start_date = forms.DateField(
        label=_("Start date"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    end_date = forms.DateField(
        label=_("End date"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    instructor = forms.CharField(
        label=_("Instructor"),
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    volunteers = forms.ModelMultipleChoiceField(
        label=_("Volunteers to enrol"),
        queryset=Volunteer.objects.none(),
        required=True,
        help_text=_("Type to search, then add each person. At least one volunteer is required."),
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select",
                "id": "id_volunteers",
                "aria-describedby": "volunteers-field-help",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user
        is_admin = user and (
            user.is_superuser or getattr(user, "is_admin_role", False)
        )
        if is_admin:
            self.fields["volunteers"].queryset = Volunteer.objects.filter(
                is_active=True
            ).order_by("name")
        else:
            self.fields.pop("unit")
            self.fields["volunteers"].queryset = Volunteer.objects.filter(
                unit_id=user.unit_id,
                is_active=True,
            ).order_by("name")

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError(
                _("End date cannot be before start date."),
            )
        return cleaned

    def save_instance(self):
        """
        Persist TrainingInstance. Caller must wrap in transaction.atomic and
        create TrainingAttendance rows for cleaned_data['volunteers'].
        """
        data = self.cleaned_data
        is_admin = self._user and (
            self._user.is_superuser or getattr(self._user, "is_admin_role", False)
        )
        if is_admin:
            unit = data.get("unit")
        else:
            unit = self._user.unit

        return TrainingInstance.objects.create(
            training=data["training"],
            unit=unit,
            batch_no=data.get("batch_no") or "",
            location=data.get("location") or "",
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            instructor=data.get("instructor") or "",
            notes=data.get("notes") or "",
        )
