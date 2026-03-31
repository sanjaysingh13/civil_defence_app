"""Smoke tests for training ModelAdmin callables."""

from __future__ import annotations

import pytest
from django.contrib.admin.sites import AdminSite

from civil_defence_app.training.admin import TrainingAdmin
from civil_defence_app.training.models import Training
from civil_defence_app.training.tests.factories import TrainingFactory
from civil_defence_app.training.tests.factories import TrainingInstanceFactory

pytestmark = pytest.mark.django_db


def test_training_admin_instance_count():
    """list_display helper counts related TrainingInstance rows."""
    training = TrainingFactory.create()
    TrainingInstanceFactory.create(training=training)
    TrainingInstanceFactory.create(training=training)
    ma = TrainingAdmin(Training, AdminSite())
    assert ma.instance_count(training) == 2
