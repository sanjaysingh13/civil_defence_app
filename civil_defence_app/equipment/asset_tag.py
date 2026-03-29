"""
Helpers for departmental asset tags (Unique ID) on Equipment.

The bulk import command ``seed_equipment`` assigns identifiers like::

    ALIPURDUAR-GEN-SET-001
    │           │       └── serial within (unit, type code), zero-padded to 3 digits
    │           └── short code for the equipment *kind* (from EQUIP_META)
    └── unit slug in UPPER CASE

Admin “Add equipment” reuses the same pattern so new rows stay consistent with
seeded data.  We resolve the middle segment from the procurement register map
when the EquipmentType name matches a known register label; otherwise we
derive a safe code from the type name (slug-style, uppercased).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.text import slugify

if TYPE_CHECKING:
    from civil_defence_app.equipment.models import EquipmentType
    from civil_defence_app.personnel.models import Unit


def equipment_type_asset_code(equipment_type: EquipmentType) -> str:
    """
    Return the short token used inside ``unique_id`` between unit slug and serial.

    * If the type's ``name`` matches a key in ``seed_equipment.EQUIP_META``,
      we use the same code the Excel import uses (e.g. ``GEN-SET``).
    * Otherwise we build a compact code from ``slugify(name)`` so new types
      created only in Admin still get stable, URL-safe segments.

    The import is done inside the function so loading ``seed_equipment`` (a
    large module) only happens when this helper runs, not on every Django
    startup.
    """
    from civil_defence_app.equipment.management.commands.seed_equipment import (
        EQUIP_META,
    )

    key = equipment_type.name.strip()
    if key in EQUIP_META:
        return EQUIP_META[key][0]

    # slugify turns arbitrary Unicode titles into ASCII hyphenated words; we
    # uppercase to match the style of seeded codes (e.g. GEN-SET).
    base = slugify(key).upper()
    if not base:
        return f"TYPE-{equipment_type.pk or 'NEW'}"

    # Keep the tag readable and within a reasonable length for CharField(100).
    if len(base) > 24:
        base = base[:24].rstrip("-")
    return base


def max_serial_suffix_for_unit_type(
    *,
    unit: Unit,
    equipment_type: EquipmentType,
) -> int:
    """
    Scan existing Equipment rows for this unit + equipment_type and return the
    largest numeric suffix parsed from the end of ``unique_id``.

    We only consider rows that already point at this ``equipment_type`` so
    unrelated legacy strings in the same unit do not affect the counter.
    The suffix is the part after the final hyphen, if it is all digits
    (e.g. ``…-001`` → 1, ``…-042`` → 42).

    If nothing matches, return ``0`` so the caller can propose ``…-001``.
    """
    # Import here to avoid circular imports when personnel loads equipment.
    from civil_defence_app.equipment.models import Equipment

    max_sl = 0
    qs = Equipment.objects.filter(unit=unit, equipment_type=equipment_type).values_list(
        "unique_id",
        flat=True,
    )
    for uid in qs:
        if not uid or "-" not in uid:
            continue
        tail = uid.rsplit("-", 1)[-1]
        if tail.isdigit():
            max_sl = max(max_sl, int(tail))
    return max_sl


def build_next_unique_id(
    *,
    unit: Unit,
    equipment_type: EquipmentType,
    width: int = 3,
) -> str:
    """
    Build the next ``unique_id`` string: ``{UNIT_SLUG_UPPER}-{CODE}-{NNN}``.

    ``width`` defaults to 3 to match ``seed_equipment`` (001, 002, …).
    """
    unit_part = unit.slug.upper()
    code = equipment_type_asset_code(equipment_type)
    next_sl = (
        max_serial_suffix_for_unit_type(unit=unit, equipment_type=equipment_type) + 1
    )
    serial = str(next_sl).zfill(width)
    return f"{unit_part}-{code}-{serial}"
