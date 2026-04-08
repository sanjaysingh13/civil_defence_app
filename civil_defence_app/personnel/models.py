"""
Personnel app models.

This app is the heart of the Civil Defence database.  It stores two things:

1.  Unit  — a Civil Defence district/unit (e.g. ALIPURDUAR, BANKURA …).
            Equipment, Fleet and Incidents all reference this same model, so it
            lives here as the canonical source.  Other apps import it with a
            string reference ("personnel.Unit") to avoid circular imports.

2.  Volunteer — a single Civil Defence volunteer record.  All 25 columns from
                the source Excel / Parquet file are mapped here, with proper
                field types (CharField, DateField, BooleanField …) rather than
                storing everything as raw text.

Django models are Python classes that inherit from django.db.models.Model.
Each class attribute that is a Field instance becomes a database column.
The __str__ method controls what Django shows when it needs to represent an
object as a string (e.g. in the admin, dropdowns, shell).
"""

import calendar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.encoding import iri_to_uri
from django.utils.translation import gettext_lazy as _

# ─────────────────────────────────────────────────────────────────────────────
# CHOICES
#
# Django's TextChoices / IntegerChoices create enum-like objects.
# Each member has a .value (stored in DB) and a .label (shown to humans).
# Using choices enforces consistency and lets forms auto-generate dropdowns.
# ─────────────────────────────────────────────────────────────────────────────


class GenderChoice(models.TextChoices):
    """Biological sex / gender of the volunteer as recorded in the source data."""

    MALE = "M", _("Male")
    FEMALE = "F", _("Female")
    OTHER = "O", _("Other / Not Specified")


class CategoryChoice(models.TextChoices):
    """Social category as per Indian government classification."""

    GENERAL = "GEN", _("General")
    SC = "SC", _("Scheduled Caste")
    ST = "ST", _("Scheduled Tribe")
    OBC_A = "OBC-A", _("OBC-A")
    OBC_B = "OBC-B", _("OBC-B")
    OTHER = "OTHER", _("Other")


class BloodGroupChoice(models.TextChoices):
    """ABO + Rh blood group system."""

    A_POS = "A+", _("A+")
    A_NEG = "A-", _("A-")
    B_POS = "B+", _("B+")
    B_NEG = "B-", _("B-")
    AB_POS = "AB+", _("AB+")
    AB_NEG = "AB-", _("AB-")
    O_POS = "O+", _("O+")
    O_NEG = "O-", _("O-")
    UNKNOWN = "UNK", _("Unknown")


# ─────────────────────────────────────────────────────────────────────────────
# ABSTRACT TIMESTAMP MIXIN
#
# An abstract model is a base class that itself is NOT turned into a database
# table.  Any model that inherits from it gets those fields automatically.
# We use this to add created_at / updated_at to every model without repeating
# the field definitions everywhere.
# ─────────────────────────────────────────────────────────────────────────────


class TimeStampedModel(models.Model):
    """Mixin that adds created_at and updated_at to any model."""

    # auto_now_add=True → Django sets this field to now() when the row is
    # first inserted and never changes it again.
    created_at = models.DateTimeField(auto_now_add=True)

    # auto_now=True → Django sets this field to now() every time .save() is
    # called, so it always reflects the last modification time.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # abstract=True tells Django NOT to create a DB table for this model.
        # It is only used as a base class.
        abstract = True


# ─────────────────────────────────────────────────────────────────────────────
# UNIT MODEL
#
# Represents a Civil Defence district unit, e.g. "ALIPURDUAR".
# This is the organisational container for Volunteers, Equipment, Fleet and
# Incidents.  Other apps reference it via a ForeignKey to "personnel.Unit".
# ─────────────────────────────────────────────────────────────────────────────


class Unit(TimeStampedModel):
    """
    A Civil Defence district / operational unit.

    The 23 districts loaded from the parquet file each become one Unit row.
    Future units can be added through the admin or management commands.
    """

    # The official name of the unit as it appears in the source Excel sheet
    # (e.g. "ALIPURDUAR", "KOLKATA (NSA)").
    name = models.CharField(
        _("Unit Name"),
        max_length=120,
        unique=True,  # No two units can have the same name.
        help_text=_("Official district / unit name (e.g. ALIPURDUAR)"),
    )

    # A human-readable short code used in URLs and reports.
    # SlugField stores URL-safe strings: lowercase letters, numbers, hyphens.
    slug = models.SlugField(
        _("Slug"),
        max_length=60,
        unique=True,
        help_text=_("Auto-generated URL-safe identifier (e.g. alipurduar)"),
    )

    # Optional free-text description or notes about the unit.
    description = models.TextField(_("Description"), blank=True, default="")

    class Meta:
        verbose_name = _("Unit")
        verbose_name_plural = _("Units")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# VOLUNTEER MODEL
