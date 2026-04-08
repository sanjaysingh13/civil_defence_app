"""Tests for Admin web UI: EquipmentCreateView at /equipment/add/."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.equipment.models import Equipment
from civil_defence_app.equipment.models import EquipmentCategory
from civil_defence_app.equipment.models import EquipmentStatus
from civil_defence_app.equipment.models import EquipmentType
from civil_defence_app.incidents.tests.factories import AdminUserFactory
from civil_defence_app.personnel.models import Unit
from civil_defence_app.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _login(user) -> Client:
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


def _create_url() -> str:
    return reverse("equipment:equipment-create")


@pytest.fixture
def alipurduar_unit() -> Unit:
    return Unit.objects.create(name="ALIPURDUAR", slug="alipurduar")


@pytest.fixture
def mega_phone_type() -> EquipmentType:
    return EquipmentType.objects.create(
        name="Mega Phone with Sling",
        category=EquipmentCategory.COMM,
        description="Hand-held megaphone with carry strap.",
        scheduled_maintenance_periodicity=1,
    )


class TestEquipmentCreateAccess:
    def test_volunteer_get_forbidden(self, alipurduar_unit, mega_phone_type):
        user = UserFactory.create(password="testpass123")
        c = _login(user)
        r = c.get(_create_url())
        assert r.status_code == 403

    def test_volunteer_post_forbidden(self, alipurduar_unit, mega_phone_type):
        user = UserFactory.create(password="testpass123")
        c = _login(user)
        r = c.post(
            _create_url(),
            {
                "unit": alipurduar_unit.pk,
                "equipment_type": mega_phone_type.pk,
                "quantity": 1,
                "notes": "",
            },
        )
        assert r.status_code == 403
        assert Equipment.objects.count() == 0


class TestEquipmentCreateAssetTag:
    def test_first_item_gets_001(self, alipurduar_unit, mega_phone_type):
        admin = AdminUserFactory.create()
        c = _login(admin)
        r = c.post(
            _create_url(),
            {
                "unit": alipurduar_unit.pk,
                "equipment_type": mega_phone_type.pk,
                "quantity": 1,
                "notes": "",
            },
        )
        assert r.status_code == 302
        eq = Equipment.objects.get()
        assert eq.unique_id == "ALIPURDUAR-MEGA-PHON-001"
        assert eq.is_functional is True
        assert eq.status == EquipmentStatus.FUNCTIONAL
        assert eq.category == EquipmentCategory.COMM
        assert eq.name == "Mega Phone with Sling"

    def test_second_item_gets_002(self, alipurduar_unit, mega_phone_type):
        Equipment.objects.create(
            unit=alipurduar_unit,
            equipment_type=mega_phone_type,
            name="Mega Phone with Sling",
            unique_id="ALIPURDUAR-MEGA-PHON-001",
            category=EquipmentCategory.COMM,
            quantity=1,
            status=EquipmentStatus.FUNCTIONAL,
            is_functional=True,
        )
        admin = AdminUserFactory.create()
        c = _login(admin)
        r = c.post(
            _create_url(),
            {
                "unit": alipurduar_unit.pk,
                "equipment_type": mega_phone_type.pk,
                "quantity": 1,
                "notes": "",
            },
        )
        assert r.status_code == 302
        newest = Equipment.objects.order_by("-pk").first()
        assert newest is not None
        assert newest.unique_id == "ALIPURDUAR-MEGA-PHON-002"
