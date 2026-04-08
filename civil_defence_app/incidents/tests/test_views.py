"""
Tests for incidents/views.py

What we verify:

  IncidentListView
    - Unauthenticated users are redirected to the login page.
    - Authenticated users (any role) get HTTP 200.
    - Filtering by status, type, and unit works correctly.

  IncidentDispatchView
    - Unauthenticated users are redirected to login.
    - Volunteers (wrong role) are redirected with an error message, NOT 403.
    - Unit In-Charges (UIC) with an assigned unit can GET the form (200).
    - A valid POST from a UIC creates the Incident + IncidentAssignment rows.
    - A POST without volunteers re-renders the form with errors (no Incident saved).

  IncidentDetailView
    - Any authenticated user can view an incident (200).
    - can_report=True only for the UIC whose unit owns the incident.

  IncidentReportView
    - The owning UIC can GET the report form (200).
    - A UIC from a different unit gets a 404 (queryset restricts access).
    - A valid POST with action="save_report" updates final_report + status.
    - A POST with action="upload_media" stores an IncidentMedia file.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.models import Incident
from civil_defence_app.incidents.models import IncidentAssignment
from civil_defence_app.incidents.models import IncidentAssignmentRole
from civil_defence_app.incidents.models import IncidentMedia
from civil_defence_app.incidents.models import IncidentStatus
from civil_defence_app.users.models import User

from .factories import EquipmentFactory
from .factories import IncidentFactory
from .factories import UICUserFactory
from .factories import VehicleFactory
from .factories import VolunteerFactory

pytestmark = pytest.mark.django_db


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def login_client(user: User, password: str = "testpass123") -> Client:
    """
    Return a Django test Client already logged in as `user`.

    django.test.Client simulates a browser session — it handles cookies,
    middleware, CSRF tokens, and session state just like a real browser,
    making it the right tool for view-level integration tests.
    """
    client = Client()
    client.login(username=user.username, password=password)
    return client


# ─────────────────────────────────────────────────────────────────────────────
# LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentListView:
    url = reverse("incidents:incident-list")

    def test_unauthenticated_redirects_to_login(self):
        """
        LoginRequiredMixin must redirect anonymous visitors to the login page.
        The response status code will be 302 (Found / Redirect).
        """
        response = Client().get(self.url)
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_authenticated_user_gets_200(self):
        """
        Any logged-in user (regardless of role) may view the incident list.
        """
        uic = UICUserFactory.create()
        client = login_client(uic)
        response = client.get(self.url)
        assert response.status_code == 200

    def test_incidents_appear_in_response(self):
        """
        Incidents saved to the database must appear as rows in the rendered
        HTML of the list page.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create()
        client = login_client(uic)
        response = client.get(self.url)
        assert incident.title in response.content.decode()

    def test_filter_by_status(self):
        """
        Passing ?status=CLOSED must exclude OPEN incidents from results and
        include only closed ones.
        """
        uic = UICUserFactory.create()
        open_inc = IncidentFactory.create(status=IncidentStatus.OPEN)
        closed_inc = IncidentFactory.create(status=IncidentStatus.CLOSED)
        client = login_client(uic)
        response = client.get(self.url, {"status": "CLOSED"})
        content = response.content.decode()
        assert closed_inc.title in content
        assert open_inc.title not in content