#
# Maps 1:1 to a row in civil_defence_raw.parquet.
# Every field is documented with its source column name for traceability.
# Messy free-text fields from the raw data (bank_details, guardian_address,
# basic_training, special_training) are stored as TextField to avoid
# truncation; they can be parsed / structured later.
# ─────────────────────────────────────────────────────────────────────────────


class Volunteer(TimeStampedModel):
    """
    A Civil Defence volunteer record sourced from FinalReportDatabase.xlsx.

    Each volunteer belongs to exactly one Unit (district).  The `block` field
    further subdivides the unit into a sub-area (e.g. town / Block Development
    Office area).

    Training and incident relationships are defined via M2M / FK from the
    training and incidents apps respectively, keeping this model lean.
    """

    # ── Organisational ───────────────────────────────────────────────────────

    # ForeignKey means "many Volunteers can belong to one Unit".
    # on_delete=PROTECT prevents accidentally deleting a Unit that still has
    # volunteers attached.
    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Unit"),
        on_delete=models.PROTECT,
        related_name="volunteers",
    )

    # Serial number within the unit (from the Excel 'Sl No.' column).
    # Not the primary key — Django auto-creates a BigAutoField PK.
    serial_no = models.CharField(
        _("Serial No."),
        max_length=20,
        help_text=_("Serial number within the unit register"),
    )

    # The Block Development Office area or municipality ward within the unit.
    # Some source rows stuffed the full address into this column (up to 217 chars),
    # so we use 500 to accommodate the worst case.
    block = models.CharField(
        _("Block / Area"),
        max_length=500,
        blank=True,
        default="",
    )

    # ── Personal Information ──────────────────────────────────────────────────

    name = models.CharField(_("Full Name"), max_length=255)

    # Gender stored as a single-character code; displayed via GenderChoice labels.
    gender = models.CharField(
        _("Gender"),
        max_length=1,
        choices=GenderChoice,
        default=GenderChoice.OTHER,
    )

    category = models.CharField(
        _("Social Category"),
        max_length=6,
        choices=CategoryChoice,
        default=CategoryChoice.GENERAL,
    )

    blood_group = models.CharField(
        _("Blood Group"),
        max_length=4,
        choices=BloodGroupChoice,
        default=BloodGroupChoice.UNKNOWN,
    )

    # Date of birth; null=True because some source rows had unparsable dates.
    dob = models.DateField(_("Date of Birth"), null=True, blank=True)

    # The date this volunteer reaches 60 years (retirement threshold).
    date_60 = models.DateField(
        _("Date of Attaining 60 Years"),
        null=True,
        blank=True,
    )

    # ── Contact Information ───────────────────────────────────────────────────

    # Some rows contain multiple numbers separated by commas/spaces (up to 50 chars).
    mobile = models.CharField(
        _("Mobile / Phone No."),
        max_length=60,
        blank=True,
        default="",
    )
    email = models.EmailField(_("Email"), max_length=254, blank=True, default="")

    # Free-text blob: "Father's Name … Permanent Address".
    # Kept as-is from source; structured address fields can be added later.
    guardian_address = models.TextField(
        _("Guardian Name, Contact & Permanent Address"),
        blank=True,
        default="",
    )

    # ── Government IDs & Schemes ──────────────────────────────────────────────

    # Aadhaar is a 12-digit national ID.  Stored as string to preserve leading
    # zeros and spaces.  Some entries have spaces plus extra digits ("1926 0447 0225 0992 3"),
    # so we allow up to 30 chars.
    aadhar_no = models.CharField(
        _("Aadhaar Card No."),
        max_length=30,
        blank=True,
        default="",
    )

    # HRMS is a government HR management system ID (e.g. "W2017021570").
    hrms_id = models.CharField(_("HRMS ID"), max_length=30, blank=True, default="")

    # Swasthya Sathi is a West Bengal state health insurance scheme.
    # The source data has Y/N; we store it as a boolean.
    swasthya_sathi = models.BooleanField(
        _("Enrolled in Swasthya Sathi Scheme"),
        default=False,
    )

    # ── Education & Skills ────────────────────────────────────────────────────

    qualification = models.CharField(
        _("Academic Qualification"),
        max_length=100,
        blank=True,
        default="",
    )

    computer_knowledge = models.BooleanField(
        _("Has Computer Knowledge"),
        default=False,
    )

    # ── Bank Details ──────────────────────────────────────────────────────────

    # Free-text blob from source: "Bank Name, Branch, IFSC, A/C no."
    # Kept unstructured intentionally; proper bank fields can be normalised later.
    bank_details = models.TextField(_("Bank Account Details"), blank=True, default="")

    # ── Civil Defence Registration & Training ─────────────────────────────────

    registration_date = models.DateField(
        _("Date of Registration as CD Volunteer"),
        null=True,
        blank=True,
    )

    # Free-text details of the Basic CD Training course as recorded in source.
    # e.g. "PLACE-ALIPURDUAR CIRCUIT HOUSE, (09.12.2013 TO 13.12.2013)"
    # Structured rows: `seed_training_from_volunteers` parses this text, creates
    # TrainingInstance + TrainingAttendance linking to "Civil Defence Basic Training".
    # This field is kept as the immutable audit trail from the import.
    basic_training_details = models.TextField(
        _("Basic Training Details (Raw)"),
        blank=True,
        default="",
    )

    # e.g. "1.AAPDA MITRA 2.MDT 3. FIRE FIGHTING …"
    # Parsed tokens map to canonical Training programmes (Aapda Mitra, MDT, …);
    # see `training.parsers` and the same seed command.
    special_training_details = models.TextField(
        _("Special Training Details (Raw)"),
        blank=True,
        default="",
    )

    extra_activities = models.TextField(
        _("Extra Curricular Activities"),
        blank=True,
        default="",
    )

    # Reference string for the linked document PDF (e.g. "01_PALASH DHAR_AP.pdf").
    # Actual file upload is handled separately through media storage.
    documents_ref = models.CharField(
        _("Documents Reference"),
        max_length=500,
        blank=True,
        default="",
    )

    # ── Status ────────────────────────────────────────────────────────────────

    is_active = models.BooleanField(
        _("Is Active"),
        default=True,
        help_text=_("Uncheck to deactivate without deleting the record"),
    )

    # When a volunteer is removed from active service (de-rostered), the web UI
    # records the effective date and a free-text reason. These fields support
    # audit and reporting; `is_active=False` is what excludes them from dispatch,
    # training pickers, and the public volunteer list.
    derostered_on = models.DateField(
        _("De-rostered on"),
        null=True,
        blank=True,
        help_text=_("Date removed from active roster (if de-rostered)."),
    )
    deroster_reason = models.TextField(
        _("De-roster reason"),
        blank=True,
        default="",
        help_text=_("Why this volunteer was de-rostered from service."),
    )

    class Meta:
        verbose_name = _("Volunteer")
        verbose_name_plural = _("Volunteers")
        ordering = ["unit", "serial_no"]

        # Composite uniqueness: a serial number is unique within a unit.
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "serial_no"],
                name="unique_volunteer_serial_per_unit",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit.name})"

    def get_age(self) -> int | None:
        """Calculate current age from date of birth."""
        if not self.dob:
            return None
        from django.utils import timezone

        today = timezone.now().date()
        age = today.year - self.dob.year
        # Subtract 1 if birthday has not yet occurred this year
        if (today.month, today.day) < (self.dob.month, self.dob.day):
            age -= 1
        return age

    @property
    def documents_file_url(self) -> str:
        """
        URL to the volunteer PDF (or other file) named in ``documents_ref``.

        ``documents_ref`` is stored as a path relative to uploaded media: either
        a bare filename (served from ``MEDIA_ROOT`` / the bucket ``media/`` prefix)
        or a subpath such as ``volunteers/01_name.pdf``.  ``iri_to_uri`` turns
        that into a valid URI (e.g. spaces become ``%20``) for use in ``<a href>``.
        """
        ref = (self.documents_ref or "").strip()
        if not ref:
            return ""
        base = settings.MEDIA_URL
        if not base.endswith("/"):
            base = f"{base}/"
        ref_norm = ref.replace("\\", "/").lstrip("/")
        return iri_to_uri(f"{base}{ref_norm}")


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY PERIOD
#
# Operational (field) deployment is a *team* operation: many volunteers on one
# Incident via incidents.IncidentAssignment.  Office duty is *not* modelled
# that way — it is individual time at the office, one row per volunteer.
#
# Service / wage day counts combine both: incident segments from the incident
# timeline plus office periods from this model.
#
# At most one open period (ended_at IS NULL) per volunteer is enforced for
# legacy data integrity; new office duty is entered via monthly CSV uploads.
# ─────────────────────────────────────────────────────────────────────────────


