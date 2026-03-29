"""
Tests for ``equipment.asset_tag`` — asset code resolution and next serial logic.
"""

from __future__ import annotations

import pytest

from civil_defence_app.equipment.asset_tag import build_next_unique_id
from civil_defence_app.equipment.asset_tag import equipment_type_asset_code
from civil_defence_app.equipment.asset_tag import max_serial_suffix_for_unit_type
from civil_defence_app.equipment.models import Equipment
from civil_defence_app.equipment.models import EquipmentCategory
from civil_defence_app.equipment.models import EquipmentType
from civil_defence_app.incidents.tests.factories import UnitFactory

pytestmark = pytest.mark.django_db


def test_equipment_type_asset_code_uses_register_map_for_known_name():
    """
    Names that appear in the Excel import map must reuse the same short code
    as ``seed_equipment`` so admin-generated IDs stay consistent.
    """
    et = EquipmentType.objects.create(
        name="Portable Generator Set",
        category=EquipmentCategory.OTHER,
    )
    assert equipment_type_asset_code(et) == "GEN-SET"


def test_equipment_type_asset_code_slugifies_unknown_name():
    """
    Types created only in Admin (not in the procurement XLSX) still get a
    deterministic code derived from the title.
    """
    et = EquipmentType.objects.create(
        name="Custom Rescue Widget™",
        category=EquipmentCategory.RESCUE,
    )
    code = equipment_type_asset_code(et)
    assert code
    assert code == code.upper()


def test_next_unique_id_starts_at_001():
    """
    With no existing rows for (unit, type), the first tag ends in -001.
    """
    unit = UnitFactory()
    et = EquipmentType.objects.create(name="Portable Generator Set")
    uid = build_next_unique_id(unit=unit, equipment_type=et)
    assert uid == f"{unit.slug.upper()}-GEN-SET-001"


def test_next_unique_id_increments_max_suffix():
    """
    The counter scans existing Equipment for the same unit+type and picks max+1.
    """
    unit = UnitFactory()
    et = EquipmentType.objects.create(name="Portable Generator Set")
    Equipment.objects.create(
        unit=unit,
        equipment_type=et,
        name=et.name,
        unique_id=f"{unit.slug.upper()}-GEN-SET-002",
        category=et.category,
    )
    Equipment.objects.create(
        unit=unit,
        equipment_type=et,
        name=et.name,
        unique_id=f"{unit.slug.upper()}-GEN-SET-007",
        category=et.category,
    )
    uid = build_next_unique_id(unit=unit, equipment_type=et)
    assert uid.endswith("-008")


def test_max_serial_ignores_non_numeric_suffix():
    """
    Rows whose unique_id does not end in digits are ignored for the max scan.
    """
    unit = UnitFactory()
    et = EquipmentType.objects.create(name="Portable Generator Set")
    Equipment.objects.create(
        unit=unit,
        equipment_type=et,
        name=et.name,
        unique_id=f"{unit.slug.upper()}-GEN-SET-legacy",
        category=et.category,
    )
    assert max_serial_suffix_for_unit_type(unit=unit, equipment_type=et) == 0
