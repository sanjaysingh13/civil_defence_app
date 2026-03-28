"""
Personnel app forms.

Small forms used by views that need validation beyond raw POST parsing.
"""

from django import forms


class OfficeDutyStartForm(forms.Form):
    """
    POST body for starting an office-duty period.

    The HTML date input sends an ISO date string; DateField parses it and
    validates that it looks like a real calendar date.
    """

    start_date = forms.DateField(
        label="Start date",
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control form-control-sm",
                "id": "id_office_duty_start_date",
            },
        ),
    )