class OfficeDutyPeriod(TimeStampedModel):
    """
    One contiguous office-duty stretch for a single volunteer (individual, not a unit team).

    started_at is normally chosen from a date picker (start of that local day).
    ended_at is set when the UIC or Admin ends the shift; NULL means still on duty.
    """

    volunteer = models.ForeignKey(
        "personnel.Volunteer",
        verbose_name=_("Volunteer"),
        on_delete=models.CASCADE,
        related_name="office_duty_periods",
    )

    started_at = models.DateTimeField(_("Duty Started At"))

    ended_at = models.DateTimeField(
        _("Duty Ended At"),
        null=True,
        blank=True,
    )

    notes = models.TextField(_("Notes"), blank=True, default="")

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Recorded By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_office_duty_periods",
    )

    class Meta:
        verbose_name = _("Office Duty Period")
        verbose_name_plural = _("Office Duty Periods")
        ordering = ["-started_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["volunteer"],
                condition=models.Q(ended_at__isnull=True),
                name="unique_open_office_duty_per_volunteer",
            ),
        ]

    def __str__(self) -> str:
        end = self.ended_at.strftime("%Y-%m-%d %H:%M") if self.ended_at else "ongoing"
        return f"{self.volunteer.name} office duty {self.started_at} → {end}"


