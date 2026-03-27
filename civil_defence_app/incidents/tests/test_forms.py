"""
Tests for incidents/forms.py

What we verify:
  - IncidentDispatchForm: volunteers field is required.
  - IncidentDispatchForm: equipment_items and vehicles are optional.
  - IncidentDispatchForm: querysets are scoped to the supplied unit —
    resources from another unit must not appear.
  - IncidentDispatchForm: valid complete submission passes validation.
  - IncidentReportForm: valid submission with all fields passes.
  - IncidentReportForm: final_report text is preserved.
"""

from __future__ import annotations

import pytest

from civil_defence_app.incidents.forms import IncidentDispatchForm
from civil_defence_app.incidents.forms import IncidentReportForm
from civil_defence_app.incidents.models import IncidentStatus

from .factories import EquipmentFactory
from .factories import IncidentFactory
from .factories import UICUserFactory
from .factories import UnitFactory
from .factories import VehicleFactory
from .factories import VolunteerFactory

pytestmark = pytest.mark.django_db


class TestIncidentDispatchForm:
    """
    Tests for IncidentDispatchForm — the form a Unit In-Charge uses to log a
    new incident and dispatch resources.

    The form receives a `unit` kwarg from the view; it uses it to filter the
    volunteers / equipment / vehicles querysets to that unit only.
    """

    def _minimal_post_data(self, volunteer_ids: list[int]) -> dict:
        """
        Helper that returns the minimum valid POST data for the dispatch form.
        title and incident_type are the only model-level required fields;
        volunteers is required at the form level.
        """
        return {
            "title": "Flash flood near river bank",
            "incident_type": "FLOOD",
            "volunteers": volunteer_ids,
        }

    def test_volunteers_required_when_empty(self):
        """
        Submitting the form without selecting any volunteer must fail
        validation — the 'volunteers' field has required=True.
        """
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_ids=[])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert not form.is_valid()
        assert "volunteers" in form.errors

    def test_valid_form_with_volunteers_only(self):
        """
        Selecting at least one volunteer (no equipment, no vehicles) must
        pass validation because equipment_items and vehicles are optional.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_ids=[volunteer.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors

    def test_equipment_is_optional(self):
        """
        Omitting equipment_items from the POST data must NOT cause a
        validation error — the field has required=False.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        EquipmentFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_ids=[volunteer.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        assert list(form.cleaned_data["equipment_items"]) == []

    def test_vehicles_is_optional(self):
        """
        Omitting vehicles from the POST data must NOT cause a validation
        error — the field has required=False.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        VehicleFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_ids=[volunteer.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        assert list(form.cleaned_data["vehicles"]) == []

    def test_volunteers_queryset_scoped_to_unit(self):
        """
        The volunteers queryset must only contain active volunteers from the
        supplied unit.  Volunteers from another unit must be excluded even if
        their PKs are passed in the POST data — Django rejects IDs outside
        the queryset with a validation error.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        volunteer_b = VolunteerFactory.create(unit=unit_b)
        VolunteerFactory.create(unit=unit_a)
        data = self._minimal_post_data(volunteer_ids=[volunteer_b.pk])
        form = IncidentDispatchForm(data=data, unit=unit_a)
        assert not form.is_valid()
        assert "volunteers" in form.errors

    def test_inactive_volunteers_excluded(self):
        """
        Inactive volunteers (is_active=False) must be excluded from the
        queryset regardless of unit — they should not be deployable.
        """
        unit = UnitFactory.create()
        inactive = VolunteerFactory.create(unit=unit, is_active=False)
        data = self._minimal_post_data(volunteer_ids=[inactive.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert not form.is_valid()
        assert "volunteers" in form.errors

    def test_form_without_unit_has_empty_querysets(self):
        """
        When no unit is passed (unit=None), all three resource querysets must
        remain empty (.none()).  This guards against accidentally showing all
        resources system-wide if the view omits the unit kwarg.
        """
        form = IncidentDispatchForm(unit=None)
        assert form.fields["volunteers"].queryset.count() == 0
        assert form.fields["equipment_items"].queryset.count() == 0
        assert form.fields["vehicles"].queryset.count() == 0

    def test_valid_form_with_all_resources(self):
        """
        Selecting volunteers + equipment + vehicles all from the same unit
        must pass validation end-to-end and surface the correct objects in
        cleaned_data.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        equipment = EquipmentFactory.create(unit=unit)
        vehicle = VehicleFactory.create(unit=unit)
        data = {
            "title": "Building collapse",
            "incident_type": "COLLAPSE",
            "volunteers": [volunteer.pk],
            "equipment_items": [equipment.pk],
            "vehicles": [vehicle.pk],
        }
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        assert volunteer in form.cleaned_data["volunteers"]
        assert equipment in form.cleaned_data["equipment_items"]
        assert vehicle in form.cleaned_data["vehicles"]


class TestIncidentReportForm:
    """
    Tests for IncidentReportForm — the form used to file the post-incident
    detailed report.
    """

    def test_valid_report_form(self):
        """
        Submitting final_report text, a valid end_time, and a status value
        must result in a valid form with no errors.
        """
        incident = IncidentFactory.create()
        data = {
            "final_report": "Full narrative of response operations.",
            "end_time": "2026-03-27T14:30",
            "status": IncidentStatus.CLOSED,
        }
        form = IncidentReportForm(data=data, instance=incident)
        assert form.is_valid(), form.errors

    def test_final_report_preserved_in_cleaned_data(self):
        """
        The text entered in final_report must come back unchanged in
        cleaned_data after successful validation.
        """
        incident = IncidentFactory.create()
        report_text = "Detailed narrative: flood affected 50 households."
        data = {
            "final_report": report_text,
            "end_time": "2026-03-27T14:30",
            "status": IncidentStatus.CLOSED,
        }
        form = IncidentReportForm(data=data, instance=incident)
        assert form.is_valid()
        assert form.cleaned_data["final_report"] == report_text

    def test_empty_final_report_is_allowed(self):
        """
        final_report has blank=True on the model, so leaving it empty must
        NOT cause a validation error — a partial save is permitted.
        """
        incident = IncidentFactory.create()
        data = {
            "final_report": "",
            "end_time": "2026-03-27T14:30",
            "status": IncidentStatus.OPEN,
        }
        form = IncidentReportForm(data=data, instance=incident)
        assert form.is_valid(), form.errors
