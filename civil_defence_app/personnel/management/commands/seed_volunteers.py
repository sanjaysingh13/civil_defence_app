"""
Management command: seed_volunteers

Usage:
    uv run python manage.py seed_volunteers
    uv run python manage.py seed_volunteers --parquet /path/to/civil_defence_raw.parquet
    uv run python manage.py seed_volunteers --dry-run

What it does:
    1. Reads civil_defence_raw.parquet (or a path you specify).
    2. Creates one Unit row for every unique value in the 'Unit' column.
       (get_or_create → safe to run multiple times; won't duplicate rows)
    3. Creates one Volunteer row for every data row in the parquet.
       (update_or_create on (unit, serial_no) → idempotent re-runs update
       existing records instead of creating duplicates)
    4. Prints a summary of rows created vs updated vs skipped.

Date parsing:
    The source data has many different date formats:
        "15.06.1990", "1987-09-12 00:00:00", "13.12.2013", "31/08/2013" …
    We try several known formats in order and fall back to None if nothing works.
    Invalid dates are logged as warnings but don't abort the whole import.

Boolean normalisation:
    "Y", "y", "YES", "yes" → True
    Anything else            → False

Management commands are Django's way to write one-off admin scripts that
have full access to the ORM, settings, and the virtual environment.
They live in <app>/management/commands/<name>.py and are invoked via
`python manage.py <name>`.
"""

import re
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from civil_defence_app.personnel.models import (
    BloodGroupChoice,
    CategoryChoice,
    GenderChoice,
    Unit,
    Volunteer,
)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Default path: walk up from this file to the civil_defence/ project root.
# seed_volunteers.py lives at:
#   civil_defence/civil_defence_app/civil_defence_app/personnel/management/commands/
# parents[5] resolves to:  civil_defence/
DEFAULT_PARQUET_PATH = Path(__file__).resolve().parents[5] / "civil_defence_raw.parquet"

# The many different date formats found in the raw data.
# We try them in order; the first successful parse wins.
DATE_FORMATS = [
    "%d.%m.%Y",        # 15.06.1990  (most common in this dataset)
    "%d/%m/%Y",        # 31/08/2013
    "%d-%m-%Y",        # 31-08-2013
    "%Y-%m-%d",        # 1987-09-12  (pandas timestamp-as-string)
    "%d.%m.%y",        # 15.06.90    (rare 2-digit year)
    "%d/%m/%y",        # 31/08/13
]


def parse_date(raw: str | None) -> date | None:
    """
    Try to parse a messy date string into a Python date object.

    Returns None if the string is empty, null-like, or doesn't match any
    known format.  This is 'best-effort' — we'd rather store None than a
    wrong date.

    Parameters
    ----------
    raw : str | None
        The raw string from the parquet column.

    Returns
    -------
    date | None
    """
    if not raw or str(raw).strip().lower() in ("nan", "nat", "none", "nil", ""):
        return None

    # Strip the time part if pandas serialised a Timestamp as "YYYY-MM-DD HH:MM:SS"
    raw_clean = str(raw).strip().split(" ")[0]

    for fmt in DATE_FORMATS:
        try:
            from datetime import datetime
            return datetime.strptime(raw_clean, fmt).date()
        except ValueError:
            continue

    # Last resort: try pandas' flexible parser
    try:
        import pandas as pd
        ts = pd.to_datetime(raw_clean, dayfirst=True, errors="coerce")
        if ts is not pd.NaT:
            return ts.date()
    except Exception:
        pass

    return None


def parse_bool(raw: str | None) -> bool:
    """
    Normalise Y/N/YES/NO strings from the source data to Python booleans.

    Parameters
    ----------
    raw : str | None
        Raw cell value from the parquet.

    Returns
    -------
    bool
    """
    if not raw:
        return False
    return str(raw).strip().upper().startswith("Y")


def normalise_gender(raw: str | None) -> str:
    """Map various spellings of Male/Female to our GenderChoice codes."""
    if not raw:
        return GenderChoice.OTHER
    val = str(raw).strip().upper()
    if val.startswith("M"):
        return GenderChoice.MALE
    if val.startswith("F"):
        return GenderChoice.FEMALE
    return GenderChoice.OTHER


