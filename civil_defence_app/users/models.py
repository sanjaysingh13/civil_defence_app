from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _


# ─────────────────────────────────────────────────────────────────────────────
# USER ROLE CHOICES
#
# Django's TextChoices creates an enum-like class where each member has a
# .value (stored in the DB column) and a .label (shown in forms/admin).
#
# The three roles represent distinct operational levels in the system:
#   ADMIN          → superuser; full access; assigned by IT / system operator
#   UNIT_IN_CHARGE → manages one district unit; logs incidents, dispatches resources
#   VOLUNTEER      → field operative; read-only access to their own records
# ─────────────────────────────────────────────────────────────────────────────

class UserRole(models.TextChoices):
    ADMIN          = "ADMIN",          _("Admin")
    UNIT_IN_CHARGE = "UNIT_IN_CHARGE", _("Unit In-Charge")
    VOLUNTEER      = "VOLUNTEER",      _("Volunteer")


class User(AbstractUser):
    """
    Custom user model for Civil Defence App.

    Extends Django's AbstractUser (which already provides username, password,
    email, is_staff, is_superuser, date_joined, etc.) with:

      name  — single full-name field (replaces the split first_name + last_name
               that don't suit Indian naming conventions)
      role  — one of ADMIN / UNIT_IN_CHARGE / VOLUNTEER
      unit  — FK to the Unit (district) this user is associated with;
               relevant mainly for UNIT_IN_CHARGE accounts
    """

    # Single full-name field — replaces the Django default split-name fields.
    name = CharField(_("Name of User"), blank=True, max_length=255)
    first_name = None  # type: ignore[assignment]
    last_name  = None  # type: ignore[assignment]

    # ── Role ─────────────────────────────────────────────────────────────────
    # CharField with choices stores the short code (e.g. "UNIT_IN_CHARGE")
    # in the DB.  Forms and templates use .get_role_display() to show the
    # human-readable label ("Unit In-Charge").
    role = CharField(
        _("Role"),
        max_length=16,
        choices=UserRole.choices,
        default=UserRole.VOLUNTEER,
        help_text=_("Determines what the user can see and do in the system."),
    )

    # ── Unit assignment ───────────────────────────────────────────────────────
    # ForeignKey (many Users → one Unit) with SET_NULL so deleting a Unit
    # does not cascade-delete user accounts — the users just lose their
    # unit assignment and the field becomes NULL.
    # null=True + blank=True → optional; Admin accounts don't need a unit.
    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Assigned Unit"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_accounts",
        help_text=_(
            "The district unit this user manages / belongs to. "
            "Required for Unit In-Charge accounts."
        ),
    )

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view."""
        return reverse("users:detail", kwargs={"username": self.username})

    # ── Convenience properties ────────────────────────────────────────────────
    # These allow views and templates to check roles with clean attribute access:
    #   {% if request.user.is_unit_in_charge %}  instead of  {% if request.user.role == "UNIT_IN_CHARGE" %}

    @property
    def is_unit_in_charge(self) -> bool:
        """True if this user holds the Unit In-Charge role."""
        return self.role == UserRole.UNIT_IN_CHARGE

    @property
    def is_admin_role(self) -> bool:
        """True if this user holds the Admin role (separate from Django's is_superuser)."""
        return self.role == UserRole.ADMIN
