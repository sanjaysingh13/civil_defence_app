"""
Personnel app forms.

Small forms used by views that need validation beyond raw POST parsing.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from civil_defence_app.personnel.models import Unit


class OfficeDutyMonthlySelectorForm(forms.Form):
    """
    Shared unit / year / month selectors for CSV download and upload.

    Admins must pick a unit; UICs use a hidden field fixed to their unit.
    """

    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        label="Year",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    month = forms.TypedChoiceField(
        choices=[(m, m) for m in range(1, 13)],
        coerce=int,
        label="Month",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    unit = forms.ModelChoiceField(
        queryset=Unit.objects.none(),
        required=False,
        label="Unit",
        empty_label=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)
        is_admin = bool(
            user
            and user.is_authenticated
            and (user.is_superuser or getattr(user, "is_admin_role", False)),
        )
        if is_admin:
            self.fields["unit"].queryset = Unit.objects.order_by("name")
            self.fields["unit"].required = True
        else:
            self.fields["unit"].widget = forms.HiddenInput()
            self.fields["unit"].required = False

    def clean(self):
        data = super().clean()
        if not self._user or not self._user.is_authenticated:
            return data
        is_admin = self._user.is_superuser or getattr(
            self._user, "is_admin_role", False
        )
        if not is_admin:
            u = getattr(self._user, "unit", None)
            if not u:
                raise forms.ValidationError("Your account has no unit assigned.")
            data["unit"] = u
        return data


class OfficeDutyMonthlyUploadForm(OfficeDutyMonthlySelectorForm):
    """Multipart upload of a filled monthly office-duty CSV."""

    csv_file = forms.FileField(
        label="Filled CSV file",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".csv,text/csv"}
        ),
    )


class OfficeDutyMonthlyStatusFilterForm(forms.Form):
    """Admin dashboard: pick calendar month for the submission matrix."""

    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    month = forms.TypedChoiceField(
        choices=[(m, m) for m in range(1, 13)],
        coerce=int,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class OfficeDutyEmailUICForm(forms.Form):
    """Admin: send blank template to Unit In-Charge user(s) for a unit + month."""

    unit = forms.ModelChoiceField(
        queryset=Unit.objects.order_by("name"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    year = forms.IntegerField(
        min_value=2000,
        max_value=2100,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    month = forms.TypedChoiceField(
        choices=[(m, m) for m in range(1, 13)],
        coerce=int,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class VolunteerDeRosterForm(forms.Form):
    """
    Confirms removal from active roster: a calendar date plus a short reason.

    The view sets Volunteer.is_active=False when this validates; the fields map
    directly to Volunteer.derostered_on and Volunteer.deroster_reason.
    """

    derostered_on = forms.DateField(
        label=_("De-roster date"),
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    deroster_reason = forms.CharField(
        label=_("Reason for de-rostering"),
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        min_length=3,
        help_text=_("Required — e.g. retirement, transfer, disciplinary, own request."),
    )