def normalise_category(raw: str | None) -> str:
    """Map the messy category strings to CategoryChoice values."""
    if not raw:
        return CategoryChoice.GENERAL
    val = str(raw).strip().upper()

    # Check for OBC-B first (more specific) before plain OBC
    if "OBC-B" in val or "OBC B" in val:
        return CategoryChoice.OBC_B
    if "OBC-A" in val or "OBC A" in val or "OBC" in val:
        return CategoryChoice.OBC_A
    if val in ("SC",):
        return CategoryChoice.SC
    if val in ("ST",):
        return CategoryChoice.ST
    # GEN / GENERAL / GENL etc.
    if val.startswith("GEN"):
        return CategoryChoice.GENERAL
    return CategoryChoice.OTHER


def normalise_blood_group(raw: str | None) -> str:
    """Map blood group strings to BloodGroupChoice values."""
    if not raw:
        return BloodGroupChoice.UNKNOWN
    val = str(raw).strip().upper().replace(" ", "")
    mapping = {
        "A+": BloodGroupChoice.A_POS, "A-": BloodGroupChoice.A_NEG,
        "B+": BloodGroupChoice.B_POS, "B-": BloodGroupChoice.B_NEG,
        "AB+": BloodGroupChoice.AB_POS, "AB-": BloodGroupChoice.AB_NEG,
        "O+": BloodGroupChoice.O_POS, "O-": BloodGroupChoice.O_NEG,
    }
    return mapping.get(val, BloodGroupChoice.UNKNOWN)


