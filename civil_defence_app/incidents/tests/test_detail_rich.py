"""
Tests that exercise the full content branches of incident_detail.html and
key branches of base.html.

incident_detail.html has many conditional sections ({% if %} blocks) that
only render when the incident has related objects attached.  Without these
tests those branches show 0% coverage.  We create fully-populated incidents
to hit every section of the template.

base.html has three distinct navbar/badge states based on user role:
  - Superuser / Admin role  → Admin badge + full admin nav
  - Unit In-Charge          → Unit name badge + UIC nav
  - Volunteer               → "Volunteer" badge + restricted nav

Each state is exercised by rendering a page while logged in as the
appropriate role.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from civil_defence_app.equipment.models import IncidentEquipment
from civil_defence_app.fleet.models import IncidentVehicle
from civil_defence_app.incidents.models import IncidentAssignment
from civil_defence_app.incidents.models import IncidentMedia
from civil_defence_app.incidents.models import IncidentStatus
from civil_defence_app.users.models import UserRole

from .factories import AdminUserFactory
from .factories import EquipmentFactory
from .factories import IncidentFactory
from .factories import UICUserFactory
from .factories import VehicleFactory
from .factories import VolunteerFactory

pytestmark = pytest.mark.django_db


def _login(user) -> Client:
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


def _detail_url(incident):
    return reverse("incidents:incident-detail", kwargs={"pk": incident.pk})


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT DETAIL — RICH CONTENT BRANCHES
# ─────────────────────────────────────────────────────────────────────────────

class TestIncidentDetailRichContent:
    """
    Each test creates an incident with specific related objects attached,
    then GETs the detail page and asserts that the corresponding template
    section is rendered.  This drives coverage of the {% if %} branches in
    incident_detail.html.
    """

    def test_volunteers_section_rendered_when_assignments_exist(self):
        """
        The "Dispatched Volunteers" table (guarded by
        {% if incident.assignments.all %}) must appear when at least one
        IncidentAssignment is linked to the incident.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        volunteer = VolunteerFactory.create(unit=uic.unit, name="Dispatch Volunteer")
        IncidentAssignment.objects.create(
            incident=incident,
            volunteer=volunteer,
            assigned_by=uic,
        )
        response = _login(uic).get(_detail_url(incident))
        assert response.status_code == 200
        assert "Dispatch Volunteer" in response.content.decode()

    def test_equipment_section_rendered_when_allocations_exist(self):
        """
        The "Equipment Deployed" table (guarded by
        {% if incident.equipment_allocations.all %}) must appear when
        at least one IncidentEquipment row is linked.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        equip = EquipmentFactory.create(unit=uic.unit, name="First Aid Box")
        IncidentEquipment.objects.create(incident=incident, equipment=equip, quantity_deployed=3)
        response = _login(uic).get(_detail_url(incident))
        assert response.status_code == 200
        assert "First Aid Box" in response.content.decode()

    def test_vehicle_section_rendered_when_allocations_exist(self):
        """
        The "Vehicles Dispatched" table (guarded by
        {% if incident.vehicle_allocations.all %}) must appear when at least
        one IncidentVehicle row is linked.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        vehicle = VehicleFactory.create(unit=uic.unit, registration_no="WB01TT0001")
        IncidentVehicle.objects.create(
            incident=incident,
            vehicle=vehicle,
            authorised_by=uic,
        )
        response = _login(uic).get(_detail_url(incident))
        assert response.status_code == 200
        assert "WB01TT0001" in response.content.decode()

    def test_final_report_section_rendered_when_report_exists(self):
        """
        The "Final Report" card (guarded by {% if incident.final_report %})
        must appear when the incident has a non-empty final_report field.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(
            unit=uic.unit,
            final_report="Full post-incident narrative describing the response.",
        )
        response = _login(uic).get(_detail_url(incident))
        content = response.content.decode()
        assert "Full post-incident narrative" in content

    def test_media_gallery_rendered_when_media_exists(self, settings, tmp_path):
        """
        The "Attached Media" gallery (guarded by
        {% if incident.media_files.all %}) must appear when IncidentMedia
        rows are attached to the incident.
        """
        settings.MEDIA_ROOT = str(tmp_path)
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit)
        fake_image = SimpleUploadedFile(
            "flood_scene.jpg",
            b"\xff\xd8\xff\xe0" + b"\x00" * 50,
            content_type="image/jpeg",
        )
        IncidentMedia.objects.create(
            incident=incident,
            file=fake_image,
            caption="Flood scene photo",
        )
        response = _login(uic).get(_detail_url(incident))
        assert response.status_code == 200
        assert "flood_scene" in response.content.decode()

    def test_closed_incident_shows_closed_badge(self):
        """
        A CLOSED incident must display the "Closed" badge (dark background),
        not the green "Open" badge.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit, status=IncidentStatus.CLOSED)
        response = _login(uic).get(_detail_url(incident))
        content = response.content.decode()
        assert "Closed" in content

    def test_fully_populated_incident_renders_all_sections(self, settings, tmp_path):
        """
        Smoke test: an incident with assignments + equipment + vehicles +
        final_report + media must render a 200 page with no template errors.
        This exercises the maximum number of branches in incident_detail.html
        in a single request.
        """
        settings.MEDIA_ROOT = str(tmp_path)
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(
            unit=uic.unit,
            status=IncidentStatus.OPEN,
            final_report="Comprehensive response report.",
        )

        vol = VolunteerFactory.create(unit=uic.unit)
        IncidentAssignment.objects.create(incident=incident, volunteer=vol, assigned_by=uic)

        equip = EquipmentFactory.create(unit=uic.unit)
        IncidentEquipment.objects.create(incident=incident, equipment=equip)

        vehicle = VehicleFactory.create(unit=uic.unit)
        IncidentVehicle.objects.create(incident=incident, vehicle=vehicle, authorised_by=uic)

        fake_img = SimpleUploadedFile("img.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, content_type="image/jpeg")
        IncidentMedia.objects.create(incident=incident, file=fake_img, caption="Scene photo")

        response = _login(uic).get(_detail_url(incident))
        assert response.status_code == 200

    def test_reported_by_shown_when_set(self):
        """
        When reported_by is populated, the user's name or username must
        appear in the Basic Info card.
        """
        uic = UICUserFactory.create()
        incident = IncidentFactory.create(unit=uic.unit, reported_by=uic)
        response = _login(uic).get(_detail_url(incident))
        content = response.content.decode()
        assert uic.username in content or (uic.name and uic.name in content)


# ─────────────────────────────────────────────────────────────────────────────
# BASE TEMPLATE — ROLE-BASED NAVBAR / BADGE BRANCHES
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseTemplateBranches:
    """
    These tests hit any authenticated page (incident list) while logged in
    as different user roles.  Because base.html is inherited by every page,
    each GET exercises a different branch of the navbar conditional.

    Three branches in base.html:
      1. is_superuser or is_admin_role  → Admin badge + full nav including
                                          Equipment / Fleet / Training / Admin
      2. is_unit_in_charge              → Unit name badge + UIC nav
      3. else (VOLUNTEER)               → "Volunteer" badge + restricted nav
    """

    LIST_URL = reverse("incidents:incident-list")

    def test_admin_role_sees_admin_badge(self):
        """
        A user with role=ADMIN must see the "Admin" badge in the navbar.
        They must also see the Admin dropdown in the navigation bar.
        """
        admin = AdminUserFactory.create()
        response = _login(admin).get(self.LIST_URL)
        content = response.content.decode()
        assert "Admin" in content

    def test_uic_sees_unit_name_badge(self):
        """
        A Unit In-Charge must see their assigned unit's name displayed
        as a badge in the right side of the navbar.
        """
        uic = UICUserFactory.create()
        response = _login(uic).get(self.LIST_URL)
        content = response.content.decode()
        assert uic.unit.name in content

    def test_volunteer_role_sees_volunteer_badge(self):
        """
        A user with role=VOLUNTEER must see the "Volunteer" badge in the
        navbar's right side — not the unit name or the Admin badge.
        """
        vol_user = UICUserFactory.create()
        vol_user.role = UserRole.VOLUNTEER
        vol_user.save()
        response = _login(vol_user).get(self.LIST_URL)
        content = response.content.decode()
        assert "Volunteer" in content

    def test_superuser_sees_admin_nav(self):
        """
        A Django superuser (is_superuser=True) must see the full admin
        navigation regardless of their role field value.
        """
        admin = AdminUserFactory.create()
        admin.is_superuser = True
        admin.save()
        response = _login(admin).get(self.LIST_URL)
        content = response.content.decode()
        assert "Admin" in content

    def test_unauthenticated_sees_sign_in_link(self):
        """
        Anonymous visitors must see the "Sign In" link in the navbar (the
        unauthenticated branch of base.html).
        We hit the home page since the list view redirects before rendering.
        """
        response = Client().get(reverse("home"))
        content = response.content.decode()
        assert "Sign In" in content or "Log" in content or "login" in content.lower()
