"""
Tests for incidents/forms.py

What we verify:
  - IncidentDispatchForm: at least one assignment_volunteer + assignment_role pair is required.
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
from civil_defence_app.incidents.models import IncidentAssignmentRole
from civil_defence_app.incidents.models import IncidentStatus

from .factories import EquipmentFactory
from .factories import IncidentFactory
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

    def _minimal_post_data(
        self,
        volunteer_pks: list[int],
        roles: list[str] | None = None,
    ) -> dict:
        """
        Helper that returns the minimum valid POST data for the dispatch form.
        Parallel lists ``assignment_volunteer`` and ``assignment_role`` mirror
        the dispatch template (one role per volunteer).
        """
        if roles is None:
            roles = [IncidentAssignmentRole.FIREFIGHTER for _ in volunteer_pks]
        return {
            "title": "Flash flood near river bank",
            "incident_type": "FLOOD",
            "assignment_volunteer": [str(pk) for pk in volunteer_pks],
            "assignment_role": list(roles),
        }

    def test_volunteers_required_when_empty(self):
        """
        Submitting the form without any assignment pair must fail validation
        (clean() raises a non-field error).
        """
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_pks=[])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert not form.is_valid()
        assert "__all__" in form.errors

    def test_valid_form_with_volunteers_only(self):
        """
        Selecting at least one volunteer (no equipment, no vehicles) must
        pass validation because equipment_items and vehicles are optional.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_pks=[volunteer.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        pairs = form.cleaned_data["dispatch_assignments"]
        assert len(pairs) == 1
        assert pairs[0][0] == volunteer
        assert pairs[0][1] == IncidentAssignmentRole.FIREFIGHTER

    def test_equipment_is_optional(self):
        """
        Omitting equipment_items from the POST data must NOT cause a
        validation error — the field has required=False.
        """
        unit = UnitFactory.create()
        volunteer = VolunteerFactory.create(unit=unit)
        EquipmentFactory.create(unit=unit)
        data = self._minimal_post_data(volunteer_pks=[volunteer.pk])
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
        data = self._minimal_post_data(volunteer_pks=[volunteer.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        assert list(form.cleaned_data["vehicles"]) == []

    def test_volunteers_queryset_scoped_to_unit(self):
        """
        Volunteers from another unit must be rejected in clean() even if
        their PKs are posted.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        volunteer_b = VolunteerFactory.create(unit=unit_b)
        VolunteerFactory.create(unit=unit_a)
        data = self._minimal_post_data(volunteer_pks=[volunteer_b.pk])
        form = IncidentDispatchForm(data=data, unit=unit_a)
        assert not form.is_valid()
        assert "__all__" in form.errors

    def test_inactive_volunteers_excluded(self):
        """
        Inactive volunteers (is_active=False) must not be deployable.
        """
        unit = UnitFactory.create()
        inactive = VolunteerFactory.create(unit=unit, is_active=False)
        data = self._minimal_post_data(volunteer_pks=[inactive.pk])
        form = IncidentDispatchForm(data=data, unit=unit)
        assert not form.is_valid()
        assert "__all__" in form.errors

    def test_form_without_unit_has_empty_querysets(self):
        """
        When no unit is passed (unit=None), equipment and vehicle querysets
        stay empty; volunteers_for_dispatch() is empty.
        """
        form = IncidentDispatchForm(unit=None)
        assert form.volunteers_for_dispatch().count() == 0
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
            "assignment_volunteer": [str(volunteer.pk)],
            "assignment_role": [IncidentAssignmentRole.CUTTER],
            "equipment_items": [equipment.pk],
            "vehicles": [vehicle.pk],
        }
        form = IncidentDispatchForm(data=data, unit=unit)
        assert form.is_valid(), form.errors
        assert form.cleaned_data["dispatch_assignments"] == [
            (volunteer, IncidentAssignmentRole.CUTTER),
        ]
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