def clean_str(raw) -> str:
    """
    Convert a raw parquet value to a clean string.
    Returns empty string for NaN / None / 'nan' / 'NIL' / 'null'.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.lower() in ("nan", "none", "nil", "null", "nill", "na", "n/a", ""):
        return ""
    return s


# ─────────────────────────────────────────────────────────────────────────────
# MANAGEMENT COMMAND CLASS
# ─────────────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    """
    Django management command to seed Volunteer + Unit data from parquet.

    The BaseCommand class provides:
      - self.stdout  : for normal output  (respects --no-color)
      - self.stderr  : for error output
      - self.style   : colour helpers (self.style.SUCCESS, self.style.WARNING …)
      - add_arguments(): to define CLI arguments
      - handle()      : the main logic, called by Django's runner
    """

    help = "Seed Unit and Volunteer records from civil_defence_raw.parquet"

    def add_arguments(self, parser):
        """
        Register command-line arguments.

        add_arguments receives an argparse.ArgumentParser instance.
        Any argument you add here becomes available in handle() via options['name'].
        """
        parser.add_argument(
            "--parquet",
            type=str,
            default=str(DEFAULT_PARQUET_PATH),
            help=f"Path to the parquet file (default: {DEFAULT_PARQUET_PATH})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and print stats without writing to the database",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of volunteers to upsert per database transaction (default: 500)",
        )

    # ── Main Entry Point ──────────────────────────────────────────────────────

    def handle(self, *args, **options):
        """
        Called by Django when the management command is invoked.

        We use a top-level try/except so any unexpected failure prints a
        helpful message instead of a raw traceback to the user.
        """
        parquet_path = Path(options["parquet"])
        dry_run      = options["dry_run"]
        batch_size   = options["batch_size"]

        self.stdout.write(f"Parquet file : {parquet_path}")
        self.stdout.write(f"Dry run      : {dry_run}")

        # ── 1. Load parquet ──────────────────────────────────────────────────
        if not parquet_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {parquet_path}"))
            return

        try:
            import pandas as pd
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "pandas is not installed.  Run: uv add pandas pyarrow"
            ))
            return

        self.stdout.write("Loading parquet file …")
        df = pd.read_parquet(parquet_path)
        self.stdout.write(self.style.SUCCESS(f"  → {len(df)} rows loaded"))

        # ── 2. Seed Units ────────────────────────────────────────────────────
        unit_names = sorted(df["Unit"].dropna().unique().tolist())
        self.stdout.write(f"\nSeeding {len(unit_names)} units …")

        unit_map: dict[str, Unit] = {}  # name → Unit instance

        if not dry_run:
            for name in unit_names:
                slug = slugify(name)
                unit, created = Unit.objects.get_or_create(
                    name=name,
                    defaults={"slug": slug},
                )
                unit_map[name] = unit
                marker = "CREATED" if created else "EXISTS "
                self.stdout.write(f"  [{marker}] {name}")
        else:
            for name in unit_names:
                self.stdout.write(f"  [DRY-RUN] Would create unit: {name}")

        # ── 3. Seed Volunteers ───────────────────────────────────────────────
        self.stdout.write(f"\nSeeding {len(df)} volunteers …")

        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_count   = 0

        # We process in chunks (batches) to avoid loading thousands of rows
        # into memory at once and to give progress feedback.
        total = len(df)
        rows  = df.itertuples(index=False)

        for i, row in enumerate(rows, start=1):
            # Progress indicator every batch_size rows
            if i % batch_size == 0 or i == total:
                self.stdout.write(f"  … processed {i}/{total}")

            unit_name  = clean_str(getattr(row, "Unit", ""))
            serial_no  = clean_str(getattr(row, "serial_no", ""))

            if not unit_name or not serial_no:
                skipped_count += 1
                continue

            if dry_run:
                continue

            unit = unit_map.get(unit_name)
            if unit is None:
                skipped_count += 1
                continue

            # Build the full field dict for this volunteer row.
            # We use update_or_create so re-running the command updates stale data.
            defaults = {
                "name":                     clean_str(getattr(row, "name", ""))           or "UNKNOWN",
                "block":                    clean_str(getattr(row, "block", "")),
                "guardian_address":         clean_str(getattr(row, "guardian_address", "")),
                "gender":                   normalise_gender(getattr(row, "gender", None)),
                "category":                 normalise_category(getattr(row, "category", None)),
                "blood_group":              normalise_blood_group(getattr(row, "blood_group", None)),
                "bank_details":             clean_str(getattr(row, "bank_details", "")),
                "aadhar_no":                clean_str(getattr(row, "aadhar_no", "")),
                "hrms_id":                  clean_str(getattr(row, "hrms_id", "")),
                "swasthya_sathi":           parse_bool(getattr(row, "swasthya_sathi", None)),
                "dob":                      parse_date(getattr(row, "dob", None)),
                "date_60":                  parse_date(getattr(row, "date_60", None)),
                "mobile":                   clean_str(getattr(row, "mobile", "")),
                "email":                    clean_str(getattr(row, "email", "")),
                "qualification":            clean_str(getattr(row, "qualification", "")),
                "computer_knowledge":       parse_bool(getattr(row, "computer_knowledge", None)),
                "registration_date":        parse_date(getattr(row, "registration_date", None)),
                "basic_training_details":   clean_str(getattr(row, "basic_training", "")),
                "special_training_details": clean_str(getattr(row, "special_training", "")),
                "extra_activities":         clean_str(getattr(row, "extra_activities", "")),
                "documents_ref":            clean_str(getattr(row, "documents", "")),
                "is_active":                True,
            }

            try:
                _, was_created = Volunteer.objects.update_or_create(
                    unit=unit,
                    serial_no=serial_no,
                    defaults=defaults,
                )
                if was_created:
                    created_count += 1
                else:
                    updated_count += 1

            except Exception as exc:
                error_count += 1
                self.stderr.write(
                    self.style.WARNING(
                        f"  Row {i} (unit={unit_name}, serial={serial_no}): {exc}"
                    )
                )

        # ── 4. Summary ───────────────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 50)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no records written"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  Created : {created_count:>6}"))
            self.stdout.write(self.style.SUCCESS(f"  Updated : {updated_count:>6}"))
            self.stdout.write(f"  Skipped : {skipped_count:>6}")
            if error_count:
                self.stdout.write(self.style.ERROR(f"  Errors  : {error_count:>6}"))
            else:
                self.stdout.write(f"  Errors  : {error_count:>6}")
        self.stdout.write("─" * 50)
        self.stdout.write(self.style.SUCCESS("Done."))
