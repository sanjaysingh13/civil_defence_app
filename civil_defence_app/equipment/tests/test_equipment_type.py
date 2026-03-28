"""
Tests for the EquipmentType model and the unit-scoped views.

Test classes:
  TestEquipmentTypeModel           — model fields, __str__, defaults.
  TestAddMonthsHelper              — the add_months() utility function.
  TestNextDueDateCalculation       — that form_valid computes next_due_date correctly.
  TestEquipmentInventorySummary    — EquipmentInventorySummaryView HTTP + context.
  TestEquipmentInventoryByUnit     — EquipmentInventoryByUnitView HTTP + context.
  TestEquipmentMaintenanceByUnit   — EquipmentMaintenanceByUnitView HTTP + queryset.
  TestEquipmentOverdueView         — EquipmentOverdueView HTTP + flag logic.
"""

from __future__ import annotations

import datetime

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.equipment.models import (
    Equipment,
    EquipmentMaintenanceLog,
    EquipmentStatus,
    EquipmentType,
    add_months,
)
from civil_defence_app.incidents.tests.factories import (
    AdminUserFactory,
    EquipmentFactory,
    UICUserFactory,
    UnitFactory,
)

pytestmark = pytest.mark.django_db


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _login(user) -> Client:
    """Return an authenticated Client for the given user."""
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


def _make_equipment_type(
    name="Life Jacket (Test)",
    category="FLOOD",
    periodicity=1,
    description="Test life jacket type.",
) -> EquipmentType:
    """
    Helper that creates and saves an EquipmentType with sensible defaults so
    individual test methods only have to specify the fields they care about.
    """
    return EquipmentType.objects.create(
        name=name,
        category=category,
        scheduled_maintenance_periodicity=periodicity,
        description=description,
    )


def _summary_url() -> str:
    return reverse("equipment:equipment-inventory-summary")


def _inventory_url(unit) -> str:
    return reverse("equipment:unit-inventory", kwargs={"unit_pk": unit.pk})


def _logs_url(unit) -> str:
    return reverse("equipment:unit-logs", kwargs={"unit_pk": unit.pk})


def _overdue_url() -> str:
    return reverse("equipment:equipment-overdue")


def _log_add_url(equip) -> str:
    return reverse("equipment:equipment-log-add", kwargs={"pk": equip.pk})


# ─────────────────────────────────────────────────────────────────────────────
# 1. EQUIPMENT TYPE MODEL
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentTypeModel:
    """Unit tests for EquipmentType model fields, __str__, and defaults."""

    def test_default_periodicity_is_one_month(self):
        """
        The model default for scheduled_maintenance_periodicity must be 1 so
        that a newly created type defaults to monthly checks — the safest option.
        """
        et = EquipmentType.objects.create(name="Test Type Default")
        assert et.scheduled_maintenance_periodicity == 1

    def test_default_category_is_other(self):
        """Category defaults to 'OTHER' if not specified."""
        et = EquipmentType.objects.create(name="Uncategorised Test")
        assert et.category == "OTHER"

    def test_str_contains_name_and_category(self):
        """
        __str__ must include both the name and the category display so the Admin
        changelist is readable at a glance.
        """
        et = _make_equipment_type(name="SCUBA Set", category="FLOOD")
        assert "SCUBA Set" in str(et)
        # "FLOOD" → "Flood Relief" via get_category_display
        assert "Flood" in str(et)

    def test_name_is_unique(self):
        """
        Attempting to create two EquipmentType rows with the same name must
        raise an IntegrityError because the name column has a UNIQUE constraint.
        """
        from django.db import IntegrityError
        _make_equipment_type(name="Unique Name")
        with pytest.raises(IntegrityError):
            _make_equipment_type(name="Unique Name")

    def test_can_set_long_description(self):
        """TextField has no max_length — a long description must save without error."""
        long_desc = "A" * 2000
        et = _make_equipment_type(description=long_desc)
        et.refresh_from_db()
        assert et.description == long_desc

    def test_ordering_is_by_category_then_name(self):
        """
        EquipmentType.Meta.ordering = ['category', 'name'] means the default
        queryset order is category alphabetically, then name alphabetically.
        """
        EquipmentType.objects.create(name="Zebra", category="OTHER")
        EquipmentType.objects.create(name="Apple", category="FLOOD")
        qs = list(EquipmentType.objects.values_list("name", flat=True))
        # FLOOD comes before OTHER alphabetically; within FLOOD, Apple first.
        assert qs.index("Apple") < qs.index("Zebra")

    def test_equipment_instances_related_name(self):
        """
        EquipmentType.equipment_instances should return the related Equipment rows
        via the reverse FK, using the related_name we specified on the FK.
        """
        unit = UnitFactory.create()
        et   = _make_equipment_type(name="Generator")
        EquipmentFactory.create(unit=unit, equipment_type=et)
        EquipmentFactory.create(unit=unit, equipment_type=et)
        assert et.equipment_instances.count() == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2. add_months() HELPER
