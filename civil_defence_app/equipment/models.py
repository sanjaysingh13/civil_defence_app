"""
Equipment app models.

Civil Defence units hold a variety of equipment — fire hoses, stretchers,
life jackets, search lights, first-aid kits, etc.  Each piece of equipment is:

  • An instance of an EquipmentType (e.g. "Life Jacket with Reflective Panel").
  • Assigned to a Unit (a district).
  • Has a quantity and a status (functional / under repair / disposed).
  • Must be inspected periodically; each inspection generates a
    EquipmentMaintenanceLog entry.
  • Can be allocated to an Incident response via IncidentEquipment (M2M).

The Admin is responsible for the initial seeding and bulk assignment.
The Unit In-Charge maintains the maintenance log.
"""

import calendar
import datetime

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


# ─────────────────────────────────────────────────────────────────────────────
# TIMESTAMP MIXIN
# ─────────────────────────────────────────────────────────────────────────────

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ─────────────────────────────────────────────────────────────────────────────
# CHOICES
# ─────────────────────────────────────────────────────────────────────────────

class EquipmentCategory(models.TextChoices):
    FIRE         = "FIRE",    _("Fire Fighting")
    RESCUE       = "RESCUE",  _("Search & Rescue")
    MEDICAL      = "MED",     _("Medical / First Aid")
    COMM         = "COMM",    _("Communication")
    FLOOD        = "FLOOD",   _("Flood Relief")
    PERSONAL     = "PPE",     _("Personal Protective Equipment")
    OTHER        = "OTHER",   _("Other")


class EquipmentStatus(models.TextChoices):
    FUNCTIONAL  = "OK",      _("Functional")
    REPAIR      = "REPAIR",  _("Under Repair")
    DISPOSED    = "DISPOSED",_("Disposed / Written Off")


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — safe month arithmetic without external libs
# ─────────────────────────────────────────────────────────────────────────────

def add_months(d: datetime.date, months: int) -> datetime.date:
    """
    Add a number of calendar months to a date, clamping the day to the last
    valid day of the resulting month.

    Python's standard library has no built-in for month arithmetic.  Using
    calendar.monthrange avoids importing python-dateutil.

    Examples:
        add_months(date(2026, 1, 31), 1)  → date(2026, 2, 28)  (February clamping)
        add_months(date(2026, 3, 15), 3)  → date(2026, 6, 15)
    """
    # Convert month to 0-indexed, add months, then convert back to 1-indexed.
    # Integer division gives the year overflow; modulo gives the target month.
    m = d.month - 1 + months
    year  = d.year + m // 12
    month = m % 12 + 1
    # calendar.monthrange(year, month) returns (weekday_of_1st, days_in_month).
    # We take min() so that e.g. Jan 31 + 1 month doesn't crash on Feb 31.
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT TYPE
#
# Every physical piece of equipment is an *instance* of an EquipmentType.
# For example, 50 individual life jackets across all units are each an
# Equipment row, all pointing to the single "Life Jacket with Reflective Panel"
# EquipmentType row.
#
# The EquipmentType stores:
#   • What the item is and what it does (description).
#   • How often it must be inspected (scheduled_maintenance_periodicity in months).
#
# Separating type-level metadata from the individual items keeps the DB
# normalised: if the inspection periodicity changes nationally, we update one
# EquipmentType row instead of 1,400 Equipment rows.
# ─────────────────────────────────────────────────────────────────────────────

