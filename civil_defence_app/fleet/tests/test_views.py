"""
Tests for fleet/views.py

VehicleListView   — paginated table with vehicle-type / status / unit / reg-no filters.
VehicleDetailView — single vehicle detail page.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VehicleFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("fleet:vehicle-list")


def _login(user) -> Client:
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestVehicleListView:

    def test_unauthenticated_redirects(self):
        """Anonymous visitors must be redirected to the login page."""
        response = Client().get(LIST_URL)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the vehicle list."""
        uic = UICUserFactory.create()
        response = _login(uic).get(LIST_URL)
        assert response.status_code == 200

    def test_vehicle_reg_appears_in_list(self):
        """
        A vehicle's registration number must appear in the rendered HTML
        so dispatchers can identify the correct vehicle.
        """
        uic = UICUserFactory.create()
        vehicle = VehicleFactory.create(registration_no="WB01ZZ0001")
        response = _login(uic).get(LIST_URL)
        assert "WB01ZZ0001" in response.content.decode()

    def test_filter_by_status(self):
        """
        ?status=AVAILABLE must show only available vehicles and hide deployed
        or maintenance-status vehicles.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        avail = VehicleFactory.create(unit=unit, registration_no="WB01AA0001", status="AVAILABLE")
        deployed = VehicleFactory.create(unit=unit, registration_no="WB01BB0001", status="DEPLOYED")
        response = _login(uic).get(LIST_URL, {"status": "AVAILABLE"})
        content = response.content.decode()
        assert avail.registration_no in content
        assert deployed.registration_no not in content

    def test_filter_by_vehicle_type(self):
        """
        ?type=AMBULANCE must show only ambulances, not jeeps or boats.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        ambulance = VehicleFactory.create(unit=unit, registration_no="WB01CC0001", vehicle_type="AMBULANCE")
        jeep = VehicleFactory.create(unit=unit, registration_no="WB01DD0001", vehicle_type="JEEP")
        response = _login(uic).get(LIST_URL, {"type": "AMBULANCE"})
        content = response.content.decode()
        assert ambulance.registration_no in content
        assert jeep.registration_no not in content

    def test_filter_by_unit(self):
        """
        ?unit=<pk> must return only vehicles assigned to that unit.
        """
        uic = UICUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        v_a = VehicleFactory.create(unit=unit_a, registration_no="WB01EE0001")
        v_b = VehicleFactory.create(unit=unit_b, registration_no="WB01FF0001")
        response = _login(uic).get(LIST_URL, {"unit": unit_a.pk})
        content = response.content.decode()
        assert v_a.registration_no in content
        assert v_b.registration_no not in content

    def test_search_by_registration_number(self):
        """
        ?q=<term> performs a case-insensitive substring match on the
        registration number column.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        VehicleFactory.create(unit=unit, registration_no="WB01GG0099")
        VehicleFactory.create(unit=unit, registration_no="WB02HH0001")
        response = _login(uic).get(LIST_URL, {"q": "GG"})
        content = response.content.decode()
        assert "WB01GG0099" in content
        assert "WB02HH0001" not in content

    def test_context_contains_filter_choices(self):
        """
        type_choices, status_choices, and units must be in context for the
        filter dropdowns to render correctly.
        """
        uic = UICUserFactory.create()
        response = _login(uic).get(LIST_URL)
        assert "type_choices" in response.context
        assert "status_choices" in response.context
        assert "units" in response.context


# ─────────────────────────────────────────────────────────────────────────────
# DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestVehicleDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view a vehicle detail page."""
        uic = UICUserFactory.create()
        vehicle = VehicleFactory.create()
        url = reverse("fleet:vehicle-detail", kwargs={"pk": vehicle.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_registration_number_in_detail(self):
        """The vehicle's registration number must appear on its detail page."""
        uic = UICUserFactory.create()
        vehicle = VehicleFactory.create(registration_no="WB99XY9999")
        url = reverse("fleet:vehicle-detail", kwargs={"pk": vehicle.pk})
        response = _login(uic).get(url)
        assert "WB99XY9999" in response.content.decode()

    def test_nonexistent_pk_returns_404(self):
        """Non-existent vehicle PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("fleet:vehicle-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404
