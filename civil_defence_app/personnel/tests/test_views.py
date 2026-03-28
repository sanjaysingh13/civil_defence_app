"""
Tests for personnel/views.py

Four views:
  UnitListView       — table of all units with annotated volunteer counts.
  UnitDetailView     — detail page for one unit with its active volunteers.
  VolunteerListView  — paginated, searchable list of all active volunteers.
  VolunteerDetailView— single volunteer detail card.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from civil_defence_app.incidents.models import IncidentAssignment
from civil_defence_app.incidents.tests.factories import AdminUserFactory
from civil_defence_app.incidents.tests.factories import IncidentFactory
from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VolunteerFactory
from civil_defence_app.personnel.models import OfficeDutyPeriod

pytestmark = pytest.mark.django_db


def _login(user) -> Client:
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# UNIT LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitListView:
    url = reverse("personnel:unit-list")

    def test_unauthenticated_redirects(self):
        """Anonymous visitors must be redirected to login."""
        response = Client().get(self.url)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the unit list."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert response.status_code == 200

    def test_unit_name_appears_in_list(self):
        """Unit names saved in the database must appear in the rendered HTML."""
        uic = UICUserFactory.create()
        unit = UnitFactory.create(name="DARJEELING")
        response = _login(uic).get(self.url)
        assert "DARJEELING" in response.content.decode()

    def test_volunteer_count_annotation(self):
        """
        Each unit row is annotated with `volunteer_count` (active volunteers
        only).  We verify the annotation is non-zero when volunteers exist.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit, is_active=True)
        VolunteerFactory.create(unit=unit, is_active=True)
        VolunteerFactory.create(unit=unit, is_active=False)
        response = _login(uic).get(self.url)
        assert response.status_code == 200
        units_qs = response.context["units"]
        this_unit = next(u for u in units_qs if u.pk == unit.pk)
        assert this_unit.volunteer_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# UNIT DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view a unit detail page."""
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        url = reverse("personnel:unit-detail", kwargs={"pk": unit.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_unit_name_in_detail(self):
        """The unit name must appear on the detail page."""
        uic = UICUserFactory.create()
        unit = UnitFactory.create(name="COOCH BEHAR")
        url = reverse("personnel:unit-detail", kwargs={"pk": unit.pk})
        response = _login(uic).get(url)
        assert "COOCH BEHAR" in response.content.decode()

    def test_active_volunteers_shown(self):
        """
        Active volunteers belonging to the unit must appear on the detail page.
        Inactive volunteers must be excluded from the context queryset.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        active = VolunteerFactory.create(unit=unit, name="Active Volunteer", is_active=True)
        VolunteerFactory.create(unit=unit, name="Inactive Volunteer", is_active=False)
        url = reverse("personnel:unit-detail", kwargs={"pk": unit.pk})
        response = _login(uic).get(url)
        context_volunteers = list(response.context["volunteers"])
        assert active in context_volunteers
        assert all(v.is_active for v in context_volunteers)

    def test_nonexistent_unit_returns_404(self):
        """A non-existent unit PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("personnel:unit-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestVolunteerListView:
    url = reverse("personnel:volunteer-list")

    def test_unauthenticated_redirects(self):
        """Anonymous visitors must be redirected to login."""
        response = Client().get(self.url)
        assert response.status_code == 302

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the volunteer list."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert response.status_code == 200

    def test_active_volunteer_appears(self):
        """Active volunteers must appear in the list."""
        uic = UICUserFactory.create()
        vol = VolunteerFactory.create(name="Ramesh Kumar", is_active=True)
        response = _login(uic).get(self.url)
        assert "Ramesh Kumar" in response.content.decode()

    def test_inactive_volunteer_excluded(self):
        """
        The view filters is_active=True, so inactive volunteers must NOT
        appear in the default list even if they exist in the database.
        """
        uic = UICUserFactory.create()
        VolunteerFactory.create(name="Deactivated Person", is_active=False)
        response = _login(uic).get(self.url)
        assert "Deactivated Person" not in response.content.decode()

    def test_filter_by_unit(self):
        """
        ?unit=<pk> must show only volunteers from that unit.
        Volunteers from other units must not appear.
        """
        uic = UICUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        vol_a = VolunteerFactory.create(unit=unit_a, name="Vol from A")
        VolunteerFactory.create(unit=unit_b, name="Vol from B")
        response = _login(uic).get(self.url, {"unit": unit_a.pk})
        content = response.content.decode()
        assert vol_a.name in content
        assert "Vol from B" not in content

    def test_filter_by_gender(self):
        """
        ?gender=F must show only female volunteers; male volunteers must be
        excluded from the filtered result.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit, name="Male Vol", gender="M")
        female = VolunteerFactory.create(unit=unit, name="Female Vol", gender="F")
        response = _login(uic).get(self.url, {"gender": "F"})
        content = response.content.decode()
        assert female.name in content
        assert "Male Vol" not in content

    def test_search_by_name(self):
        """
        ?q=<term> performs a case-insensitive substring search on the
        volunteer name column.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit, name="Sunita Devi")
        VolunteerFactory.create(unit=unit, name="Rajesh Gupta")
        response = _login(uic).get(self.url, {"q": "sunita"})
        content = response.content.decode()
        assert "Sunita Devi" in content
        assert "Rajesh Gupta" not in content

    def test_context_has_units_for_filter_dropdown(self):
        """
        The template needs `units` in the context to render the unit filter
        dropdown — verify it's present and contains Unit objects.
        """
        uic = UICUserFactory.create()
        UnitFactory.create()
        response = _login(uic).get(self.url)
        assert "units" in response.context
        assert response.context["units"].count() >= 1


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestVolunteerDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view a volunteer's detail card."""
        uic = UICUserFactory.create()
        vol = VolunteerFactory.create()
        url = reverse("personnel:volunteer-detail", kwargs={"pk": vol.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_volunteer_name_in_detail(self):
        """The volunteer's name must appear on the detail page."""
        uic = UICUserFactory.create()
        vol = VolunteerFactory.create(name="Priya Sharma")
        url = reverse("personnel:volunteer-detail", kwargs={"pk": vol.pk})
        response = _login(uic).get(url)
        assert "Priya Sharma" in response.content.decode()

    def test_nonexistent_volunteer_returns_404(self):
        """Non-existent volunteer PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("personnel:volunteer-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404

    def test_service_log_shows_incident_deployment(self):
        """
        Incident assignments appear in the service log section with the incident title.
        """
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit)
        inc = IncidentFactory.create(unit=unit, title="Service Log Flood Event")
        inc.start_time = timezone.make_aware(datetime(2026, 1, 10, 8, 0, 0))
        inc.end_time = timezone.make_aware(datetime(2026, 1, 12, 18, 0, 0))
        inc.save()
        IncidentAssignment.objects.create(incident=inc, volunteer=vol)
        url = reverse("personnel:volunteer-detail", kwargs={"pk": vol.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200
        html = response.content.decode()
        assert "Service Log Flood Event" in html
        assert "Days served by calendar year" in html

    def test_context_can_log_office_duty_for_own_uic(self):
        """Owning UIC receives can_log_office_duty=True for volunteers in their unit."""
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit)
        url = reverse("personnel:volunteer-detail", kwargs={"pk": vol.pk})
        response = _login(uic).get(url)
        assert response.context["can_log_office_duty"] is True


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY POST ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


class TestVolunteerOfficeDutyViews:

    def test_admin_can_start_and_end_office_duty(self):
        """Admin may POST start then end; database reflects one closed period."""
        admin = AdminUserFactory.create()
        vol = VolunteerFactory.create()
        client = _login(admin)
        start_url = reverse("personnel:volunteer-office-duty-start", kwargs={"pk": vol.pk})
        today = timezone.localdate().isoformat()
        r1 = client.post(start_url, {"start_date": today})
        assert r1.status_code == 302
        open_row = OfficeDutyPeriod.objects.get(volunteer=vol)
        assert open_row.ended_at is None

        end_url = reverse("personnel:volunteer-office-duty-end", kwargs={"pk": vol.pk})
        r2 = client.post(end_url, {})
        assert r2.status_code == 302
        open_row.refresh_from_db()
        assert open_row.ended_at is not None

    def test_uic_wrong_unit_cannot_start_office_duty(self):
        """UIC for unit A cannot start office duty for a volunteer in unit B."""
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit_a)
        vol = VolunteerFactory.create(unit=unit_b)
        client = _login(uic)
        start_url = reverse("personnel:volunteer-office-duty-start", kwargs={"pk": vol.pk})
        response = client.post(
            start_url,
            {"start_date": timezone.localdate().isoformat()},
        )
        assert response.status_code == 302
        assert OfficeDutyPeriod.objects.filter(volunteer=vol).count() == 0

    def test_double_start_rejected_when_period_open(self):
        """Second start while a period is open does not create another row."""
        admin = AdminUserFactory.create()
        vol = VolunteerFactory.create()
        client = _login(admin)
        start_url = reverse("personnel:volunteer-office-duty-start", kwargs={"pk": vol.pk})
        d = timezone.localdate().isoformat()
        client.post(start_url, {"start_date": d})
        client.post(start_url, {"start_date": d})
        assert OfficeDutyPeriod.objects.filter(volunteer=vol).count() == 1
