from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

# ─────────────────────────────────────────────────────────────────────────────
# TELEPHONE VALIDATION (MODEL LAYER)
#
# RegexValidator runs only when the field is non-empty if blank=True — Django
# skips validators for empty values in CharField.clean(). Signup/admin forms
# require 10 digits; optional blank in the model keeps legacy rows valid.
# ─────────────────────────────────────────────────────────────────────────────

TELEPHONE_VALIDATOR = RegexValidator(
    regex=r"^\d{10}$",
    message=_("Enter exactly 10 digits (no spaces or dashes)."),
)


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
    ADMIN = "ADMIN", _("Admin")
    UNIT_IN_CHARGE = "UNIT_IN_CHARGE", _("Unit In-Charge")
    VOLUNTEER = "VOLUNTEER", _("Volunteer")


class User(AbstractUser):
    """
    Custom user model for Civil Defence App.

    Extends Django's AbstractUser (username, password, email, first_name,
    last_name, is_staff, is_superuser, date_joined, etc.) with:

      name       — optional legacy / display full name (can mirror first + last)
      rank       — user's rank or designation
      telephone  — 10-digit contact number
      role       — ADMIN / UNIT_IN_CHARGE / VOLUNTEER
      unit       — FK to the district Unit (mainly for Unit In-Charge)
    """

    # Optional full-name string kept for templates, search, and older data;
    # signup can set this from first_name + last_name for consistency.
    name = CharField(_("Name of User"), blank=True, max_length=255)

    # ── Rank & telephone (Civil Defence profile) ───────────────────────────
    rank = CharField(_("Rank"), max_length=128, blank=True)
    telephone = CharField(
        _("Telephone"),
        max_length=10,
        blank=True,
        validators=[TELEPHONE_VALIDATOR],
    )

    # ── Role ─────────────────────────────────────────────────────────────────
    # CharField with choices stores the short code (e.g. "UNIT_IN_CHARGE")
    # in the DB.  Forms and templates use .get_role_display() to show the
    # human-readable label ("Unit In-Charge").
    role = CharField(
        _("Role"),
        max_length=16,
        choices=UserRole,
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
            "Required for Unit In-Charge accounts.",
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
