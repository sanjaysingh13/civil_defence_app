"""HTTP tests for training coverage + unit summary views."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import (
    AdminUserFactory,
    UICUserFactory,
    UnitFactory,
)
from civil_defence_app.personnel.models import Volunteer
from civil_defence_app.training.models import (
    Training,
    TrainingAttendance,
    TrainingInstance,
    TrainingType,
)

pytestmark = pytest.mark.django_db


def _login(user):
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


def _coverage_url():
    return reverse("training:training-coverage-summary")


def _unit_summary_url(unit):
    return reverse("training:training-unit-summary", kwargs={"unit_pk": unit.pk})


class TestTrainingCoverageSummaryView:
    def test_anonymous_redirects(self):
        r = Client().get(_coverage_url())
        assert r.status_code == 302
        assert "login" in r["Location"]

    def test_admin_gets_200(self):
        admin = AdminUserFactory.create()
        r = _login(admin).get(_coverage_url())
        assert r.status_code == 200

    def test_uic_redirects_to_own_unit(self):
        unit = UnitFactory.create()
        uic  = UICUserFactory.create(unit=unit)
        r = _login(uic).get(_coverage_url())
        assert r.status_code == 302
        assert str(unit.pk) in r["Location"]

    def test_context_has_grand_totals(self):
        unit = UnitFactory.create()
        Volunteer.objects.create(unit=unit, serial_no="S001", name="Test Vol", is_active=True)
        admin = AdminUserFactory.create()
        r = _login(admin).get(_coverage_url())
        assert r.status_code == 200
        assert "grand_volunteers" in r.context


class TestTrainingUnitSummaryView:
    def test_anonymous_redirects(self):
        unit = UnitFactory.create()
        r = Client().get(_unit_summary_url(unit))
        assert r.status_code == 302

    def test_uic_own_unit_ok(self):
        unit = UnitFactory.create()
        uic  = UICUserFactory.create(unit=unit)
        r = _login(uic).get(_unit_summary_url(unit))
        assert r.status_code == 200

    def test_uic_other_unit_403(self):
        ua = UnitFactory.create()
        ub = UnitFactory.create()
        uic = UICUserFactory.create(unit=ua)
        r = _login(uic).get(_unit_summary_url(ub))
        assert r.status_code == 403

    def test_shows_programme_with_attendance(self):
        unit = UnitFactory.create()
        tr = Training.objects.create(
            name="Civil Defence Basic Training",
            training_type=TrainingType.BASIC,
        )
        inst = TrainingInstance.objects.create(training=tr, unit=unit, location="X")
        vol = Volunteer.objects.create(unit=unit, serial_no="Z001", name="A", is_active=True)
        TrainingAttendance.objects.create(volunteer=vol, training_instance=inst)

        admin = AdminUserFactory.create()
        r = _login(admin).get(_unit_summary_url(unit))
        assert r.status_code == 200
        assert "Civil Defence Basic Training" in r.content.decode()