class EquipmentType(TimeStampedModel):
    """
    A logical classification of equipment (e.g. "Portable Generator Set").

    Each physical Equipment record is an *instance* of an EquipmentType.
    The type defines what the item is, what it does, and how often it must
    be scheduled for maintenance.
    """

    name = models.CharField(
        _("Type Name"),
        max_length=200,
        unique=True,
        help_text=_("Canonical name for this equipment type, e.g. 'Life Jacket with Reflective Panel'."),
    )

    # Equipment category (same vocabulary as Equipment.category so we can
    # filter inventory by category across the type→instance hierarchy).
    category = models.CharField(
        _("Category"),
        max_length=8,
        choices=EquipmentCategory.choices,
        default=EquipmentCategory.OTHER,
    )

    # Human-readable explanation of what this equipment does and why it matters.
    # This is displayed on the inventory and detail pages so any user can
    # understand the item without looking it up externally.
    description = models.TextField(
        _("Description"),
        blank=True,
        default="",
        help_text=_("What this equipment is used for and key operational notes."),
    )

    # How many months between mandatory maintenance/inspection events.
    # Default is 1 month (monthly check) — the most conservative option.
    # The Admin can relax this for simple hand tools (e.g. 6 months for shovels).
    scheduled_maintenance_periodicity = models.PositiveIntegerField(
        _("Maintenance Periodicity (months)"),
        default=1,
        help_text=_(
            "Number of months between scheduled maintenance checks. "
            "Default: 1 month. The system flags items overdue relative to this value."
        ),
    )

    class Meta:
        verbose_name        = _("Equipment Type")
        verbose_name_plural = _("Equipment Types")
        ordering            = ["category", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_category_display()})"


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT
# ─────────────────────────────────────────────────────────────────────────────

class Equipment(TimeStampedModel):
    """
    A single type of equipment held by a Unit.

    'Type' here means a logical item (e.g. "Life Jacket — Adult size") rather
    than a specific serial-numbered physical unit.  The `quantity` field
    tracks how many are available.

    If you need to track individual items (for per-item maintenance history),
    create a separate EquipmentItem model that FKs to this one.
    """

    # ── Type classification ───────────────────────────────────────────────────
    #
    # Each Equipment row is a *physical unit* (individual serial-numbered item).
    # equipment_type points to the EquipmentType that describes what this item
    # is and how often it must be maintained.
    #
    # null=True / blank=True: we make this optional for migration safety —
    # existing items won't have a type until seed_equipment_types assigns them.
    # on_delete=SET_NULL: if an EquipmentType is deleted, the individual items
    # become 'untyped' rather than being cascade-deleted.

    equipment_type = models.ForeignKey(
        "equipment.EquipmentType",
        verbose_name=_("Equipment Type"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_instances",
        help_text=_("The type classification for this physical unit."),
    )

    # Which district unit owns / holds this equipment.
    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Assigned Unit"),
        on_delete=models.PROTECT,
        related_name="equipment_items",
    )

    name = models.CharField(
        _("Equipment Name"),
        max_length=200,
        help_text=_("Descriptive name, e.g. 'Life Jacket (Adult)'"),
    )

    # A unique identifier assigned by the department or manufacturer.
    unique_id = models.CharField(
        _("Unique ID / Asset Tag"),
        max_length=100,
        unique=True,
        help_text=_("Departmental asset tag or serial number"),
    )

    category = models.CharField(
        _("Category"),
        max_length=8,
        choices=EquipmentCategory.choices,
        default=EquipmentCategory.OTHER,
    )

    quantity = models.PositiveIntegerField(
        _("Quantity"),
        default=1,
        help_text=_("Number of units of this equipment item"),
    )

    status = models.CharField(
        _("Status"),
        max_length=8,
        choices=EquipmentStatus.choices,
        default=EquipmentStatus.FUNCTIONAL,
    )

    # ── Functional Flag ───────────────────────────────────────────────────────
    #
    # A simple boolean that records whether THIS specific physical unit is
    # currently working.  This is separate from `status` (which can also track
    # DISPOSED items) and is set during the bulk import from the equipment
    # register.
    #
    # The seeding logic assigns is_functional=True to the *later* serial
    # numbers within each unit+type group, on the assumption that lower serial
    # numbers were procured earlier and are therefore more likely to be worn
    # out.  e.g. if Total=5 and Functional=3 → SL 001-002 = False, 003-005 = True.

    is_functional = models.BooleanField(
        _("Is Functional"),
        default=True,
        help_text=_(
            "True if this specific item is currently in working order. "
            "False means it is non-functional / under repair."
        ),
    )

    # ── Maintenance Schedule ──────────────────────────────────────────────────

    last_check_date = models.DateField(
        _("Last Inspection Date"),
        null=True,
        blank=True,
    )

    next_due_date = models.DateField(
        _("Next Inspection Due"),
        null=True,
        blank=True,
    )

    notes = models.TextField(_("Notes"), blank=True, default="")

    class Meta:
        verbose_name        = _("Equipment")
        verbose_name_plural = _("Equipment Items")
        ordering            = ["unit", "category", "name"]

    def __str__(self) -> str:
        return f"{self.name} [{self.unique_id}] — {self.unit.name}"


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT MAINTENANCE LOG
#
# Each inspection of an equipment item creates one row here.
# The Unit In-Charge fills this out periodically and after any incident.
# ─────────────────────────────────────────────────────────────────────────────