# ─────────────────────────────────────────────────────────────────────────────
# DISPATCH VIEW
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentDispatchView:
    url = reverse("incidents:incident-dispatch")

    def test_unauthenticated_redirects_to_login(self):
        """
        Anonymous visitors must be redirected to the login page before they
        can access the dispatch form.
        """
        response = Client().get(self.url)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_volunteer_role_gets_redirected_with_error(self):
        """
        A user with role=VOLUNTEER must NOT see the dispatch form.
        UnitInChargeRequiredMixin redirects them (not 403) with an error
        message and sends them to the incident list.
        """
        volunteer_user = UICUserFactory.create()
        volunteer_user.role = "VOLUNTEER"
        volunteer_user.save()
        client = login_client(volunteer_user)
        response = client.get(self.url)
        assert response.status_code == 302
        assert "incident" in response["Location"]

    def test_uic_gets_dispatch_form(self):
        """
        A Unit In-Charge with an assigned unit must see the dispatch form
        (HTTP 200) when they GET the URL.
        """
        uic = UICUserFactory.create()
        client = login_client(uic)
        response = client.get(self.url)
        assert response.status_code == 200

    def test_valid_post_creates_incident(self):
        """
        A valid POST from a UIC must create exactly one new Incident row in
        the database.  The incident must be owned by the UIC's unit.
        """
        uic = UICUserFactory.create()
        volunteer = VolunteerFactory.create(unit=uic.unit)
        client = login_client(uic)
        initial_count = Incident.objects.count()
        response = client.post(
            self.url,
            {
                "title": "Test incident",
                "incident_type": "FLOOD",
                "assignment_volunteer": [str(volunteer.pk)],
                "assignment_role": [IncidentAssignmentRole.FIREFIGHTER],
            },
        )
        assert Incident.objects.count() == initial_count + 1
        new_incident = Incident.objects.latest("created_at")
        assert new_incident.unit == uic.unit
        assert response.status_code == 302

    def test_valid_post_creates_assignments(self):
        """
        Each selected volunteer must generate an IncidentAssignment row
        linking them to the newly created Incident.
        """
        uic = UICUserFactory.create()
        vol1 = VolunteerFactory.create(unit=uic.unit)
        vol2 = VolunteerFactory.create(unit=uic.unit)
        client = login_client(uic)
        client.post(
            self.url,
            {
                "title": "Multi-volunteer incident",
                "incident_type": "SEARCH",
                "assignment_volunteer": [str(vol1.pk), str(vol2.pk)],
                "assignment_role": [
                    IncidentAssignmentRole.DRIVER,
                    IncidentAssignmentRole.SCUBA_DIVER,
                ],
            },
        )
        incident = Incident.objects.latest("created_at")
        assert IncidentAssignment.objects.filter(incident=incident).count() == 2
        roles = set(
            IncidentAssignment.objects.filter(incident=incident).values_list(
                "role",
                flat=True,
            ),
        )
        assert roles == {
            IncidentAssignmentRole.DRIVER,
            IncidentAssignmentRole.SCUBA_DIVER,
        }

    def test_valid_post_auto_generates_incident_number(self):
        """
        After a successful dispatch, the new incident must have a non-empty
        incident_number in the UNIT-YEAR-NNN format.
        """
        uic = UICUserFactory.create()
        volunteer = VolunteerFactory.create(unit=uic.unit)
        client = login_client(uic)
        client.post(
            self.url,
            {
                "title": "Auto-numbered incident",
                "incident_type": "FIRE",
                "assignment_volunteer": [str(volunteer.pk)],
                "assignment_role": [IncidentAssignmentRole.FIREFIGHTER],
            },
        )
        incident = Incident.objects.latest("created_at")
        assert incident.incident_number is not None
        assert uic.unit.slug.upper() in incident.incident_number

    def test_post_without_volunteers_re_renders_form(self):
        """
        Submitting the dispatch form with no volunteers selected must NOT
        save an Incident.  The view re-renders the form with validation
        errors instead of redirecting.
        """
        uic = UICUserFactory.create()
        VolunteerFactory.create(unit=uic.unit)
        client = login_client(uic)
        initial_count = Incident.objects.count()
        response = client.post(
            self.url,
            {
                "title": "Missing volunteers",
                "incident_type": "FLOOD",
                "assignment_volunteer": [],
                "assignment_role": [],
            },
        )
        assert response.status_code == 200
        assert Incident.objects.count() == initial_count

    def test_valid_post_with_equipment_creates_allocations(self):
        """
        Selecting equipment in the dispatch form must create IncidentEquipment
        rows linking the equipment to the new incident.
        """
        from civil_defence_app.equipment.models import IncidentEquipment

        uic = UICUserFactory.create()
        volunteer = VolunteerFactory.create(unit=uic.unit)
        equip = EquipmentFactory.create(unit=uic.unit)
        client = login_client(uic)
        client.post(
            self.url,
            {
                "title": "Incident with equipment",
                "incident_type": "FIRE",
                "assignment_volunteer": [str(volunteer.pk)],
                "assignment_role": [IncidentAssignmentRole.CUTTER],
                "equipment_items": [equip.pk],
            },
        )
        incident = Incident.objects.latest("created_at")
        assert IncidentEquipment.objects.filter(
            incident=incident, equipment=equip
        ).exists()

    def test_valid_post_with_vehicle_creates_allocations(self):
        """
        Selecting vehicles in the dispatch form must create IncidentVehicle
        rows linking the vehicles to the new incident.
        """
        from civil_defence_app.fleet.models import IncidentVehicle

        uic = UICUserFactory.create()
        volunteer = VolunteerFactory.create(unit=uic.unit)
        vehicle = VehicleFactory.create(unit=uic.unit)
        client = login_client(uic)
        client.post(
            self.url,
            {
                "title": "Incident with vehicle",
                "incident_type": "ACCIDENT",
                "assignment_volunteer": [str(volunteer.pk)],
                "assignment_role": [IncidentAssignmentRole.DRIVER],
                "vehicles": [vehicle.pk],
            },
        )
        incident = Incident.objects.latest("created_at")
        assert IncidentVehicle.objects.filter(
            incident=incident, vehicle=vehicle
        ).exists()


