from __future__ import annotations

import factory
from factory import LazyAttribute
from factory import Sequence
from factory import SubFactory
from factory import post_generation
from factory.django import DjangoModelFactory

from civil_defence_app.equipment.models import Equipment
from civil_defence_app.equipment.models import EquipmentCategory
from civil_defence_app.fleet.models import Vehicle
from civil_defence_app.fleet.models import VehicleStatus
from civil_defence_app.fleet.models import VehicleType
from civil_defence_app.incidents.models import Incident
from civil_defence_app.incidents.models import IncidentStatus
from civil_defence_app.incidents.models import IncidentType
from civil_defence_app.personnel.models import Unit
from civil_defence_app.personnel.models import Volunteer
from civil_defence_app.users.models import User
from civil_defence_app.users.models import UserRole


class UnitFactory(DjangoModelFactory[Unit]):
    """
    Creates a Unit (district).  The slug is derived from the name so both
    fields remain consistent and URL-safe without manual effort.

    Sequence() appends an incrementing integer to the name to guarantee
    uniqueness across test runs — important because Unit.name has unique=True.
    """

    name = Sequence(lambda n: f"TEST DISTRICT {n}")
    slug = LazyAttribute(lambda o: o.name.lower().replace(" ", "-"))

    class Meta:
        model = Unit
        django_get_or_create = ["name"]


class VolunteerFactory(DjangoModelFactory[Volunteer]):
    """
    Creates an active Volunteer belonging to a Unit.

    serial_no is unique within a unit (composite unique constraint), so we
    use Sequence to avoid collisions when multiple volunteers share a unit
    in a single test.
    """

    unit = SubFactory(UnitFactory)
    serial_no = Sequence(lambda n: f"V{n:04d}")
    name = factory.Faker("name")
    is_active = True

    class Meta:
        model = Volunteer


class EquipmentFactory(DjangoModelFactory[Equipment]):
    """
    Creates a functional Equipment item belonging to a Unit.

    status="OK" matches EquipmentStatus.FUNCTIONAL, which is what the
    IncidentDispatchForm's queryset filter expects (filter(status="OK")).

    unique_id has a unique=True constraint with no blank/null allowed, so
    Sequence() guarantees a distinct asset-tag string per factory call.
    """

    unit = SubFactory(UnitFactory)
    name = Sequence(lambda n: f"Equipment Item {n}")
    unique_id = Sequence(lambda n: f"ASSET-{n:06d}")
    category = EquipmentCategory.RESCUE
    status = "OK"
    # is_functional mirrors status="OK" — a working item is functional.
    # Tests that specifically need a non-functional item can override this.
    is_functional = True
    quantity = 2

    class Meta:
        model = Equipment


class VehicleFactory(DjangoModelFactory[Vehicle]):
    """
    Creates an available Vehicle belonging to a Unit.

    registration_no has a unique constraint, so Sequence avoids collisions.
    status="AVAILABLE" matches VehicleStatus.AVAILABLE, the filter used
    by IncidentDispatchForm.
    """

    unit = SubFactory(UnitFactory)
    registration_no = Sequence(lambda n: f"WB01AB{n:04d}")
    vehicle_type = VehicleType.JEEP
    status = VehicleStatus.AVAILABLE

    class Meta:
        model = Vehicle


class IncidentFactory(DjangoModelFactory[Incident]):
    """
    Creates an open Incident for a Unit.

    incident_number is intentionally left empty here — the model's save()
    override auto-generates it.  Tests that need to verify the number can
    simply check incident.incident_number after saving.
    """

    unit = SubFactory(UnitFactory)
    title = factory.Faker("sentence", nb_words=5)
    incident_type = IncidentType.FLOOD
    status = IncidentStatus.OPEN

    class Meta:
        model = Incident


class AdminUserFactory(DjangoModelFactory[User]):
    """
    Creates a User with role=ADMIN and staff permissions.

    The password post_generation hook uses a simple test password so tests
    can log in with client.login(username=…, password="testpass123").
    skip_postgeneration_save=True avoids a redundant extra SQL UPDATE after
    save() — the password hook calls save() itself when create=True.
    """

    username = Sequence(lambda n: f"admin_user_{n}")
    email = factory.Faker("email")
    name = factory.Faker("name")
    role = UserRole.ADMIN
    is_staff = True

    @post_generation
    def password(self: User, create: bool, extracted: str | None, **kwargs):
        self.set_password(extracted or "testpass123")
        if create:
            self.save()

    class Meta:
        model = User
        django_get_or_create = ["username"]
        skip_postgeneration_save = True


class UICUserFactory(DjangoModelFactory[User]):
    """
    Creates a User with role=UNIT_IN_CHARGE assigned to a Unit.

    The view's UnitInChargeRequiredMixin checks both role == UNIT_IN_CHARGE
    AND user.unit is not None — this factory satisfies both conditions.
    """

    username = Sequence(lambda n: f"uic_user_{n}")
    email = factory.Faker("email")
    name = factory.Faker("name")
    role = UserRole.UNIT_IN_CHARGE
    unit = SubFactory(UnitFactory)

    @post_generation
    def password(self: User, create: bool, extracted: str | None, **kwargs):
        self.set_password(extracted or "testpass123")
        if create:
            self.save()

    class Meta:
        model = User
        django_get_or_create = ["username"]
        skip_postgeneration_save = True
