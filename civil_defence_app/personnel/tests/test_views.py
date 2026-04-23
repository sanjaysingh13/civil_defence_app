"""
Tests for personnel/views.py

Views covered:
  UnitListView, UnitDetailView, VolunteerListView, VolunteerDetailView,
  VolunteerDeRosterView (POST), VolunteerReinstateView (POST), and office-duty CSV views.
"""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from civil_defence_app.incidents.models import IncidentAssignment
from civil_defence_app.incidents.tests.factories import AdminUserFactory
from civil_defence_app.incidents.tests.factories import IncidentFactory
from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VolunteerFactory
from civil_defence_app.personnel.models import OfficeDutyMonthSubmission
from civil_defence_app.personnel.models import Volunteer
from civil_defence_app.personnel.models import VolunteerOfficeDutyMonth
from civil_defence_app.users.models import User
from civil_defence_app.users.models import UserRole

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
        active = VolunteerFactory.create(
            unit=unit, name="Active Volunteer", is_active=True
        )
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

    def test_volunteer_detail_links_csv_for_owning_uic(self):
        """Owning UIC sees link to monthly office-duty CSV workflow."""
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit)
        url = reverse("personnel:volunteer-detail", kwargs={"pk": vol.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200
        assert "/personnel/office-duty/" in response.content.decode()


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER DE-ROSTER (POST)
# ─────────────────────────────────────────────────────────────────────────────


class TestVolunteerDeRosterView:
    """POST personnel:volunteer-deroster — Admin/UIC-only; date + reason required."""

    def test_unauthenticated_redirects_to_login(self):
        vol = VolunteerFactory.create(is_active=True)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = Client().post(
            url,
            {"derostered_on": "2026-04-01", "deroster_reason": "Test reason here"},
        )
        assert r.status_code == 302
        assert "login" in r["Location"]

    def test_uic_own_unit_derosters_volunteer(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit, is_active=True)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = _login(uic).post(
            url,
            {
                "derostered_on": "2026-04-01",
                "deroster_reason": "Retirement age reached",
            },
        )
        assert r.status_code == 302
        vol.refresh_from_db()
        assert vol.is_active is False
        assert vol.deroster_reason == "Retirement age reached"
        assert vol.derostered_on.isoformat() == "2026-04-01"

    def test_uic_other_unit_gets_403(self):
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit_a)
        vol = VolunteerFactory.create(unit=unit_b, is_active=True)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = _login(uic).post(
            url,
            {"derostered_on": "2026-04-01", "deroster_reason": "Should not apply"},
        )
        assert r.status_code == 403
        vol.refresh_from_db()
        assert vol.is_active is True

    def test_admin_can_deroster_any_unit(self):
        admin = AdminUserFactory.create()
        vol = VolunteerFactory.create(is_active=True)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = _login(admin).post(
            url,
            {
                "derostered_on": "2026-03-15",
                "deroster_reason": "Transferred out of district",
            },
        )
        assert r.status_code == 302
        vol.refresh_from_db()
        assert vol.is_active is False

    def test_volunteer_user_role_gets_403(self):
        unit = UnitFactory.create()
        vol_user = User.objects.create(
            username="vol_only2", role=UserRole.VOLUNTEER, unit=unit
        )
        vol_user.set_password("testpass123")
        vol_user.save()
        vol = VolunteerFactory.create(unit=unit, is_active=True)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = _login(vol_user).post(
            url,
            {"derostered_on": "2026-04-01", "deroster_reason": "Invalid attempt"},
        )
        assert r.status_code == 403

    def test_already_inactive_redirects_without_change(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit, is_active=False)
        url = reverse("personnel:volunteer-deroster", kwargs={"pk": vol.pk})
        r = _login(uic).post(
            url,
            {"derostered_on": "2026-04-01", "deroster_reason": "Again"},
        )
        assert r.status_code == 302
        vol.refresh_from_db()
        assert vol.is_active is False


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER REINSTATE (POST)
# ─────────────────────────────────────────────────────────────────────────────


class TestVolunteerReinstateView:
    """POST personnel:volunteer-reinstate — same auth as de-roster; clears audit fields."""

    def test_unauthenticated_redirects_to_login(self):
        vol = VolunteerFactory.create(is_active=False)
        url = reverse("personnel:volunteer-reinstate", kwargs={"pk": vol.pk})
        r = Client().post(url, {})
        assert r.status_code == 302
        assert "login" in r["Location"]

    def test_uic_reinstates_own_unit_volunteer(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(
            unit=unit,
            is_active=False,
            derostered_on="2026-01-15",
            deroster_reason="Left district",
        )
        url = reverse("personnel:volunteer-reinstate", kwargs={"pk": vol.pk})
        r = _login(uic).post(url, {})
        assert r.status_code == 302
        vol.refresh_from_db()
        assert vol.is_active is True
        assert vol.derostered_on is None
        assert vol.deroster_reason == ""

    def test_uic_other_unit_gets_403(self):
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit_a)
        vol = VolunteerFactory.create(unit=unit_b, is_active=False)
        url = reverse("personnel:volunteer-reinstate", kwargs={"pk": vol.pk})
        r = _login(uic).post(url, {})
        assert r.status_code == 403
        vol.refresh_from_db()
        assert vol.is_active is False

    def test_already_active_redirects_without_change(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        vol = VolunteerFactory.create(unit=unit, is_active=True)
        url = reverse("personnel:volunteer-reinstate", kwargs={"pk": vol.pk})
        r = _login(uic).post(url, {})
        assert r.status_code == 302
        vol.refresh_from_db()
        assert vol.is_active is True

    def test_volunteer_user_role_gets_403(self):
        unit = UnitFactory.create()
        vol_user = User.objects.create(
            username="vol_only3", role=UserRole.VOLUNTEER, unit=unit
        )
        vol_user.set_password("testpass123")
        vol_user.save()
        vol = VolunteerFactory.create(unit=unit, is_active=False)
        url = reverse("personnel:volunteer-reinstate", kwargs={"pk": vol.pk})
        r = _login(vol_user).post(url, {})
        assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY — MONTHLY CSV
# ─────────────────────────────────────────────────────────────────────────────


def _csv_bytes_for_volunteers(*vols: Volunteer, days: str = "3") -> bytes:
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["serial_no", "name", "volunteer_id", "days_worked"])
    for vol in vols:
        w.writerow([vol.serial_no or "", vol.name or "", str(vol.pk), days])
    return buf.getvalue().encode("utf-8")


def _csv_bytes_with_rows(rows: list[list[str]]) -> bytes:
    """Build CSV bytes with explicit rows for edge-case parser tests."""
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["serial_no", "name", "volunteer_id", "days_worked"])
    for row in rows:
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


