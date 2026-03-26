"""
Fleet app models.

The Civil Defence fleet consists of vehicles used in emergency responses —
ambulances, fire trucks, jeeps, motorcycles, boats, etc.

Paralleling the Equipment app, each Vehicle:
  • Belongs to a Unit (district).
  • Has a status: Available / Deployed / Under Maintenance.
  • Gets a maintenance log entry for each service / inspection.
  • Can be allocated to an Incident via IncidentVehicle.

The Unit In-Charge manages day-to-day operations; the Admin does initial
seeding and unit assignments.
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

class VehicleType(models.TextChoices):
    AMBULANCE   = "AMBULANCE",  _("Ambulance")
    FIRE_TRUCK  = "FIRE",       _("Fire Truck")
    JEEP        = "JEEP",       _("Jeep / SUV")
    MINI_BUS    = "MINIBUS",    _("Mini Bus")
    MOTORCYCLE  = "MOTO",       _("Motorcycle")
    BOAT        = "BOAT",       _("Rescue Boat")
    TRUCK       = "TRUCK",      _("Truck / Lorry")
    OTHER       = "OTHER",      _("Other")


class VehicleStatus(models.TextChoices):
    AVAILABLE   = "AVAILABLE",    _("Available")
    DEPLOYED    = "DEPLOYED",     _("Deployed / In Use")
    MAINTENANCE = "MAINTENANCE",  _("Under Maintenance")
    DISPOSED    = "DISPOSED",     _("Disposed / Written Off")


# ─────────────────────────────────────────────────────────────────────────────
# VEHICLE
# ─────────────────────────────────────────────────────────────────────────────

class Vehicle(TimeStampedModel):
    """
    A single vehicle in the Civil Defence fleet.

    Each vehicle is uniquely identified by its government registration number
    (e.g. "WB 75 AB 1234").  The `unit` FK tells us which district garage
    it is parked at / assigned to.
    """

    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Assigned Unit"),
        on_delete=models.PROTECT,
        related_name="vehicles",
    )

    vehicle_type = models.CharField(
        _("Vehicle Type"),
        max_length=10,
        choices=VehicleType.choices,
        default=VehicleType.OTHER,
    )

    registration_no = models.CharField(
        _("Registration Number"),
        max_length=20,
        unique=True,
        help_text=_("Government registration plate, e.g. WB 75 AB 1234"),
    )

    # Seating / load capacity (persons or tonnes depending on type).
    capacity = models.PositiveSmallIntegerField(
        _("Capacity"),
        default=0,
        help_text=_("Passenger seats or load capacity in kg"),
    )

    status = models.CharField(
        _("Status"),
        max_length=12,
        choices=VehicleStatus.choices,
        default=VehicleStatus.AVAILABLE,
    )

    # ── Maintenance Schedule ──────────────────────────────────────────────────

    last_service_date = models.DateField(
        _("Last Service Date"),
        null=True,
        blank=True,
    )

    next_service_due = models.DateField(
        _("Next Service Due"),
        null=True,
        blank=True,
    )

    notes = models.TextField(_("Notes"), blank=True, default="")

    class Meta:
        verbose_name        = _("Vehicle")
        verbose_name_plural = _("Vehicles")
        ordering            = ["unit", "vehicle_type", "registration_no"]

    def __str__(self) -> str:
        return f"{self.get_vehicle_type_display()} {self.registration_no} — {self.unit.name}"


# ─────────────────────────────────────────────────────────────────────────────
# VEHICLE MAINTENANCE LOG
# ─────────────────────────────────────────────────────────────────────────────

class VehicleMaintenanceLog(TimeStampedModel):
    """
    A record of one service / inspection event for a Vehicle.

    The Unit In-Charge or Admin creates a log entry after each service.
    Querying the logs for a vehicle gives its complete service history.
    """

    vehicle = models.ForeignKey(
        "fleet.Vehicle",
        verbose_name=_("Vehicle"),
        on_delete=models.CASCADE,
        related_name="maintenance_logs",
    )

    service_date = models.DateField(_("Service / Inspection Date"))

    serviced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Logged By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    status_after_service = models.CharField(
        _("Status After Service"),
        max_length=12,
        choices=VehicleStatus.choices,
        default=VehicleStatus.AVAILABLE,
    )

    odometer_km = models.PositiveIntegerField(
        _("Odometer Reading (km)"),
        null=True,
        blank=True,
    )

    remarks = models.TextField(
        _("Remarks"),
        blank=True,
        default="",
        help_text=_("Work done, parts replaced, issues found, etc."),
    )

    class Meta:
        verbose_name        = _("Vehicle Maintenance Log")
        verbose_name_plural = _("Vehicle Maintenance Logs")
        ordering            = ["-service_date"]

    def __str__(self) -> str:
        return f"{self.vehicle.registration_no} — serviced on {self.service_date}"


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT VEHICLE ALLOCATION
#
# Links a Vehicle to a specific Incident response.
# ─────────────────────────────────────────────────────────────────────────────

class IncidentVehicle(TimeStampedModel):
    """
    Allocation of a Vehicle to an Incident response.

    Tracks dispatch time, return time, and who authorised the deployment.
    """

    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name=_("Incident"),
        on_delete=models.CASCADE,
        related_name="vehicle_allocations",
    )

    vehicle = models.ForeignKey(
        "fleet.Vehicle",
        verbose_name=_("Vehicle"),
        on_delete=models.PROTECT,
        related_name="incident_allocations",
    )

    dispatched_at = models.DateTimeField(_("Dispatched At"), null=True, blank=True)
    returned_at   = models.DateTimeField(_("Returned At"),   null=True, blank=True)

    driver_name = models.CharField(
        _("Driver Name"),
        max_length=200,
        blank=True,
        default="",
    )

    notes = models.TextField(_("Notes"), blank=True, default="")

    authorised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Authorised By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name        = _("Incident Vehicle Allocation")
        verbose_name_plural = _("Incident Vehicle Allocations")

        constraints = [
            models.UniqueConstraint(
                fields=["incident", "vehicle"],
                name="unique_vehicle_per_incident",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.vehicle.registration_no} → {self.incident.title}"
