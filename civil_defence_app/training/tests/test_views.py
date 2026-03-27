"""
Tests for training/views.py

Four views:
  TrainingListView         — table of all training programmes with instance counts.
  TrainingDetailView       — detail page for one programme (stub).
  TrainingInstanceListView — paginated table of all batches with programme/unit filters.
  TrainingInstanceDetailView — detail page for one batch (stub).
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory

from .factories import TrainingFactory
from .factories import TrainingInstanceFactory

pytestmark = pytest.mark.django_db


def _login(user) -> Client:
    c = Client()
    c.login(username=user.username, password="testpass123")
    return c


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingListView:
    url = reverse("training:training-list")

    def test_unauthenticated_redirects(self):
        """Anonymous visitors must be redirected to the login page."""
        response = Client().get(self.url)
        assert response.status_code == 302
        assert "login" in response["Location"]

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the training list."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert response.status_code == 200

    def test_programme_name_appears_in_list(self):
        """
        Training programmes saved to the database must appear in the HTML
        so users can browse the catalogue.
        """
        uic = UICUserFactory.create()
        training = TrainingFactory.create(name="Aapda Mitra Advanced Course")
        response = _login(uic).get(self.url)
        assert training.name in response.content.decode()

    def test_instance_count_annotation_works(self):
        """
        Each Training is annotated with `instance_count` — the number of
        batches run for that programme.  We verify the annotation returns
        the correct count after creating two instances.
        """
        uic = UICUserFactory.create()
        training = TrainingFactory.create()
        TrainingInstanceFactory.create(training=training)
        TrainingInstanceFactory.create(training=training)
        response = _login(uic).get(self.url)
        qs = response.context["trainings"]
        this = next(t for t in qs if t.pk == training.pk)
        assert this.instance_count == 2

    def test_context_has_trainings(self):
        """The 'trainings' context variable must be present."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert "trainings" in response.context


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view a training programme detail page."""
        uic = UICUserFactory.create()
        training = TrainingFactory.create()
        url = reverse("training:training-detail", kwargs={"pk": training.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_nonexistent_pk_returns_404(self):
        """Non-existent training PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("training:training-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING INSTANCE LIST VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingInstanceListView:
    url = reverse("training:instance-list")

    def test_unauthenticated_redirects(self):
        """Anonymous visitors must be redirected to login."""
        response = Client().get(self.url)
        assert response.status_code == 302

    def test_authenticated_gets_200(self):
        """Any logged-in user may view the instance list."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert response.status_code == 200

    def test_instance_location_appears_in_list(self):
        """
        A training instance's location must appear in the rendered HTML
        so users can identify where the batch was held.
        """
        uic = UICUserFactory.create()
        instance = TrainingInstanceFactory.create(location="Circuit House Alipurduar")
        response = _login(uic).get(self.url)
        assert "Circuit House Alipurduar" in response.content.decode()

    def test_filter_by_training_programme(self):
        """
        ?training=<pk> must show only instances of that specific programme.
        Instances of other programmes must not appear in the filtered result.
        """
        uic = UICUserFactory.create()
        training_a = TrainingFactory.create()
        training_b = TrainingFactory.create()
        inst_a = TrainingInstanceFactory.create(training=training_a, location="Venue A")
        TrainingInstanceFactory.create(training=training_b, location="Venue B")
        response = _login(uic).get(self.url, {"training": training_a.pk})
        content = response.content.decode()
        assert inst_a.location in content
        assert "Venue B" not in content

    def test_filter_by_unit(self):
        """
        ?unit=<pk> must show only instances organised by that unit.
        """
        uic = UICUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        inst_a = TrainingInstanceFactory.create(unit=unit_a, location="Alpha Venue")
        TrainingInstanceFactory.create(unit=unit_b, location="Beta Venue")
        response = _login(uic).get(self.url, {"unit": unit_a.pk})
        content = response.content.decode()
        assert inst_a.location in content
        assert "Beta Venue" not in content

    def test_context_has_filter_data(self):
        """
        The template needs `trainings` and `units` in context to populate
        the filter dropdowns correctly.
        """
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert "trainings" in response.context
        assert "units" in response.context


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING INSTANCE DETAIL VIEW
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingInstanceDetailView:

    def test_authenticated_gets_200(self):
        """Any logged-in user may view a training instance detail page."""
        uic = UICUserFactory.create()
        instance = TrainingInstanceFactory.create()
        url = reverse("training:instance-detail", kwargs={"pk": instance.pk})
        response = _login(uic).get(url)
        assert response.status_code == 200

    def test_nonexistent_pk_returns_404(self):
        """Non-existent instance PK must return HTTP 404."""
        uic = UICUserFactory.create()
        url = reverse("training:instance-detail", kwargs={"pk": 999999})
        response = _login(uic).get(url)
        assert response.status_code == 404
