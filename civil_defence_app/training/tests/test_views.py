"""
Tests for training/views.py — programme list/detail, instance list/detail,
coverage summaries, and web workflows (programme + batch creation, volunteer search).
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from civil_defence_app.incidents.tests.factories import AdminUserFactory
from civil_defence_app.incidents.tests.factories import UICUserFactory
from civil_defence_app.incidents.tests.factories import UnitFactory
from civil_defence_app.incidents.tests.factories import VolunteerFactory
from civil_defence_app.training.models import TrainingAttendance
from civil_defence_app.users.models import User
from civil_defence_app.users.models import UserRole

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

    def test_admin_instance_count_is_global(self):
        """Admins see batch counts across all organising units."""
        admin = AdminUserFactory.create()
        training = TrainingFactory.create()
        TrainingInstanceFactory.create(training=training)
        TrainingInstanceFactory.create(training=training)
        response = _login(admin).get(self.url)
        qs = response.context["trainings"]
        this = next(t for t in qs if t.pk == training.pk)
        assert this.instance_count == 2

    def test_uic_instance_count_is_scoped_to_own_unit(self):
        """UICs see instance_count only for batches organised by their unit."""
        unit = UnitFactory.create()
        other_unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        training = TrainingFactory.create()
        TrainingInstanceFactory.create(training=training, unit=unit)
        TrainingInstanceFactory.create(training=training, unit=other_unit)
        response = _login(uic).get(self.url)
        qs = response.context["trainings"]
        this = next(t for t in qs if t.pk == training.pk)
        assert this.instance_count == 1

    def test_context_has_trainings(self):
        """The 'trainings' context variable must be present."""
        uic = UICUserFactory.create()
        response = _login(uic).get(self.url)
        assert "trainings" in response.context

    def test_volunteer_role_sees_global_instance_counts(self):
        """
        Users who are not Admin and not UIC (e.g. VOLUNTEER) use the fallback
        queryset: full statewide instance counts for the catalogue.
        """
        vol_user = User.objects.create_user(username="vol_list", password="testpass123")
        vol_user.role = UserRole.VOLUNTEER
        vol_user.save()
        training = TrainingFactory.create()
        TrainingInstanceFactory.create(training=training)
        TrainingInstanceFactory.create(training=training)
        response = _login(vol_user).get(self.url)
        qs = response.context["trainings"]
        this = next(t for t in qs if t.pk == training.pk)
        assert this.instance_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING PROGRAMME CREATE (Admin only)
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingProgrammeCreateView:
    url = reverse("training:training-programme-create")

    def test_admin_gets_200(self):
        admin = AdminUserFactory.create()
        r = _login(admin).get(self.url)
        assert r.status_code == 200

    def test_uic_gets_403(self):
        uic = UICUserFactory.create()
        r = _login(uic).get(self.url)
        assert r.status_code == 403

    def test_post_creates_programme(self):
        admin = AdminUserFactory.create()
        r = _login(admin).post(
            self.url,
            {
                "name": "Web-created programme",
                "training_type": "BASIC",
                "description": "From test",
            },
        )
        assert r.status_code == 302
        from civil_defence_app.training.models import Training

        assert Training.objects.filter(name="Web-created programme").exists()


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING INSTANCE CREATE + VOLUNTEER SEARCH
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingInstanceCreateView:
    url = reverse("training:training-instance-create")

    def test_get_form_renders_with_is_admin_in_context(self):
        """GET must run get_context_data (is_admin flag for template branching)."""
        admin = AdminUserFactory.create()
        r = _login(admin).get(self.url)
        assert r.status_code == 200
        assert r.context["is_admin"] is True

    def test_uic_get_renders_is_admin_false(self):
        uic = UICUserFactory.create()
        r = _login(uic).get(self.url)
        assert r.status_code == 200
        assert r.context["is_admin"] is False

    def test_volunteer_user_gets_403(self):
        vol_user = User.objects.create_user(username="volonly", password="testpass123")
        vol_user.role = UserRole.VOLUNTEER
        vol_user.save()
        r = _login(vol_user).get(self.url)
        assert r.status_code == 403

    def test_uic_post_creates_batch_and_attendance(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        training = TrainingFactory.create()
        vol = VolunteerFactory.create(unit=unit, name="Searchable Volunteer")
        client = _login(uic)
        r = client.post(
            self.url,
            {
                "training": training.pk,
                "location": "Community Hall",
                "start_date": "2026-03-01",
                "end_date": "2026-03-05",
                "volunteers": [vol.pk],
            },
        )
        assert r.status_code == 302
        inst = TrainingAttendance.objects.get(volunteer=vol).training_instance
        assert inst.unit_id == unit.pk
        assert inst.location == "Community Hall"

    def test_admin_post_creates_batch_for_selected_unit(self):
        admin = AdminUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        training = TrainingFactory.create()
        vol_b = VolunteerFactory.create(unit=unit_b)
        client = _login(admin)
        r = client.post(
            self.url,
            {
                "training": training.pk,
                "unit": unit_b.pk,
                "location": "State HQ",
                "volunteers": [vol_b.pk],
            },
        )
        assert r.status_code == 302
        inst = TrainingAttendance.objects.get(volunteer=vol_b).training_instance
        assert inst.unit_id == unit_b.pk


class TestVolunteerSearchView:
    url = reverse("training:volunteer-search")

    def test_empty_query_returns_empty_json(self):
        """GET without q or q= whitespace hits early JsonResponse (no DB filter)."""
        uic = UICUserFactory.create()
        r = _login(uic).get(self.url, {"q": ""})
        assert r.status_code == 200
        assert r.json() == {"results": []}

    def test_volunteer_role_gets_403_json(self):
        """Authenticated volunteer cannot use staff autocomplete — JSON 403."""
        vol_user = User.objects.create_user(username="volsearch", password="testpass123")
        vol_user.role = UserRole.VOLUNTEER
        vol_user.save()
        r = _login(vol_user).get(self.url, {"q": "x"})
        assert r.status_code == 403
        assert r.json()["detail"] == "forbidden"

    def test_anonymous_redirects(self):
        r = Client().get(self.url, {"q": "ab"})
        assert r.status_code == 302

    def test_uic_search_scoped_to_unit(self):
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        VolunteerFactory.create(unit=unit, name="UniqueAlphaNameXYZ")
        VolunteerFactory.create(name="UniqueBetaNameZZZ")
        r = _login(uic).get(self.url, {"q": "UniqueAlpha"})
        assert r.status_code == 200
        data = r.json()
        labels = " ".join(x["label"] for x in data["results"])
        assert "UniqueAlphaNameXYZ" in labels
        assert "UniqueBetaNameZZZ" not in labels

    def test_admin_search_sees_all_units(self):
        admin = AdminUserFactory.create()
        ua = UnitFactory.create()
        ub = UnitFactory.create()
        va = VolunteerFactory.create(unit=ua, name="GammaAllUnitsA")
        VolunteerFactory.create(unit=ub, name="GammaAllUnitsB")
        r = _login(admin).get(self.url, {"q": "GammaAllUnits"})
        assert r.status_code == 200
        ids = {x["id"] for x in r.json()["results"]}
        assert va.pk in ids


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

    def test_instance_location_appears_when_same_unit_as_uic(self):
        """
        A UIC only sees batches for their unit; the location must appear when
        the instance belongs to that unit.
        """
        unit = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit)
        TrainingInstanceFactory.create(
            unit=unit,
            location="Circuit House Alipurduar",
        )
        response = _login(uic).get(self.url)
        assert "Circuit House Alipurduar" in response.content.decode()

    def test_filter_by_training_programme_admin(self):
        """
        ?training=<pk> must show only instances of that specific programme
        (admin sees all units).
        """
        admin = AdminUserFactory.create()
        training_a = TrainingFactory.create()
        training_b = TrainingFactory.create()
        inst_a = TrainingInstanceFactory.create(training=training_a, location="Venue A")
        TrainingInstanceFactory.create(training=training_b, location="Venue B")
        response = _login(admin).get(self.url, {"training": training_a.pk})
        content = response.content.decode()
        assert inst_a.location in content
        assert "Venue B" not in content

    def test_filter_by_unit_admin(self):
        """
        ?unit=<pk> must show only instances organised by that unit (admin only).
        """
        admin = AdminUserFactory.create()
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        inst_a = TrainingInstanceFactory.create(unit=unit_a, location="Alpha Venue")
        TrainingInstanceFactory.create(unit=unit_b, location="Beta Venue")
        response = _login(admin).get(self.url, {"unit": unit_a.pk})
        content = response.content.decode()
        assert inst_a.location in content
        assert "Beta Venue" not in content

    def test_uic_sees_only_own_unit_batches(self):
        unit_a = UnitFactory.create()
        unit_b = UnitFactory.create()
        uic = UICUserFactory.create(unit=unit_a)
        TrainingInstanceFactory.create(unit=unit_a, location="Our Batch")
        TrainingInstanceFactory.create(unit=unit_b, location="Other Batch")
        response = _login(uic).get(self.url)
        content = response.content.decode()
        assert "Our Batch" in content
        assert "Other Batch" not in content

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
