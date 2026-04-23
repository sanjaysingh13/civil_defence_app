"""
Tests for the Equipment Maintenance Log feature.

Three test classes:
  TestMaintenanceLogModel   — model field defaults, __str__, is_fit independence.
  TestMaintenanceLogForm    — form validation, default date, required / optional fields.
  TestMaintenanceLogView    — full HTTP layer: access control, GET form render,
                              POST creates log + updates equipment, idempotency of
                              repeated inspections, and template branches on detail page.
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
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


def _add_log_url(equip: Equipment) -> str:
    return reverse("equipment:equipment-log-add", kwargs={"pk": equip.pk})


def _detail_url(equip: Equipment) -> str:
    return reverse("equipment:equipment-detail", kwargs={"pk": equip.pk})


# ─────────────────────────────────────────────────────────────────────────────
# 1. MODEL
# ─────────────────────────────────────────────────────────────────────────────

class TestMaintenanceLogModel:
    """Unit tests for EquipmentMaintenanceLog model fields and __str__."""

    def test_is_fit_defaults_to_true(self):
        """
        A newly created log row must default is_fit=True (the common case —
        most inspections confirm the item is still working).
        """
        equip = EquipmentFactory.create()
        log   = EquipmentMaintenanceLog.objects.create(
            equipment  = equip,
            check_date = datetime.date.today(),
        )
        assert log.is_fit is True

    def test_can_create_not_fit_log(self):
        """is_fit=False must persist without any constraint error."""
        equip = EquipmentFactory.create()
        log   = EquipmentMaintenanceLog.objects.create(
            equipment  = equip,
            check_date = datetime.date.today(),
            is_fit     = False,
        )
        reloaded = EquipmentMaintenanceLog.objects.get(pk=log.pk)
        assert reloaded.is_fit is False

    def test_str_includes_fit_label(self):
        """
        __str__ must include the word 'Fit' or 'Not Fit' so log entries are
        instantly readable in the admin list view.
        """
        equip = EquipmentFactory.create(name="Life Jacket")
        log   = EquipmentMaintenanceLog.objects.create(
            equipment  = equip,
            check_date = datetime.date(2026, 3, 27),
            is_fit     = True,
        )
        assert "Fit" in str(log)

    def test_str_not_fit_label(self):
        equip = EquipmentFactory.create(name="Broken Generator")
        log   = EquipmentMaintenanceLog.objects.create(
            equipment  = equip,
            check_date = datetime.date(2026, 3, 27),
            is_fit     = False,
        )
        assert "Not Fit" in str(log)


# ─────────────────────────────────────────────────────────────────────────────
# 2. FORM
# ─────────────────────────────────────────────────────────────────────────────

class TestMaintenanceLogForm:
    """Unit tests for EquipmentMaintenanceLogForm validation."""

    def _make_form(self, data=None):
        from civil_defence_app.equipment.forms import EquipmentMaintenanceLogForm
        return EquipmentMaintenanceLogForm(data=data)

    def test_valid_with_all_fields(self):
        """A fully populated form must be valid."""
        form = self._make_form({
            "check_date": "2026-03-27",
            "is_fit":     True,
            "remarks":    "All good, lubricated moving parts.",
        })
        assert form.is_valid(), form.errors

    def test_valid_without_remarks(self):
        """remarks is optional (blank=True on the model) — omitting it is valid."""
        form = self._make_form({
            "check_date": "2026-03-27",
            "is_fit":     True,
            "remarks":    "",
        })
        assert form.is_valid(), form.errors

    def test_invalid_without_check_date(self):
        """check_date is required — omitting it must produce a validation error."""
        form = self._make_form({
            "check_date": "",
            "is_fit":     True,
        })
        assert not form.is_valid()
        assert "check_date" in form.errors

    def test_default_check_date_is_today(self):
        """
        An unbound form (no POST data) must pre-populate check_date with today's
        date so the UIC rarely has to change it.
        """
        form = self._make_form()   # unbound — no data argument
        assert form.initial.get("check_date") == datetime.date.today().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# 3. VIEW — access control
# ─────────────────────────────────────────────────────────────────────────────

class TestMaintenanceLogViewAccess:
    """Test the UIC-only access gate on EquipmentMaintenanceLogCreateView."""

    def test_unauthenticated_redirected_to_login(self):
        """Anonymous visitors must be redirected to the login page."""
        equip    = EquipmentFactory.create()
        response = Client().get(_add_log_url(equip))
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_uic_of_same_unit_gets_form(self):
        """A UIC whose unit owns the equipment must see the form (200)."""
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_add_log_url(equip))
        assert response.status_code == 200

    def test_uic_of_different_unit_gets_403(self):
        """
        A UIC from a different unit must be refused — they cannot log maintenance
        for equipment they don't own.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip  = EquipmentFactory.create(unit=unit_a)
        uic_b  = UICUserFactory.create(unit=unit_b)
        response = _login(uic_b).get(_add_log_url(equip))
        assert response.status_code == 403

    def test_admin_superuser_gets_form(self):
        """Django superusers bypass the unit-ownership check (admin oversight)."""
        equip = EquipmentFactory.create()
        admin = AdminUserFactory.create()
        response = _login(admin).get(_add_log_url(equip))
        assert response.status_code == 200

    def test_nonexistent_equipment_returns_404(self):
        """A PK that does not exist in the Equipment table must return 404."""
        uic = UICUserFactory.create()
        url = reverse("equipment:equipment-log-add", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. VIEW — POST / business logic
# ─────────────────────────────────────────────────────────────────────────────

class TestMaintenanceLogViewPost:
    """Test that a valid POST creates the log and updates the equipment."""

    def _post(self, uic, equip, data):
        return _login(uic).post(_add_log_url(equip), data)

    def test_valid_post_creates_log_row(self):
        """Submitting a valid form must create one EquipmentMaintenanceLog row."""
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        self._post(uic, equip, {
            "check_date": "2026-03-27",
            "is_fit":     "on",     # HTML checkbox sends "on" when ticked
            "remarks":    "Tested OK",
        })
        assert EquipmentMaintenanceLog.objects.filter(equipment=equip).count() == 1

    def test_valid_post_redirects_to_detail(self):
        """
        A successful POST must redirect (302) to the equipment detail page, not
        re-render the form.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        response = self._post(uic, equip, {
            "check_date": "2026-03-27",
            "is_fit":     "on",
            "remarks":    "",
        })
        assert response.status_code == 302
        assert response["Location"] == _detail_url(equip)

    def test_fit_true_sets_equipment_functional(self):
        """
        When is_fit is True, Equipment.is_functional must be updated to True
        and Equipment.status must be set to OK.
        """
        unit  = UnitFactory.create()
        # Start with a non-functional item so we can verify the update
        equip = EquipmentFactory.create(unit=unit, is_functional=False, status="REPAIR")
        uic   = UICUserFactory.create(unit=unit)
        self._post(uic, equip, {
            "check_date": "2026-03-27",
            "is_fit":     "on",
            "remarks":    "Repaired and tested.",
        })
        equip.refresh_from_db()
        assert equip.is_functional is True
        assert equip.status == EquipmentStatus.FUNCTIONAL

    def test_fit_false_sets_equipment_non_functional(self):
        """
        When is_fit is False (checkbox left un-ticked), Equipment.is_functional
        must be set to False and status to REPAIR.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=True, status="OK")
        uic   = UICUserFactory.create(unit=unit)
        # HTML form sends nothing for an un-ticked checkbox, so omit is_fit
        self._post(uic, equip, {
            "check_date": "2026-03-27",
            "remarks":    "Found damaged, needs repair.",
        })
        equip.refresh_from_db()
        assert equip.is_functional is False
        assert equip.status == EquipmentStatus.REPAIR

    def test_last_check_date_updated_on_equipment(self):
        """
        Equipment.last_check_date must be updated to the inspection date
        submitted in the form.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        self._post(uic, equip, {
            "check_date": "2026-03-27",
            "is_fit":     "on",
            "remarks":    "",
        })
        equip.refresh_from_db()
        assert equip.last_check_date == datetime.date(2026, 3, 27)

    def test_checked_by_stamped_as_current_user(self):
        """
        The log row must record checked_by = the logged-in UIC, not null.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        self._post(uic, equip, {
            "check_date": "2026-03-27",
            "is_fit":     "on",
            "remarks":    "",
        })
        log = EquipmentMaintenanceLog.objects.get(equipment=equip)
        assert log.checked_by == uic

    def test_second_inspection_overwrites_functional_status(self):
        """
        A second maintenance log for the same equipment must update
        is_functional again — the latest inspection always wins.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit, is_functional=True)
        uic   = UICUserFactory.create(unit=unit)
        # First inspection: fit
        self._post(uic, equip, {"check_date": "2026-03-01", "is_fit": "on", "remarks": ""})
        # Second inspection: not fit
        self._post(uic, equip, {"check_date": "2026-03-27", "remarks": "Motor seized"})
        equip.refresh_from_db()
        assert equip.is_functional is False
        assert EquipmentMaintenanceLog.objects.filter(equipment=equip).count() == 2

    def test_invalid_post_rerenders_form(self):
        """
        A POST missing required fields (check_date) must return 200 with the
        form re-rendered showing errors — not save a log or redirect.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        response = self._post(uic, equip, {
            "check_date": "",    # missing required field
            "is_fit":     "on",
        })
        assert response.status_code == 200
        assert EquipmentMaintenanceLog.objects.filter(equipment=equip).count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. DETAIL PAGE — template branches
