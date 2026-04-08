"""
Incidents app models.

An Incident is any emergency event that a Civil Defence unit responds to —
floods, fires, building collapses, storms, cyclones, road accidents, etc.

The lifecycle of an incident in this system:
  1.  Incident is created (reported) with status OPEN.
  2.  Unit In-Charge diarises it and builds a response team:
        - assigns Volunteers (IncidentAssignment)
        - may note equipment and vehicles used (free-text for now; structured
          links via equipment/fleet apps can be added later)
  3.  Logs are added as the response progresses (IncidentLog).
  4.  After completion the Unit In-Charge writes a detailed report and closes
      the incident (status → CLOSED).

Media files (photos, videos) are handled by Django's FileField / ImageField
and stored under MEDIA_ROOT/incident_media/.
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


class IncidentType(models.TextChoices):
    FLOOD = "FLOOD", _("Flood")
    FIRE = "FIRE", _("Fire")
    COLLAPSE = "COLLAPSE", _("Building / Structure Collapse")
    STORM = "STORM", _("Storm / Cyclone")
    ACCIDENT = "ACCIDENT", _("Road / Rail Accident")
    DROUGHT = "DROUGHT", _("Drought")
    EPIDEMIC = "EPIDEMIC", _("Epidemic / Disease Outbreak")
    SEARCH = "SEARCH", _("Search & Rescue")
    OTHER = "OTHER", _("Other")


class IncidentStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending Diary")
    OPEN = "OPEN", _("Open / Active Response")
    CLOSED = "CLOSED", _("Closed / Completed")


class IncidentAssignmentRole(models.TextChoices):
    """
    Fixed set of deployment roles for a volunteer on a specific incident.

    Add new roles here and run makemigrations if max_length must grow; the
    dispatch form and admin use these choices for validation and dropdowns.
    """

    SCUBA_DIVER = "SCUBA_DIVER", _("Scuba Diver")
    DRIVER = "DRIVER", _("Driver")
    FIREFIGHTER = "FIREFIGHTER", _("Fire-fighter")
    CUTTER = "CUTTER", _("Cutter")


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT
# ─────────────────────────────────────────────────────────────────────────────


class Incident(TimeStampedModel):
    """
    A single emergency incident managed by a Civil Defence unit.

    A Unit In-Charge creates and owns the incident record.  He then attaches
    Volunteers, writes log entries, and eventually closes the incident with a
    detailed report.

    Incident Number Format:  {UNIT_SLUG_UPPER}-{YEAR}-{NNN}
    Example:                 ALIPURDUAR-2026-003

    The number is auto-generated in the save() method the first time a new
    Incident is persisted to the database.  It is unique across the whole
    incidents table.
    """

    # ── Incident Number ───────────────────────────────────────────────────────
    # null=True so existing rows in the DB (if any) get NULL instead of
    # colliding on the unique constraint.  The save() override fills this in
    # automatically whenever a new incident is created.
    incident_number = models.CharField(
        _("Incident Number"),
        max_length=40,
        unique=True,
        null=True,
        blank=True,
        help_text=_("Auto-generated: UNIT-YEAR-NNN  (e.g. ALIPURDUAR-2026-003)"),
    )

    # The unit that is handling this incident.
    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Handling Unit"),
        on_delete=models.PROTECT,
        related_name="incidents",
    )

    title = models.CharField(
        _("Incident Title"),
        max_length=255,
        help_text=_(
            "Short descriptive title, e.g. 'Flash flood in Alipurduar Block I'"
        ),
    )

    incident_type = models.CharField(
        _("Incident Type"),
        max_length=12,
        choices=IncidentType,
        default=IncidentType.OTHER,
    )

    status = models.CharField(
        _("Status"),
        max_length=8,
        choices=IncidentStatus,
        default=IncidentStatus.OPEN,
    )

    # ── Location ──────────────────────────────────────────────────────────────

    location_text = models.CharField(
        _("Location Description"),
        max_length=500,
        blank=True,
        default="",
        help_text=_("Free-text: village, block, PS, landmark"),
    )

    # Optional GPS co-ordinates for future GIS integration.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    # ── Timeline ──────────────────────────────────────────────────────────────

    start_time = models.DateTimeField(_("Incident Start Time"), null=True, blank=True)
    end_time = models.DateTimeField(_("Incident End Time"), null=True, blank=True)

    # ── Report ────────────────────────────────────────────────────────────────

    description = models.TextField(
        _("Incident Description"),
        blank=True,
        default="",
        help_text=_("Full narrative: what happened, scope, damage assessment"),
    )

    # Detailed report filed after operations are complete.
    final_report = models.TextField(_("Final Incident Report"), blank=True, default="")

    # ── Ownership ─────────────────────────────────────────────────────────────

    # The user (Unit In-Charge or Admin) who reported this incident.
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Reported By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reported_incidents",
    )

    class Meta:
        verbose_name = _("Incident")
        verbose_name_plural = _("Incidents")
        ordering = ["-start_time", "-created_at"]

    def __str__(self) -> str:
        num = self.incident_number or "—"
        return f"[{num}] {self.title}"

    # ── Auto-generate incident number on first save ───────────────────────────

    @classmethod
    def generate_incident_number(cls, unit, reference_time=None) -> str:
        """
        Build the next available incident number for *unit* in the given year.

        Algorithm:
          1. Use the reference_time's year (falls back to current year).
          2. Count existing Incident rows whose incident_number starts with
             the prefix  "{UNIT_SLUG}-{YEAR}-"  to find the current highest
             serial for that unit+year combination.
          3. Return  "{UNIT_SLUG}-{YEAR}-{serial+1:03d}"

        Example:  ALIPURDUAR already has ALIPURDUAR-2026-001 and -002
                  → next call returns  "ALIPURDUAR-2026-003"

        Note: a very small race condition exists if two incidents for the same
        unit are saved simultaneously.  For the current scale (1–2 concurrent
        operations per unit) this is acceptable.
        """
        from django.utils import timezone

        year = (reference_time or timezone.now()).year
        prefix = f"{unit.slug.upper()}-{year}-"

        # Count rows that already have a number with this prefix to determine
        # the next serial number in the sequence.
        existing_count = cls.objects.filter(
            incident_number__startswith=prefix,
        ).count()

        serial = existing_count + 1
        return f"{prefix}{serial:03d}"

    def save(self, *args, **kwargs):
        """
        Override Django's default save() to auto-populate incident_number
        the first time a new Incident is written to the database.

        self.pk is None when the object is brand-new (not yet saved).
        self.unit_id check ensures we don't crash if unit hasn't been set yet
        (though the model's FK makes that unlikely for a real save call).
        """
        if not self.incident_number and self.unit_id:
            self.incident_number = Incident.generate_incident_number(
                self.unit,
                reference_time=self.start_time,
            )
        super().save(*args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT MEDIA
#
# Each Incident can have multiple attached photos or videos.
# Files are stored under MEDIA_ROOT/incident_media/<incident_id>/.
# ─────────────────────────────────────────────────────────────────────────────


def incident_media_path(instance: "IncidentMedia", filename: str) -> str:
    """
    Callable used by FileField's upload_to argument.
    Organises uploads as: incident_media/<incident_pk>/<filename>
    """
    return f"incident_media/{instance.incident_id}/{filename}"


class IncidentMedia(TimeStampedModel):
    """A photo or video file attached to an Incident."""

    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name=_("Incident"),
        on_delete=models.CASCADE,
        related_name="media_files",
    )

    file = models.FileField(
        _("File"),
        upload_to=incident_media_path,
        help_text=_("Photo (jpg/png) or video (mp4) file"),
    )

    caption = models.CharField(_("Caption"), max_length=255, blank=True, default="")
    tags = models.CharField(_("Tags"), max_length=200, blank=True, default="")

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Uploaded By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Incident Media")
        verbose_name_plural = _("Incident Media Files")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.incident.title} — {self.file.name}"


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT LOG
#
# A chronological diary of actions taken during an incident response.
# The Unit In-Charge adds entries as events unfold.
# ─────────────────────────────────────────────────────────────────────────────


class IncidentLog(TimeStampedModel):
    """Time-stamped diary entry for an ongoing Incident."""

    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name=_("Incident"),
        on_delete=models.CASCADE,
        related_name="log_entries",
    )

    # Exact time the logged action occurred (may differ from created_at).
    timestamp = models.DateTimeField(_("Timestamp"))

    action_taken = models.TextField(
        _("Action Taken"),
        help_text=_("What was done at this point in the response"),
    )

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Entered By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Incident Log Entry")
        verbose_name_plural = _("Incident Log Entries")
        ordering = ["timestamp"]

    def __str__(self) -> str:
        return f"{self.incident.title} @ {self.timestamp}: {self.action_taken[:60]}"


# ─────────────────────────────────────────────────────────────────────────────
# INCIDENT ASSIGNMENT
#
# Links a Volunteer to an Incident (M2M through-table with metadata).
# Equipment and Vehicle assignments are recorded as FK references to their
# respective models in the equipment / fleet apps.
# ─────────────────────────────────────────────────────────────────────────────


class IncidentAssignment(TimeStampedModel):
    """
    Assignment of a Volunteer to an Incident response team.

    A single incident may involve many volunteers; a volunteer may be deployed
    to multiple incidents over time.  The through-table lets us record the
    volunteer's role in this specific incident.
    """

    incident = models.ForeignKey(
        "incidents.Incident",
        verbose_name=_("Incident"),
        on_delete=models.CASCADE,
        related_name="assignments",
    )

    volunteer = models.ForeignKey(
        "personnel.Volunteer",
        verbose_name=_("Volunteer"),
        on_delete=models.PROTECT,
        related_name="incident_assignments",
    )

    role = models.CharField(
        _("Role in Incident"),
        max_length=32,
        choices=IncidentAssignmentRole,
        default=IncidentAssignmentRole.FIREFIGHTER,
        help_text=_("Role this volunteer fills on this incident."),
    )

    assigned_at = models.DateTimeField(_("Assigned At"), auto_now_add=True)

    # Optional: notes on the volunteer's specific contribution.
    notes = models.TextField(_("Notes"), blank=True, default="")

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Assigned By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Incident Assignment")
        verbose_name_plural = _("Incident Assignments")
        ordering = ["-assigned_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["incident", "volunteer"],
                name="unique_volunteer_per_incident",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.volunteer.name} → {self.incident.title}"
