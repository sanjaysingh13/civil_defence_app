"""Tests for training/forms.py — batch form validation."""

from __future__ import annotations

import pytest

from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.training.forms import TrainingInstanceWithVolunteersForm
from civil_defence_app.training.tests.factories import TrainingFactory

pytestmark = pytest.mark.django_db


def test_end_date_before_start_date_is_invalid():
    """clean() rejects end_date strictly before start_date when both are set."""
    uic = UICUserFactory.create()
    training = TrainingFactory.create()
    form = TrainingInstanceWithVolunteersForm(
        data={
            "training": training.pk,
            "start_date": "2026-06-10",
            "end_date": "2026-06-01",
            "volunteers": [],
        },
        user=uic,
    )
    assert not form.is_valid()
    assert "__all__" in form.errors or any(
        "End date cannot be before start date" in str(e) for e in form.non_field_errors()
    )


def test_same_day_start_and_end_is_valid():
    uic = UICUserFactory.create()
    training = TrainingFactory.create()
    from civil_defence_app.incidents.tests.factories import VolunteerFactory

    vol = VolunteerFactory.create(unit=uic.unit)
    form = TrainingInstanceWithVolunteersForm(
        data={
            "training": training.pk,
            "start_date": "2026-06-10",
            "end_date": "2026-06-10",
            "volunteers": [vol.pk],
        },
        user=uic,
    )
    assert form.is_valid(), form.errors