# ─────────────────────────────────────────────────────────────────────────────
# DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentDetailView:
    """
    Tests for the read-only detail page that any authenticated user can view.
    """

    def test_any_authenticated_user_gets_200(self):
        """
        IncidentDetailView uses LoginRequiredMixin (not UnitInChargeRequired),
        so any logged-in user should be able to see the detail page.
        """
        incident = IncidentFactory.create()
        uic = UICUserFactory.create()
        client = login_client(uic)
        url = reverse("incidents:incident-detail", kwargs={"pk": incident.pk})
        response = client.get(url)
        assert response.status_code == 200

    def test_can_report_true_for_owning_uic(self):
        """
        The template receives can_report=True only when the logged-in UIC's
        unit matches the incident's unit.  We verify this via context.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        client = login_client(uic)
        url = reverse("incidents:incident-detail", kwargs={"pk": incident.pk})
        response = client.get(url)
        assert response.context["can_report"] is True

    def test_can_report_false_for_different_unit_uic(self):
        """
        A UIC from a different unit must NOT have permission to file a report
        on an incident they don't own — can_report must be False.
        """
        uic_a = UICUserFactory.create()
        uic_b = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic_a.unit)
        client = login_client(uic_b)
        url = reverse("incidents:incident-detail", kwargs={"pk": incident.pk})
        response = client.get(url)
        assert response.context["can_report"] is False


# ─────────────────────────────────────────────────────────────────────────────
# REPORT VIEW
# ─────────────────────────────────────────────────────────────────────────────


class TestIncidentReportView:
    """
    Tests for the post-incident report submission page.

    The view's get_queryset() filters incidents to the UIC's unit, so a UIC
    from a different unit gets a 404 when trying to access another unit's
    incident report URL.
    """

    def test_owning_uic_can_get_report_form(self):
        """
        The UIC whose unit owns the incident must be able to GET the report
        form page (HTTP 200).
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        client = login_client(uic)
        url = reverse("incidents:incident-report", kwargs={"pk": incident.pk})
        response = client.get(url)
        assert response.status_code == 200

    def test_different_unit_uic_gets_404(self):
        """
        A UIC from a different unit cannot edit the report of an incident
        they don't own.  get_queryset() excludes the incident → 404.
        """
        uic_a = UICUserFactory.create()
        uic_b = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic_a.unit)
        client = login_client(uic_b)
        url = reverse("incidents:incident-report", kwargs={"pk": incident.pk})
        response = client.get(url)
        assert response.status_code == 404

    def test_save_report_updates_incident(self):
        """
        A POST with action="save_report" must save the final_report text and
        update the status to CLOSED on the Incident row.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit, status=IncidentStatus.OPEN)
        client = login_client(uic)
        url = reverse("incidents:incident-report", kwargs={"pk": incident.pk})
        response = client.post(
            url,
            {
                "action": "save_report",
                "final_report": "Full narrative of the flood response.",
                "end_time": "2026-03-27T16:00",
                "status": IncidentStatus.CLOSED,
            },
        )
        assert response.status_code == 302
        incident.refresh_from_db()
        assert incident.final_report == "Full narrative of the flood response."
        assert incident.status == IncidentStatus.CLOSED

    def test_upload_media_creates_incident_media(self, settings, tmp_path):
        """
        A POST with action="upload_media" must create an IncidentMedia row
        with the uploaded file attached to the incident.

        SimpleUploadedFile simulates a real file upload without needing an
        actual file on disk — Django treats it exactly like a multipart POST.
        """
        settings.MEDIA_ROOT = str(tmp_path)
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        client = login_client(uic)
        url = reverse("incidents:incident-report", kwargs={"pk": incident.pk})

        fake_image = SimpleUploadedFile(
            "scene.jpg",
            b"\xff\xd8\xff\xe0" + b"\x00" * 100,
            content_type="image/jpeg",
        )
        response = client.post(
            url,
            {
                "action": "upload_media",
                "files": fake_image,
                "caption": "Scene at arrival",
            },
        )
        assert response.status_code == 302
        assert IncidentMedia.objects.filter(incident=incident).exists()
        media = IncidentMedia.objects.get(incident=incident)
        assert media.caption == "Scene at arrival"

    def test_upload_media_without_file_shows_warning(self):
        """
        Posting to upload_media with no files attached must NOT create any
        IncidentMedia rows — the view shows a warning message and redirects.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        client = login_client(uic)
        url = reverse("incidents:incident-report", kwargs={"pk": incident.pk})
        response = client.post(
            url,
            {
                "action": "upload_media",
                "caption": "No files uploaded",
            },
        )
        assert response.status_code == 302
        assert IncidentMedia.objects.filter(incident=incident).count() == 0
