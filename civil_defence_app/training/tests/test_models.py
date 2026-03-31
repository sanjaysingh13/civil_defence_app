"""Tests for training/models.py — string representations and edge cases."""

from __future__ import annotations

import pytest

from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VolunteerFactory
from civil_defence_app.training.models import Training
from civil_defence_app.training.models import TrainingAttendance
from civil_defence_app.training.models import TrainingInstance
from civil_defence_app.training.models import TrainingType
from civil_defence_app.training.tests.factories import TrainingFactory
from civil_defence_app.training.tests.factories import TrainingInstanceFactory

pytestmark = pytest.mark.django_db


def test_training_str_includes_type_display():
    t = Training.objects.create(
        name="Basic Course",
        training_type=TrainingType.BASIC,
    )
    assert "Basic Course" in str(t)
    assert "Basic" in str(t) or "Foundation" in str(t)


def test_training_instance_str_undated_and_unknown_venue():
    tr = TrainingFactory.create(name="Prog A")
    inst = TrainingInstance.objects.create(
        training=tr,
        unit=None,
        location="",
        start_date=None,
    )
    s = str(inst)
    assert "Prog A" in s
    assert "undated" in s
    assert "Unknown venue" in s


def test_training_instance_str_with_dates():
    from datetime import date

    tr = TrainingFactory.create(name="Prog B")
    unit = UnitFactory.create()
    inst = TrainingInstance.objects.create(
        training=tr,
        unit=unit,
        location="Hall",
        start_date=date(2024, 1, 15),
    )
    assert "Prog B" in str(inst)
    assert "Hall" in str(inst)
    assert "2024" in str(inst)


def test_training_attendance_str():
    tr = TrainingFactory.create()
    unit = UnitFactory.create()
    inst = TrainingInstanceFactory.create(training=tr, unit=unit)
    vol = VolunteerFactory.create(unit=unit, name="Pat Citizen")
    att = TrainingAttendance.objects.create(volunteer=vol, training_instance=inst)
    assert "Pat Citizen" in str(att)
    assert str(inst) in str(att) or "Prog" in str(att)