class TestOfficeDutyMonthlyHubAndDownload:
    hub = reverse("personnel:office-duty-monthly")
    dl = reverse("personnel:office-duty-template-download")

    def test_hub_unauthenticated_redirects(self):
        assert Client().get(self.hub).status_code == 302

    def test_volunteer_role_gets_403_on_hub(self):
        unit = UnitFactory.create()
        vol_user = User.objects.create(
            username="vol_only", role=UserRole.VOLUNTEER, unit=unit
        )
        vol_user.set_password("testpass123")
        vol_user.save()
        r = _login(vol_user).get(self.hub)
        assert r.status_code == 403

    def test_admin_download_template_200(self):
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        VolunteerFactory.create(unit=unit, serial_no="S1", name="A", is_active=True)
        q = f"dl-year=2026&dl-month=4&dl-unit={unit.pk}"
        r = _login(admin).get(f"{self.dl}?{q}")
        assert r.status_code == 200
        assert "text/csv" in r["Content-Type"]
        body = r.content.decode("utf-8-sig")
        assert "volunteer_id" in body
        assert "S1" in body

    def test_uic_download_uses_own_unit(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        VolunteerFactory.create(unit=unit, is_active=True)
        q = "dl-year=2026&dl-month=3"
        r = _login(uic).get(f"{self.dl}?{q}")
        assert r.status_code == 200


class TestOfficeDutyMonthlyUpload:
    upload_url = reverse("personnel:office-duty-upload")

    def test_admin_upload_creates_rows_and_submission(self):
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        vol = VolunteerFactory.create(
            unit=unit, serial_no="X1", name="Tester", is_active=True
        )
        csv_bytes = _csv_bytes_for_volunteers(vol, days="5")
        f = SimpleUploadedFile("filled.csv", csv_bytes, content_type="text/csv")
        client = _login(admin)
        r = client.post(
            self.upload_url,
            {
                "up-year": "2026",
                "up-month": "6",
                "up-unit": str(unit.pk),
                "up-csv_file": f,
            },
        )
        assert r.status_code == 302
        row = VolunteerOfficeDutyMonth.objects.get(volunteer=vol, year=2026, month=6)
        assert row.days_worked == 5
        assert OfficeDutyMonthSubmission.objects.filter(
            unit=unit, year=2026, month=6
        ).exists()

    def test_upload_rejects_wrong_unit_volunteer(self):
        admin = AdminUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        vol_b = VolunteerFactory.create(unit=unit_b, serial_no="B1", is_active=True)
        csv_bytes = _csv_bytes_for_volunteers(vol_b)
        f = SimpleUploadedFile("bad.csv", csv_bytes, content_type="text/csv")
        client = _login(admin)
        r = client.post(
            self.upload_url,
            {
                "up-year": "2026",
                "up-month": "5",
                "up-unit": str(unit_a.pk),
                "up-csv_file": f,
            },
        )
        assert r.status_code == 302
        assert VolunteerOfficeDutyMonth.objects.count() == 0

    def test_upload_appended_row_creates_new_volunteer(self):
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        existing = VolunteerFactory.create(
            unit=unit,
            serial_no="S9",
            name="Existing Person",
            is_active=True,
        )
        csv_bytes = _csv_bytes_with_rows(
            [
                [existing.serial_no, existing.name, str(existing.pk), "4"],
                ["", "New Recruit", "", "7"],
            ],
        )
        f = SimpleUploadedFile("filled.csv", csv_bytes, content_type="text/csv")
        client = _login(admin)
        r = client.post(
            self.upload_url,
            {
                "up-year": "2026",
                "up-month": "6",
                "up-unit": str(unit.pk),
                "up-csv_file": f,
            },
        )
        assert r.status_code == 302
        new_vol = Volunteer.objects.get(unit=unit, name="New Recruit")
        assert new_vol.serial_no == "S10"
        assert new_vol.is_active is True
        assert VolunteerOfficeDutyMonth.objects.get(
            volunteer=new_vol,
            year=2026,
            month=6,
        ).days_worked == 7


class TestOfficeDutyStatusAndEmail:
    status_url = reverse("personnel:office-duty-status")
    email_url = reverse("personnel:office-duty-email-uic")

    def test_uic_gets_403_on_status(self):
        uic = UICUserFactory.create()
        r = _login(uic).get(self.status_url)
        assert r.status_code == 403

    def test_admin_status_shows_submitted_flag(self):
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        OfficeDutyMonthSubmission.objects.create(
            unit=unit, year=2026, month=8, submitted_by=admin
        )
        r = _login(admin).get(self.status_url, {"st-year": "2026", "st-month": "8"})
        assert r.status_code == 200
        html = r.content.decode()
        assert unit.name in html
        assert "Submitted" in html

    def test_email_uic_sends_attachment_when_email_present(self):
        mail.outbox.clear()
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit, email="uic@example.test")
        r = _login(admin).post(
            self.email_url,
            {
                "em-unit": str(unit.pk),
                "em-year": "2026",
                "em-month": "9",
            },
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 1
        msg = mail.outbox[0]
        assert msg.to == ["uic@example.test"]
        assert len(msg.attachments) == 1
        assert msg.attachments[0][2] == "text/csv"

    def test_email_no_outbox_when_uic_has_no_email(self):
        mail.outbox.clear()
        admin = AdminUserFactory.create()
        unit = UnitFactory.create()
        UICUserFactory.create(unit=unit, email="")
        r = _login(admin).post(
            self.email_url,
            {
                "em-unit": str(unit.pk),
                "em-year": "2026",
                "em-month": "10",
            },
        )
        assert r.status_code == 302
        assert len(mail.outbox) == 0