class EquipmentMaintenanceLog(TimeStampedModel):
    """
    A record of one inspection / service event for a piece of Equipment.

    By looking at the log entries for a given equipment item you can see its
    complete service history.
    """

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name=_("Equipment"),
        on_delete=models.CASCADE,
        related_name="maintenance_logs",
    )

    check_date = models.DateField(_("Inspection / Service Date"))

    # Who performed or supervised the check.
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Checked By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    status_after_check = models.CharField(
        _("Status After Check"),
        max_length=8,
        choices=EquipmentStatus.choices,
        default=EquipmentStatus.FUNCTIONAL,
    )

    # ── Fitness Check ─────────────────────────────────────────────────────────
    #
    # A simple yes / no result of the inspection.  When the UIC submits the
    # maintenance log form, this value is used to update Equipment.is_functional
    # on the parent equipment item.
    #
    # This is kept separate from status_after_check so the form can present a
    # plain checkbox ("Equipment is fit for service?") rather than a dropdown.

    is_fit = models.BooleanField(
        _("Equipment is Fit"),
        default=True,
        help_text=_(
            "Check if the equipment is fit for service after this inspection. "
            "Saving the log will update the equipment's functional status."
        ),
    )

    remarks = models.TextField(
        _("Remarks"),
        blank=True,
        default="",
        help_text=_("Observations, repairs done, parts replaced, etc."),
    )

    class Meta:
        verbose_name        = _("Equipment Maintenance Log")
        verbose_name_plural = _("Equipment Maintenance Logs")
        ordering            = ["-check_date"]

    def __str__(self) -> str:
        fit_label = "Fit" if self.is_fit else "Not Fit"
        return f"{self.equipment.name} — {self.check_date} ({fit_label})"


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT EQUIPMENT ALLOCATION
#
# Links equipment (and a quantity) to a specific Incident.
# The equipment is 'booked out' for a response and returned after.
# ─────────────────────────────────────────────────────────────────────────────

class IncidentEquipment(TimeStampedModel):
    """
    Allocation of Equipment to an Incident response.

    Tracks how many units of a piece of equipment were deployed and whether
    they have been returned.
    """

    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name=_("Incident"),
        on_delete=models.CASCADE,
        related_name="equipment_allocations",
    )

    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name=_("Equipment"),
        on_delete=models.PROTECT,
        related_name="incident_allocations",
    )

    quantity_deployed = models.PositiveIntegerField(
        _("Quantity Deployed"),
        default=1,
    )

    returned = models.BooleanField(_("Returned"), default=False)

    notes = models.TextField(_("Notes"), blank=True, default="")

    class Meta:
        verbose_name        = _("Incident Equipment Allocation")
        verbose_name_plural = _("Incident Equipment Allocations")

        constraints = [
            models.UniqueConstraint(
                fields=["incident", "equipment"],
                name="unique_equipment_per_incident",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment.name} × {self.quantity_deployed} → {self.incident.title}"
