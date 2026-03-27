"""
Tests for personnel/views.py

Four views:
  UnitListView       — table of all units with annotated volunteer counts.
  UnitDetailView     — detail page for one unit with its active volunteers.
  VolunteerListView  — paginated, searchable list of all active volunteers.
  VolunteerDetailView— single volunteer detail card.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VolunteerFactory

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
