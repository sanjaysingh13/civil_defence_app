"""
Training app models.

Civil Defence volunteers undergo two broad categories of training:

1.  Basic Training  — the mandatory foundation course every volunteer must
                      complete when they register.
2.  Special Training — advanced / specialised courses like Aapda Mitra, MDT,
                       Fire Fighting, Driving, etc.

We model training in three layers:

  Training          — the definition of a training programme (name, type,
                      description).  Think of it as the "syllabus".
  TrainingInstance  — a specific real-world occurrence of that programme
                      (batch, venue, dates, instructor).  Think of it as a
                      "class run".
  TrainingAttendance — the join table linking a Volunteer to a particular
                       TrainingInstance, recording whether they attended and
                       their certificate number.

This three-layer design is standard in event-attendance systems and is often
called the "Event / Event-Occurrence / Attendee" pattern.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


# ─────────────────────────────────────────────────────────────────────────────
# TIMESTAMP MIXIN  (copied from personnel to keep apps decoupled)
# ─────────────────────────────────────────────────────────────────────────────

class TimeStampedModel(models.Model):
    """Abstract base class adding created_at / updated_at to every model."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ─────────────────────────────────────────────────────────────────────────────
# CHOICES
# ─────────────────────────────────────────────────────────────────────────────

class TrainingType(models.TextChoices):
    """
    Broad classification of training programmes.

    BASIC       — mandatory foundation course (maps to basic_training_details)
    ADVANCED    — Aapda Mitra, MDT, Search & Rescue, etc.
    SPECIALIZED — Driving, Diving, Fire Fighting, TOT (Trainer of Trainers), etc.
    REFRESHER   — periodic refresher courses and mock drills
    """
    BASIC       = "BASIC",       _("Basic / Foundation")
    ADVANCED    = "ADVANCED",    _("Advanced")
    SPECIALIZED = "SPECIALIZED", _("Specialised Skill")
    REFRESHER   = "REFRESHER",   _("Refresher / Mock Drill")


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING  (programme definition)
# ─────────────────────────────────────────────────────────────────────────────

class Training(TimeStampedModel):
    """
    A Civil Defence training programme (the "what").

    Examples:
      • "Civil Defence Basic Training Course"  (type=BASIC)
      • "Aapda Mitra"                          (type=ADVANCED)
      • "Fire Fighting"                        (type=SPECIALIZED)
      • "Refresher Training & Mock Drill"      (type=REFRESHER)

    Multiple TrainingInstances (actual runs / batches) can exist for each
    Training programme.
    """

    name = models.CharField(
        _("Training Name"),
        max_length=200,
        unique=True,
        help_text=_("Full official name of the training programme"),
    )

    training_type = models.CharField(
        _("Training Type"),
        max_length=12,
        choices=TrainingType.choices,
        default=TrainingType.BASIC,
    )

    description = models.TextField(_("Description"), blank=True, default="")

    class Meta:
        verbose_name        = _("Training Programme")
        verbose_name_plural = _("Training Programmes")
        ordering            = ["training_type", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_training_type_display()})"


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING INSTANCE  (a specific batch / run of a programme)
# ─────────────────────────────────────────────────────────────────────────────

class TrainingInstance(TimeStampedModel):
    """
    A specific occurrence of a Training programme (the "when & where").

    For example, the Alipurduar Basic Training batch held at Circuit House
    from 09.12.2013 to 13.12.2013 would be one TrainingInstance linked to the
    "Civil Defence Basic Training Course" Training.

    The Unit FK records which Civil Defence district organised / hosted this
    batch.  A training could be inter-district, so it is optional (blank=True).
    """

    # Which programme is this an instance of?
    training = models.ForeignKey(
        "training.Training",
        verbose_name=_("Training Programme"),
        on_delete=models.PROTECT,
        related_name="instances",
    )

    # Which unit/district organised this batch?
    # String reference avoids a circular import between apps.
    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Organising Unit"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_instances",
        help_text=_("Leave blank if inter-district"),
    )

    # Batch identifier or certificate number prefix (e.g. "1389-BB.CD-ALP").
    batch_no = models.CharField(
        _("Batch / Certificate Prefix"),
        max_length=100,
        blank=True,
        default="",
    )

    location = models.CharField(
        _("Venue / Location"),
        max_length=255,
        blank=True,
        default="",
    )

    start_date = models.DateField(_("Start Date"), null=True, blank=True)
    end_date   = models.DateField(_("End Date"),   null=True, blank=True)

    # The instructor's name (free text for flexibility).
    instructor = models.CharField(_("Instructor"), max_length=200, blank=True, default="")

    notes = models.TextField(_("Notes"), blank=True, default="")

    class Meta:
        verbose_name        = _("Training Instance / Batch")
        verbose_name_plural = _("Training Instances / Batches")
        ordering            = ["-start_date"]

    def __str__(self) -> str:
        date_str = str(self.start_date) if self.start_date else "undated"
        return f"{self.training.name} — {self.location or 'Unknown venue'} ({date_str})"


# ─────────────────────────────────────────────────────────────────────────────
# TRAINING ATTENDANCE  (M2M through-table: Volunteer ↔ TrainingInstance)
# ─────────────────────────────────────────────────────────────────────────────

class TrainingAttendance(TimeStampedModel):
    """
    Links a Volunteer to a specific TrainingInstance they attended.

    Using an explicit through-table (instead of a plain ManyToManyField)
    lets us store extra per-attendance metadata: certificate number, notes,
    and who enrolled the volunteer.

    Django supports this pattern via ManyToManyField with through=.
    Here we define the relationship on the Volunteer model (in personnel) by
    having both FKs here — the admin and DRF serialisers pick it up naturally.
    """

    # String reference to avoid cross-app circular imports.
    volunteer = models.ForeignKey(
        "personnel.Volunteer",
        verbose_name=_("Volunteer"),
        on_delete=models.CASCADE,
        related_name="training_attendances",
    )

    training_instance = models.ForeignKey(
        "training.TrainingInstance",
        verbose_name=_("Training Instance"),
        on_delete=models.CASCADE,
        related_name="attendances",
    )

    certificate_no = models.CharField(
        _("Certificate Number"),
        max_length=100,
        blank=True,
        default="",
    )

    # Optional notes — e.g. "attended day 1 only", "passed with distinction"
    notes = models.TextField(_("Notes"), blank=True, default="")

    # The admin / unit-in-charge who recorded this attendance.
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Enrolled By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enrollments_made",
    )

    class Meta:
        verbose_name        = _("Training Attendance")
        verbose_name_plural = _("Training Attendances")
        ordering            = ["-training_instance__start_date"]

        # A volunteer can only attend a specific batch once.
        constraints = [
            models.UniqueConstraint(
                fields=["volunteer", "training_instance"],
                name="unique_attendance_per_instance",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.volunteer.name} @ {self.training_instance}"
