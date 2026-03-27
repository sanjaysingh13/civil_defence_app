"""
Factory-boy factories for the training app models.

Training          — the "syllabus" definition (name, type).
TrainingInstance  — a specific batch/run of a Training (venue, dates, unit).
"""

from __future__ import annotations

import factory
from factory import Sequence
from factory import SubFactory
from factory.django import DjangoModelFactory

from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.training.models import Training
from civil_defence_app.training.models import TrainingInstance
from civil_defence_app.training.models import TrainingType


class TrainingFactory(DjangoModelFactory[Training]):
    """
    Creates a Training programme definition.

    Training.name has unique=True, so Sequence() ensures each factory call
    produces a distinct name and avoids IntegrityError in tests.
    """

    name = Sequence(lambda n: f"Test Training Programme {n}")
    training_type = TrainingType.BASIC
    description = ""

    class Meta:
        model = Training
        django_get_or_create = ["name"]


class TrainingInstanceFactory(DjangoModelFactory[TrainingInstance]):
    """
    Creates a TrainingInstance (a specific batch of a Training programme).

    The `unit` FK is optional on the model (null=True) — we link it to a
    real Unit by default so tests can filter by unit without extra setup.
    """

    training = SubFactory(TrainingFactory)
    unit = SubFactory(UnitFactory)
    location = factory.Faker("city")
    start_date = factory.Faker("date_object")

    class Meta:
        model = TrainingInstance
