"""
Tests for incidents/models.py

What we verify:
  - generate_incident_number() returns the correct UNIT-YEAR-NNN format.
  - Serial numbers increment correctly when multiple incidents exist for the
    same unit and year.
  - The Incident.save() override auto-populates incident_number on first save.
  - Saving an already-numbered incident leaves the number unchanged (idempotent).
  - __str__() includes the incident number.
"""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from civil_defence_app.incidents.models import Incident
from civil_defence_app.incidents.models import IncidentStatus

from .factories import IncidentFactory
from .factories import UICUserFactory
from .factories import UnitFactory

pytestmark = pytest.mark.django_db


class TestGenerateIncidentNumber:
    """
    Unit tests for Incident.generate_incident_number() classmethod.

    This classmethod builds the next serial number for a given unit + year
    by counting how many incidents already have a number starting with the
    same prefix (e.g. "ALIPURDUAR-2026-").
    """

    def test_first_incident_gets_001(self):
        """
        When no prior incidents exist for a unit+year, the first call must
        return serial 001 — i.e. the format is SLUG-YEAR-001.
        """
        unit = UnitFactory.create()
        number = Incident.generate_incident_number(unit)
        year = timezone.now().year
        assert number == f"{unit.slug.upper()}-{year}-001"

    def test_sequential_numbering(self):
        """
        Each subsequent incident for the same unit+year must increment the
        serial by 1.  After 2 incidents the next call returns 003.
        """
        unit = UnitFactory.create()
        IncidentFactory.create(unit=unit)
        IncidentFactory.create(unit=unit)
        number = Incident.generate_incident_number(unit)
        year = timezone.now().year
        assert number == f"{unit.slug.upper()}-{year}-003"

    def test_different_units_are_independent(self):
        """
        Incidents for unit A must not affect the serial counter for unit B.
        Each unit always starts from 001 independently.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        IncidentFactory.create(unit=unit_a)
        IncidentFactory.create(unit=unit_a)
        number_b = Incident.generate_incident_number(unit_b)
        year = timezone.now().year
        assert number_b == f"{unit_b.slug.upper()}-{year}-001"

    def test_reference_time_year_is_used(self):
        """
        When reference_time is supplied, the year from that datetime must be
        used instead of the current year.  Useful for back-dating incidents.
        """
        unit = UnitFactory.create()
        past_time = datetime.datetime(2020, 6, 15, 12, 0, tzinfo=datetime.timezone.utc)
        number = Incident.generate_incident_number(unit, reference_time=past_time)
        assert "-2020-" in number
        assert number.endswith("-001")

    def test_slug_is_uppercased_in_number(self):
        """
        Unit slugs are stored in lowercase (e.g. "alipurduar") but the
        incident number must display them uppercased ("ALIPURDUAR-2026-001").
        """
        unit = UnitFactory.create(name="ALIPURDUAR", slug="alipurduar")
        number = Incident.generate_incident_number(unit)
        assert number.startswith("ALIPURDUAR-")


class TestIncidentSave:
    """
    Integration tests for Incident.save() — the override that auto-populates
    incident_number the first time a new incident is written to the database.
    """

    def test_incident_number_auto_generated_on_create(self):
        """
        After saving a brand-new Incident, incident_number must NOT be blank.
        Django calls our overridden save() which calls generate_incident_number().
        """
        unit = UnitFactory.create()
        incident = IncidentFactory.create(unit=unit)
        assert incident.incident_number is not None
        assert incident.incident_number != ""

    def test_incident_number_format(self):
        """
        The auto-generated number must match the pattern SLUG-YEAR-NNN,
        where SLUG is the uppercased unit slug, YEAR is 4 digits, and NNN
        is a zero-padded 3-digit serial.
        """
        unit = UnitFactory.create(name="BANKURA", slug="bankura")
        incident = IncidentFactory.create(unit=unit)
        year = timezone.now().year
        assert incident.incident_number == f"BANKURA-{year}-001"

    def test_incident_number_not_overwritten_on_update(self):
        """
        If an incident already has an incident_number, save() must NOT
        replace it.  This preserves the original serial even after edits.
        """
        incident = IncidentFactory.create()
        original_number = incident.incident_number
        incident.title = "Updated title"
        incident.save()
        incident.refresh_from_db()
        assert incident.incident_number == original_number

    def test_two_incidents_same_unit_get_different_numbers(self):
        """
        Two incidents for the same unit must receive distinct, sequential
        numbers — not the same number twice.
        """
        unit = UnitFactory.create()
        first = IncidentFactory.create(unit=unit)
        second = IncidentFactory.create(unit=unit)
        assert first.incident_number != second.incident_number
        year = timezone.now().year
        assert first.incident_number == f"{unit.slug.upper()}-{year}-001"
        assert second.incident_number == f"{unit.slug.upper()}-{year}-002"


class TestIncidentStr:
    """Tests for Incident.__str__()."""

    def test_str_includes_incident_number(self):
        """
        __str__ must include the incident_number inside square brackets,
        followed by the title — format: "[NUMBER] title".
        """
        incident = IncidentFactory.create()
        s = str(incident)
        assert incident.incident_number in s
        assert incident.title in s

    def test_str_with_no_number_uses_dash(self):
        """
        If incident_number is somehow None (e.g. no unit_id set), __str__
        must degrade gracefully using "—" instead of crashing.
        """
        incident = Incident(title="Test", status=IncidentStatus.OPEN)
        assert "—" in str(incident)