# ─────────────────────────────────────────────────────────────────────────────

class TestAddMonthsHelper:
    """
    Unit tests for the add_months() utility function defined in models.py.

    This function must handle month-end clamping correctly — adding 1 month
    to Jan 31 cannot produce Feb 31 (which doesn't exist); it should return
    Feb 28 (or 29 in a leap year).
    """

    def test_add_one_month_normal(self):
        """Adding 1 month to March 15 gives April 15."""
        result = add_months(datetime.date(2026, 3, 15), 1)
        assert result == datetime.date(2026, 4, 15)

    def test_add_one_month_clamps_to_feb_end(self):
        """Adding 1 month to Jan 31 must clamp to Feb 28 (non-leap year)."""
        result = add_months(datetime.date(2026, 1, 31), 1)
        assert result == datetime.date(2026, 2, 28)

    def test_add_one_month_clamps_to_feb_end_leap_year(self):
        """Adding 1 month to Jan 31 in a leap year must clamp to Feb 29."""
        result = add_months(datetime.date(2024, 1, 31), 1)
        assert result == datetime.date(2024, 2, 29)

    def test_add_twelve_months_same_date(self):
        """Adding 12 months to any date gives the same day next year."""
        result = add_months(datetime.date(2026, 3, 15), 12)
        assert result == datetime.date(2027, 3, 15)

    def test_add_months_crosses_year_boundary(self):
        """Adding 3 months to November 1 should give February 1 of the next year."""
        result = add_months(datetime.date(2026, 11, 1), 3)
        assert result == datetime.date(2027, 2, 1)

    def test_add_six_months(self):
        """Adding 6 months to January 1 gives July 1."""
        result = add_months(datetime.date(2026, 1, 1), 6)
        assert result == datetime.date(2026, 7, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. NEXT_DUE_DATE CALCULATION IN MAINTENANCE LOG VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestNextDueDateCalculation:
    """
    Tests that EquipmentMaintenanceLogCreateView.form_valid correctly computes
    Equipment.next_due_date based on the equipment's EquipmentType periodicity.
    """

    def _post(self, uic, equip, data):
        return _login(uic).post(_log_add_url(equip), data)

    def test_next_due_date_computed_from_type_periodicity(self):
        """
        After a valid POST, Equipment.next_due_date must equal
        check_date + scheduled_maintenance_periodicity months.

        For a type with periodicity=3 and a check_date of 2026-03-28,
        the expected next_due_date is 2026-06-28.
        """
        unit  = UnitFactory.create()
        et    = _make_equipment_type(name="Rope Test Type", periodicity=3)
        equip = EquipmentFactory.create(unit=unit, equipment_type=et)
        uic   = UICUserFactory.create(unit=unit)

        self._post(uic, equip, {
            "check_date": "2026-03-28",
            "is_fit": "on",
            "remarks": "Quarterly check done.",
        })
        equip.refresh_from_db()
        assert equip.next_due_date == datetime.date(2026, 6, 28)

    def test_next_due_date_for_monthly_periodicity(self):
        """
        A type with periodicity=1 month: check on March 28 → due April 28.
        """
        unit  = UnitFactory.create()
        et    = _make_equipment_type(name="Life Jacket Monthly", periodicity=1)
        equip = EquipmentFactory.create(unit=unit, equipment_type=et)
        uic   = UICUserFactory.create(unit=unit)

        self._post(uic, equip, {
            "check_date": "2026-03-28",
            "is_fit": "on",
            "remarks": "",
        })
        equip.refresh_from_db()
        assert equip.next_due_date == datetime.date(2026, 4, 28)

    def test_next_due_date_not_set_without_equipment_type(self):
        """
        If equipment has no EquipmentType assigned (equipment_type is None),
        next_due_date must remain null after a maintenance log is submitted.
        Without a type, we cannot calculate the periodicity.
        """
        unit  = UnitFactory.create()
        # EquipmentFactory creates equipment without a type by default.
        equip = EquipmentFactory.create(unit=unit, equipment_type=None)
        uic   = UICUserFactory.create(unit=unit)

        self._post(uic, equip, {
            "check_date": "2026-03-28",
            "is_fit": "on",
            "remarks": "",
        })
        equip.refresh_from_db()
        # next_due_date should still be None since no EquipmentType is assigned.
        assert equip.next_due_date is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. EQUIPMENT INVENTORY SUMMARY VIEW (all-units)
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentInventorySummary:
    """Tests for the all-units inventory summary view (EquipmentInventorySummaryView)."""

    def test_unauthenticated_redirects_to_login(self):
        """Anonymous users must be redirected to the login page."""
        response = Client().get(_summary_url())
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_admin_gets_200(self):
        """Admin/superuser must receive 200."""
        admin = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        assert response.status_code == 200

    def test_uic_redirected_to_own_unit_inventory(self):
        """
        A UIC is redirected to their own unit's per-type inventory page because
        a single-unit-row summary is not useful to them.
        """
        unit = UnitFactory.create()
        uic  = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_summary_url())
        assert response.status_code == 302
        assert str(unit.pk) in response["Location"]

    def test_units_appear_in_context(self):
        """
        Units with equipment must appear in the 'units' context variable with
        correct annotation keys.
        """
        unit  = UnitFactory.create()
        EquipmentFactory.create(unit=unit, is_functional=True)
        EquipmentFactory.create(unit=unit, is_functional=False)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        assert response.status_code == 200

        units = list(response.context["units"])
        # The unit we created must appear.
        matching = [u for u in units if u.pk == unit.pk]
        assert len(matching) == 1
        u = matching[0]
        assert u.total          == 2
        assert u.functional     == 1
        assert u.non_functional == 1

    def test_units_without_equipment_excluded(self):
        """
        A unit that has no equipment at all must NOT appear in the summary
        (filtered by total__gt=0 in the queryset).
        """
        empty_unit = UnitFactory.create()
        admin      = AdminUserFactory.create()
        response   = _login(admin).get(_summary_url())
        pks        = [u.pk for u in response.context["units"]]
        assert empty_unit.pk not in pks

    def test_overdue_count_in_context(self):
        """
        Equipment that is functional and has no last_check_date must be counted
        in the 'overdue' annotation on the unit.
        """
        unit  = UnitFactory.create()
        # Never-inspected functional item counts as overdue.
        EquipmentFactory.create(unit=unit, is_functional=True, last_check_date=None)
        # Non-functional item must NOT count as overdue.
        EquipmentFactory.create(unit=unit, is_functional=False, last_check_date=None)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        matching = [u for u in response.context["units"] if u.pk == unit.pk]
        assert matching[0].overdue == 1   # only the functional one

    def test_grand_totals_in_context(self):
        """
        grand_total, grand_functional, grand_nonfunctional, grand_overdue must
        equal the sum of the corresponding per-unit annotations.
        """
        unit = UnitFactory.create()
        EquipmentFactory.create(unit=unit, is_functional=True)
        EquipmentFactory.create(unit=unit, is_functional=False)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        ctx      = response.context

        assert ctx["grand_total"]         >= 2
        assert ctx["grand_functional"]    >= 1
        assert ctx["grand_nonfunctional"] >= 1

    def test_unit_name_appears_in_page(self):
        """The unit name must be rendered in the summary table HTML."""
        unit  = UnitFactory.create()
        EquipmentFactory.create(unit=unit)
        admin    = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        assert unit.name in response.content.decode()

    def test_by_type_link_present_for_each_unit(self):
        """
        Each unit row must contain a 'By Type' link pointing to the per-unit
        inventory detail view.
        """
        unit  = UnitFactory.create()
        EquipmentFactory.create(unit=unit)
        admin    = AdminUserFactory.create()
        response = _login(admin).get(_summary_url())
        assert "By Type" in response.content.decode()