# ─────────────────────────────────────────────────────────────────────────────
# OFFICE DUTY — MONTHLY AGGREGATE (CSV workflow)
#
# UICs upload one CSV per unit per calendar month with days worked in office per
# volunteer.  This replaces start/stop period logging for new data; legacy
# OfficeDutyPeriod rows remain for history and service-log merging.
# ─────────────────────────────────────────────────────────────────────────────


class VolunteerOfficeDutyMonth(TimeStampedModel):
    """
    Total days a volunteer worked in office during a given calendar month.

    Uniqueness on (volunteer, year, month) so re-uploading a unit CSV upserts.
    """

    volunteer = models.ForeignKey(
        "personnel.Volunteer",
        verbose_name=_("Volunteer"),
        on_delete=models.CASCADE,
        related_name="office_duty_months",
    )
    year = models.PositiveSmallIntegerField(_("Year"))
    month = models.PositiveSmallIntegerField(_("Month"))
    days_worked = models.PositiveSmallIntegerField(_("Days worked in office"))
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Recorded By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_office_duty_months",
    )

    class Meta:
        verbose_name = _("Volunteer office duty (monthly)")
        verbose_name_plural = _("Volunteer office duty (monthly)")
        ordering = ["-year", "-month", "volunteer__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["volunteer", "year", "month"],
                name="unique_volunteer_office_duty_month",
            ),
            models.CheckConstraint(
                condition=models.Q(month__gte=1) & models.Q(month__lte=12),
                name="office_duty_month_month_range",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.month is not None and (self.month < 1 or self.month > 12):
            raise ValidationError({"month": _("Month must be between 1 and 12.")})
        if (
            self.year is not None
            and self.month is not None
            and self.days_worked is not None
        ):
            _w, max_days = calendar.monthrange(int(self.year), int(self.month))
            if self.days_worked > max_days:
                raise ValidationError(
                    {
                        "days_worked": _(
                            "Cannot exceed %(max)d days in this month.",
                        )
                        % {"max": max_days},
                    },
                )

    def __str__(self) -> str:
        return (
            f"{self.volunteer.name} {self.year}-{self.month:02d}: {self.days_worked}d"
        )


class OfficeDutyMonthSubmission(TimeStampedModel):
    """
    Tracks that a unit has submitted office-duty CSV data for a calendar month.

    Updated on each successful upload so admins can see which units filed.
    """

    unit = models.ForeignKey(
        "personnel.Unit",
        verbose_name=_("Unit"),
        on_delete=models.CASCADE,
        related_name="office_duty_month_submissions",
    )
    year = models.PositiveSmallIntegerField(_("Year"))
    month = models.PositiveSmallIntegerField(_("Month"))
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Submitted By"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="office_duty_month_submissions",
    )

    class Meta:
        verbose_name = _("Office duty month submission")
        verbose_name_plural = _("Office duty month submissions")
        ordering = ["-year", "-month", "unit__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "year", "month"],
                name="unique_unit_office_duty_month_submission",
            ),
            models.CheckConstraint(
                condition=models.Q(month__gte=1) & models.Q(month__lte=12),
                name="office_duty_submission_month_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.unit.name} {self.year}-{self.month:02d}"
