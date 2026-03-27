"""
Tests for equipment/views.py

EquipmentListView  — paginated table with category / status / unit / name filters.
EquipmentDetailView— single equipment item detail page.

We import shared factories from the incidents tests package because that is where
all model factories for this project are centralised.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import EquipmentFactory
from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory

pytestmark = pytest.mark.django_db

LIST_URL = reverse("equipment:equipment-list")


def _login(user) -> Client:
    """Return a logged-in Django test Client for the given user."""
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentListView:

    def test_unauthenticated_redirects(self):
        """
        LoginRequiredMixin must redirect anonymous visitors to the login page
        before rendering the equipment list.
        """
        response = Client().get(LIST_URL)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the equipment list (HTTP 200)."""
        uic = UICUserFactory.create()
        response = _login(uic).get(LIST_URL)
        assert response.status_code == 200

    def test_equipment_name_appears_in_list(self):
        """
        Equipment saved to the database must appear in the rendered HTML
        so users can actually see their inventory.
        """
        uic = UICUserFactory.create()
        equip = EquipmentFactory.create(name="Life Jacket XL")
        response = _login(uic).get(LIST_URL)
        assert "Life Jacket XL" in response.content.decode()

    def test_filter_by_status(self):
        """
        ?status=OK must show only functional items and hide items with other
        statuses (e.g. REPAIR / DISPOSED).
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        functional = EquipmentFactory.create(unit=unit, name="Rope Ladder", status="OK")
        broken = EquipmentFactory.create(unit=unit, name="Broken Hose", status="REPAIR")
        response = _login(uic).get(LIST_URL, {"status": "OK"})
        content = response.content.decode()
        assert functional.name in content
        assert broken.name not in content

    def test_filter_by_category(self):
        """
        ?category=FIRE must show only fire-fighting equipment, not rescue or
        medical items.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        fire_eq = EquipmentFactory.create(unit=unit, name="Fire Hose", category="FIRE")
        rescue_eq = EquipmentFactory.create(unit=unit, name="Stretcher", category="RESCUE")
        response = _login(uic).get(LIST_URL, {"category": "FIRE"})
        content = response.content.decode()
        assert fire_eq.name in content
        assert rescue_eq.name not in content

    def test_filter_by_unit(self):
        """
        ?unit=<pk> must return only equipment assigned to that unit.
        Equipment from other units must not appear in the filtered result.
        """
        uic = UICUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        eq_a = EquipmentFactory.create(unit=unit_a, name="Torch Unit A")
        eq_b = EquipmentFactory.create(unit=unit_b, name="Radio Unit B")
        response = _login(uic).get(LIST_URL, {"unit": unit_a.pk})
        content = response.content.decode()
        assert eq_a.name in content
        assert eq_b.name not in content

    def test_search_by_name(self):
        """
        ?q=<term> must perform a case-insensitive substring search on the
        equipment name column.
        """
        uic = UICUserFactory.create()
        unit = UnitFactory.create()
        EquipmentFactory.create(unit=unit, name="Oxygen Cylinder")
        EquipmentFactory.create(unit=unit, name="First Aid Kit")
        response = _login(uic).get(LIST_URL, {"q": "oxygen"})
        content = response.content.decode()
        assert "Oxygen Cylinder" in content
        assert "First Aid Kit" not in content

    def test_context_contains_filter_choices(self):
        """
        The template depends on category_choices and status_choices being
        present in the context to render the filter dropdowns.
        """
        uic = UICUserFactory.create()
        response = _login(uic).get(LIST_URL)
        assert "category_choices" in response.context
        assert "status_choices" in response.context
        assert "units" in response.context


# ─────────────────────────────────────────────────────────────────────────────
# DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view an equipment detail page."""
        uic = UICUserFactory.create()
        equip = EquipmentFactory.create()
        url = reverse("equipment:equipment-detail", kwargs={"pk": equip.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_equipment_name_in_detail_page(self):
        """The equipment's name must appear on its own detail page."""
        uic = UICUserFactory.create()
        equip = EquipmentFactory.create(name="Rescue Rope 50m")
        url = reverse("equipment:equipment-detail", kwargs={"pk": equip.pk})
        response = _login(uic).get(url)
        assert "Rescue Rope 50m" in response.content.decode()

    def test_nonexistent_pk_returns_404(self):
        """Requesting a non-existent equipment PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("equipment:equipment-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404