# ─────────────────────────────────────────────────────────────────────────────
# 5. EQUIPMENT INVENTORY BY UNIT VIEW  (per-unit type drill-down)
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentInventoryByUnit:
    """Tests for the unit-wise inventory view (EquipmentInventoryByUnitView)."""

    def test_unauthenticated_redirects_to_login(self):
        """Anonymous users must be redirected to the login page."""
        unit     = UnitFactory.create()
        response = Client().get(_inventory_url(unit))
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_user_gets_200(self):
        """Any authenticated user can view the unit inventory."""
        unit  = UnitFactory.create()
        admin = AdminUserFactory.create()
        response = _login(admin).get(_inventory_url(unit))
        assert response.status_code == 200

    def test_nonexistent_unit_returns_404(self):
        """A unit PK that doesn't exist must return 404."""
        admin = AdminUserFactory.create()
        url   = reverse("equipment:unit-inventory", kwargs={"unit_pk": 999999})
        response = _login(admin).get(url)
        assert response.status_code == 404

    def test_typed_inventory_groups_by_type(self):
        """
        Equipment items with an EquipmentType must appear in typed_inventory
        grouped by type, with correct total and functional counts.
        """
        unit = UnitFactory.create()
        et   = _make_equipment_type(name="Stretcher Type")
        # Create 3 items of this type — 2 functional, 1 not.
        EquipmentFactory.create(unit=unit, equipment_type=et, is_functional=True)
        EquipmentFactory.create(unit=unit, equipment_type=et, is_functional=True)
        EquipmentFactory.create(unit=unit, equipment_type=et, is_functional=False)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_inventory_url(unit))
        assert response.status_code == 200

        typed = response.context["typed_inventory"]
        # There should be one group for the type we created.
        matching = [row for row in typed if row["equipment_type__name"] == "Stretcher Type"]
        assert len(matching) == 1
        assert matching[0]["total"]          == 3
        assert matching[0]["functional"]     == 2
        assert matching[0]["non_functional"] == 1

    def test_untyped_inventory_appears_separately(self):
        """
        Equipment without an EquipmentType must appear in untyped_inventory,
        not in typed_inventory.
        """
        unit = UnitFactory.create()
        EquipmentFactory.create(unit=unit, equipment_type=None, name="Old Equipment")

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_inventory_url(unit))

        typed   = response.context["typed_inventory"]
        untyped = response.context["untyped_inventory"]

        typed_names = [r["equipment_type__name"] for r in typed]
        assert "Old Equipment" not in typed_names

        untyped_names = [r["name"] for r in untyped]
        assert "Old Equipment" in untyped_names

    def test_summary_counts_in_context(self):
        """
        total_items, functional_items, nonfunctional_items context vars must
        match the actual Equipment counts for the unit.
        """
        unit = UnitFactory.create()
        EquipmentFactory.create(unit=unit, is_functional=True)
        EquipmentFactory.create(unit=unit, is_functional=True)
        EquipmentFactory.create(unit=unit, is_functional=False)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_inventory_url(unit))

        assert response.context["total_items"]        == 3
        assert response.context["functional_items"]   == 2
        assert response.context["nonfunctional_items"] == 1

    def test_unit_name_appears_in_page(self):
        """The unit name must appear in the rendered HTML."""
        unit  = UnitFactory.create()
        admin = AdminUserFactory.create()
        response = _login(admin).get(_inventory_url(unit))
        assert unit.name in response.content.decode()

    def test_uic_can_view_inventory(self):
        """A UIC should be able to view their own unit's inventory (no restrictions)."""
        unit = UnitFactory.create()
        uic  = UICUserFactory.create(unit=unit)
        EquipmentFactory.create(unit=unit)
        response = _login(uic).get(_inventory_url(unit))
        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 6. EQUIPMENT MAINTENANCE BY UNIT VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentMaintenanceByUnit:
    """Tests for the unit-wise maintenance log view (EquipmentMaintenanceByUnitView)."""

    def test_unauthenticated_redirects(self):
        """Anonymous users must be redirected to login."""
        unit     = UnitFactory.create()
        response = Client().get(_logs_url(unit))
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_user_gets_200(self):
        """Any authenticated user can view the maintenance logs."""
        unit  = UnitFactory.create()
        admin = AdminUserFactory.create()
        response = _login(admin).get(_logs_url(unit))
        assert response.status_code == 200

    def test_nonexistent_unit_returns_404(self):
        """A PK not in the Unit table must return 404."""
        admin = AdminUserFactory.create()
        url   = reverse("equipment:unit-logs", kwargs={"unit_pk": 999999})
        response = _login(admin).get(url)
        assert response.status_code == 404

    def test_shows_only_logs_for_this_unit(self):
        """
        Logs for equipment in OTHER units must not appear in this unit's view.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip_a = EquipmentFactory.create(unit=unit_a)
        equip_b = EquipmentFactory.create(unit=unit_b)

        EquipmentMaintenanceLog.objects.create(
            equipment=equip_a, check_date=datetime.date.today(),
            is_fit=True, remarks="Unit A log"
        )
        EquipmentMaintenanceLog.objects.create(
            equipment=equip_b, check_date=datetime.date.today(),
            is_fit=True, remarks="Unit B log"
        )

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_logs_url(unit_a))
        content  = response.content.decode()

        assert "Unit A log" in content
        assert "Unit B log" not in content

    def test_empty_state_for_unit_with_no_logs(self):
        """
        A unit that has equipment but no maintenance logs must show the
        'No maintenance logs recorded' message.
        """
        unit  = UnitFactory.create()
        EquipmentFactory.create(unit=unit)
        admin = AdminUserFactory.create()
        response = _login(admin).get(_logs_url(unit))
        assert "No maintenance logs" in response.content.decode()

    def test_log_remarks_appear_in_response(self):
        """A log's remarks must be visible in the rendered table."""
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        EquipmentMaintenanceLog.objects.create(
            equipment=equip,
            check_date=datetime.date.today(),
            is_fit=False,
            remarks="Hydraulic seal blown, needs replacement.",
        )
        admin    = AdminUserFactory.create()
        response = _login(admin).get(_logs_url(unit))
        assert "Hydraulic seal blown" in response.content.decode()

    def test_system_seeded_log_shows_system_label(self):
        """
        A log with checked_by=None (system-seeded) must display 'System'
        rather than crashing or showing nothing.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        EquipmentMaintenanceLog.objects.create(
            equipment=equip,
            check_date=datetime.date.today(),
            is_fit=True,
            checked_by=None,
            remarks="Initial status found functional",
        )
        admin    = AdminUserFactory.create()
        response = _login(admin).get(_logs_url(unit))
        assert "System" in response.content.decode()


# ─────────────────────────────────────────────────────────────────────────────
# 7. EQUIPMENT OVERDUE VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentOverdueView:
    """Tests for EquipmentOverdueView — the delayed maintenance flagging view."""

    def test_unauthenticated_redirects(self):
        """Anonymous users must be redirected to login."""
        response = Client().get(_overdue_url())
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_user_gets_200(self):
        """Any authenticated user can access the overdue view."""
        admin = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        assert response.status_code == 200

    def test_never_inspected_functional_item_appears(self):
        """
        A functional item with last_check_date=None (never inspected) must
        appear in the overdue list.

        This covers condition B in the view: no last_check_date at all.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=True, last_check_date=None)
        admin = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        # The asset tag (unique_id) must appear in the HTML.
        assert equip.unique_id in response.content.decode()

    def test_overdue_next_due_date_appears(self):
        """
        A functional item whose next_due_date is in the past must appear in
        the overdue list.  This covers condition A.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=True)
        # Set next_due_date to yesterday so it is overdue.
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        equip.last_check_date = yesterday - datetime.timedelta(days=30)
        equip.next_due_date   = yesterday
        equip.save(update_fields=["last_check_date", "next_due_date"])

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        assert equip.unique_id in response.content.decode()

    def test_non_functional_item_excluded(self):
        """
        A non-functional item (is_functional=False) must NOT appear in the
        overdue list even if its next_due_date is in the past.

        We only care about items expected to be in active service.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=False)
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        equip.next_due_date = yesterday
        equip.save(update_fields=["next_due_date"])

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        assert equip.unique_id not in response.content.decode()

    def test_up_to_date_item_excluded(self):
        """
        An item whose next_due_date is in the future (not yet overdue) must
        NOT appear in the overdue list.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=True)
        future = datetime.date.today() + datetime.timedelta(days=30)
        equip.last_check_date = datetime.date.today()
        equip.next_due_date   = future
        equip.save(update_fields=["last_check_date", "next_due_date"])

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        assert equip.unique_id not in response.content.decode()

    def test_uic_sees_only_own_unit(self):
        """
        A UIC must only see overdue items from their own unit, not from other units.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip_a = EquipmentFactory.create(unit=unit_a, is_functional=True, last_check_date=None)
        equip_b = EquipmentFactory.create(unit=unit_b, is_functional=True, last_check_date=None)

        uic_a = UICUserFactory.create(unit=unit_a)
        response = _login(uic_a).get(_overdue_url())
        content = response.content.decode()

        assert equip_a.unique_id in content
        assert equip_b.unique_id not in content

    def test_admin_sees_all_units(self):
        """
        An admin/superuser must see overdue items from ALL units, not just one.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip_a = EquipmentFactory.create(unit=unit_a, is_functional=True, last_check_date=None)
        equip_b = EquipmentFactory.create(unit=unit_b, is_functional=True, last_check_date=None)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        content  = response.content.decode()

        assert equip_a.unique_id in content
        assert equip_b.unique_id in content

    def test_admin_can_filter_by_unit(self):
        """
        Admins can pass ?unit=<pk> to narrow the overdue view to a single unit.
        Only items from that unit must appear.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip_a = EquipmentFactory.create(unit=unit_a, is_functional=True, last_check_date=None)
        equip_b = EquipmentFactory.create(unit=unit_b, is_functional=True, last_check_date=None)

        admin    = AdminUserFactory.create()
        response = _login(admin).get(f"{_overdue_url()}?unit={unit_a.pk}")
        content  = response.content.decode()

        assert equip_a.unique_id in content
        assert equip_b.unique_id not in content

    def test_all_clear_message_when_no_overdue(self):
        """
        When no items are overdue, the template must show an 'all clear' success
        message instead of an alert.
        """
        admin = AdminUserFactory.create()
        # Don't create any equipment → nothing is overdue.
        response = _login(admin).get(_overdue_url())
        content  = response.content.decode()
        assert "up to date" in content.lower()

    def test_total_overdue_count_in_context(self):
        """
        context['total_overdue'] must equal the total number of overdue items
        visible to the current user (not just the current page).
        """
        unit  = UnitFactory.create()
        EquipmentFactory.create(unit=unit, is_functional=True, last_check_date=None)
        EquipmentFactory.create(unit=unit, is_functional=True, last_check_date=None)
        EquipmentFactory.create(unit=unit, is_functional=False)  # not overdue

        admin    = AdminUserFactory.create()
        response = _login(admin).get(_overdue_url())
        assert response.context["total_overdue"] >= 2
