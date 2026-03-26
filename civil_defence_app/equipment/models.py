"""
Equipment app models.

Civil Defence units hold a variety of equipment — fire hoses, stretchers,
life jackets, search lights, first-aid kits, etc.  Each piece of equipment is:

  • Assigned to a Unit (a district).
  • Has a quantity and a status (functional / under repair / disposed).
  • Must be inspected periodically; each inspection generates a
    EquipmentMaintenanceLog entry.
  • Can be allocated to an Incident response via IncidentEquipment (M2M).

The Admin is responsible for the initial seeding and bulk assignment.
The Unit In-Charge maintains the maintenance log.
"""

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
        return f"{self.equipment.name} — checked on {self.check_date}"


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