# ─────────────────────────────────────────────────────────────────────────────

class TestEquipmentDetailWithLogs:
    """Test the equipment detail page template branches added for maintenance logs."""

    def test_detail_shows_add_log_button_for_owning_uic(self):
        """
        The '+ Log Maintenance' action button must appear on the detail page
        for a UIC whose unit owns the equipment (can_log=True path).

        We check for '+ Log Maintenance' (with the '+' prefix) which is the
        exact text of the button rendered when can_log=True in equipment_detail.html.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_detail_url(equip))
        assert "+ Log Maintenance" in response.content.decode()

    def test_detail_hides_add_log_button_for_other_unit_uic(self):
        """
        The '+ Log Maintenance' action button in the equipment detail card must
        NOT appear for a UIC from a different unit.

        Note: the navbar always contains 'Log Maintenance (select item first)'
        for UIC users regardless of unit ownership — that is a nav link, not
        the item-specific action button.  We check for '+ Log Maintenance'
        (with the '+' prefix) which only appears in the detail page content
        when can_log=True.
        """
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        equip  = EquipmentFactory.create(unit=unit_a)
        uic_b  = UICUserFactory.create(unit=unit_b)
        response = _login(uic_b).get(_detail_url(equip))
        assert "+ Log Maintenance" not in response.content.decode()

    def test_detail_shows_empty_history_message(self):
        """
        When there are no maintenance logs the template must show the
        'No maintenance records yet' message.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_detail_url(equip))
        assert "No maintenance records" in response.content.decode()

    def test_detail_shows_log_history_when_present(self):
        """
        When a maintenance log exists, the table must appear and include
        the remarks from that log entry.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        uic   = UICUserFactory.create(unit=unit)
        EquipmentMaintenanceLog.objects.create(
            equipment  = equip,
            check_date = datetime.date(2026, 3, 27),
            is_fit     = True,
            checked_by = uic,
            remarks    = "All components inspected and cleared.",
        )
        response = _login(uic).get(_detail_url(equip))
        content  = response.content.decode()
        assert "All components inspected and cleared." in content
        # The fitness badge must also appear
        assert "Fit" in content

    def test_detail_shows_last_check_date(self):
        """
        Equipment.last_check_date (updated by the view on form save) must
        appear on the detail page in the Equipment Details card.
        """
        unit  = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        equip.last_check_date = datetime.date(2026, 3, 1)
        equip.save(update_fields=["last_check_date"])
        uic = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_detail_url(equip))
        assert "01 Mar 2026" in response.content.decode()

    def test_detail_shows_maintainance_note_when_present(self):
        """
        The equipment detail page should render the read-only maintenance
        reminder note when configured on the equipment row.
        """
        unit = UnitFactory.create()
        equip = EquipmentFactory.create(unit=unit)
        equip.equipment_type = EquipmentType.objects.create(
            name="Battery Unit Type",
            equipment_maintainance_note="Check battery terminals before each shift.",
        )
        equip.save(update_fields=["equipment_type"])
        uic = UICUserFactory.create(unit=unit)
        response = _login(uic).get(_detail_url(equip))
        content = response.content.decode()
        assert "Maintenance reminder note" in content
        assert "Check battery terminals before each shift." in content
