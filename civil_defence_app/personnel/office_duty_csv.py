"""
CSV template generation and upload parsing for monthly office duty (per unit).

The template is UTF-8 with a BOM so Excel on Windows recognises encoding.
Expected columns: serial_no, name, volunteer_id, days_worked (last column empty until filled).
"""

from __future__ import annotations

import calendar
import csv
import io
import re
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from civil_defence_app.personnel.models import OfficeDutyMonthSubmission
from civil_defence_app.personnel.models import Unit
from civil_defence_app.personnel.models import Volunteer
from civil_defence_app.personnel.models import VolunteerOfficeDutyMonth

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser


OFFICE_DUTY_CSV_COLUMNS = ["serial_no", "name", "volunteer_id", "days_worked"]

# Human-readable header row (must match OFFICE_DUTY_CSV_COLUMNS order).
OFFICE_DUTY_CSV_HEADER = ",".join(OFFICE_DUTY_CSV_COLUMNS)


def active_volunteers_for_unit(unit: Unit):
    """Active volunteers for template rows, stable ordering for reproducible CSVs."""
    return Volunteer.objects.filter(unit=unit, is_active=True).order_by(
        "serial_no", "name"
    )


def build_office_duty_template_csv_bytes(unit: Unit, year: int, month: int) -> bytes:
    """
    Build CSV body: one data row per active volunteer; days_worked column empty.

    year/month appear only in the filename from the view; rows are volunteer data only.
    """
    buffer = io.StringIO()
    buffer.write("\ufeff")
    writer = csv.writer(buffer)
    writer.writerow(OFFICE_DUTY_CSV_COLUMNS)
    for vol in active_volunteers_for_unit(unit):
        writer.writerow(
            [
                vol.serial_no or "",
                vol.name or "",
                str(vol.pk),
                "",
            ],
        )
    return buffer.getvalue().encode("utf-8")


def _normalise_header(fieldnames: list[str] | None) -> dict[str, str]:
    """Map normalised column name -> original key for row lookup."""
    if not fieldnames:
        return {}
    out: dict[str, str] = {}
    for raw in fieldnames:
        if raw is None:
            continue
        key = raw.strip().lower().lstrip("\ufeff")
        out[key] = raw
    return out


def _row_get(row: dict[str, str], norm_map: dict[str, str], *aliases: str) -> str:
    for alias in aliases:
        orig = norm_map.get(alias)
        if orig is not None and orig in row:
            return (row.get(orig) or "").strip()
    return ""


def _parse_days(raw: str, year: int, month: int) -> int:
    if raw == "" or raw is None:
        return 0
    if not re.fullmatch(r"-?\d+", raw.strip()):
        raise ValidationError(f"Invalid days value: {raw!r}")
    value = int(raw.strip())
    if value < 0:
        raise ValidationError("Days worked cannot be negative.")
    _w, max_days = calendar.monthrange(year, month)
    if value > max_days:
        raise ValidationError(
            f"Days worked ({value}) cannot exceed {max_days} for this month.",
        )
    return value


def _next_serial_seed_for_unit(unit: Unit) -> tuple[str, int, int, set[str]]:
    """
    Build serial allocation seed for auto-creating volunteers from CSV rows.

    Returns:
      (prefix, next_number, width, used_serials)
    """
    serials = list(
        Volunteer.objects.filter(unit=unit).values_list("serial_no", flat=True),
    )
    used_serials = {str(s or "").strip() for s in serials if str(s or "").strip()}
    best_prefix = ""
    best_num = 0
    best_width = 1
    for raw in used_serials:
        m = re.fullmatch(r"([^\d]*)(\d+)", raw)
        if not m:
            continue
        prefix, num_raw = m.group(1), m.group(2)
        num_val = int(num_raw)
        if num_val >= best_num:
            best_num = num_val
            best_prefix = prefix
            best_width = len(num_raw)
    if best_num <= 0:
        return ("S", 1, 1, used_serials)
    return (best_prefix, best_num + 1, best_width, used_serials)


def _allocate_next_serial_no(
    prefix: str,
    next_number: int,
    width: int,
    used_serials: set[str],
) -> tuple[str, int]:
    """Allocate the next free serial string and return (serial, updated_counter)."""
    n = next_number
    while True:
        num_text = str(n).zfill(width)
        serial = f"{prefix}{num_text}"
        if serial not in used_serials:
            used_serials.add(serial)
            return serial, n + 1
        n += 1


def apply_office_duty_csv_upload(
    file_content: str | bytes,
    unit: Unit,
    year: int,
    month: int,
    user: AbstractBaseUser | None,
) -> int:
    """
    Parse CSV and upsert VolunteerOfficeDutyMonth rows plus submission record.

    Returns the number of volunteer rows processed. Raises ValidationError on failure.
    All DB changes run in one transaction.
    """
    if month < 1 or month > 12:
        raise ValidationError("Month must be 1–12.")
    if year < 2000 or year > 2100:
        raise ValidationError("Year is out of allowed range.")

    if isinstance(file_content, bytes):
        text = file_content.decode("utf-8-sig")
    else:
        text = file_content.lstrip("\ufeff")

    reader = csv.DictReader(io.StringIO(text))
    norm = _normalise_header(reader.fieldnames)
    required = {"serial_no", "name", "volunteer_id", "days_worked"}
    if not norm or not required.issubset(set(norm.keys())):
        raise ValidationError(
            "CSV must include headers: " + ", ".join(OFFICE_DUTY_CSV_COLUMNS),
        )

    rows_parsed: list[tuple[Volunteer, int]] = []
    serial_prefix, next_serial_number, serial_width, used_serials = (
        _next_serial_seed_for_unit(unit)
    )
    for lineno, row in enumerate(reader, start=2):
        vid_raw = _row_get(row, norm, "volunteer_id")
        serial = _row_get(row, norm, "serial_no")
        name = _row_get(row, norm, "name")
        vol: Volunteer
        if not vid_raw:
            if serial:
                raise ValidationError(
                    f"Row {lineno}: volunteer_id is required when serial_no is provided.",
                )
            if not name:
                raise ValidationError(
                    f"Row {lineno}: name is required when adding a new volunteer.",
                )
            serial, next_serial_number = _allocate_next_serial_no(
                prefix=serial_prefix,
                next_number=next_serial_number,
                width=serial_width,
                used_serials=used_serials,
            )
            vol = Volunteer(unit=unit, serial_no=serial, name=name, is_active=True)
        else:
            if not re.fullmatch(r"\d+", vid_raw):
                raise ValidationError(f"Row {lineno}: invalid volunteer_id.")
            vid = int(vid_raw)
            try:
                vol = Volunteer.objects.select_related("unit").get(pk=vid)
            except Volunteer.DoesNotExist as exc:
                raise ValidationError(
                    f"Row {lineno}: unknown volunteer_id {vid}.",
                ) from exc
            if vol.unit_id != unit.pk:
                raise ValidationError(
                    f"Row {lineno}: volunteer {vid} does not belong to the selected unit.",
                )
        if serial and (vol.serial_no or "") != serial:
            raise ValidationError(
                f"Row {lineno}: serial_no does not match volunteer record.",
            )
        days_raw = _row_get(row, norm, "days_worked")
        days = _parse_days(days_raw, year, month)
        rows_parsed.append((vol, days))

    if not rows_parsed:
        raise ValidationError("No data rows found in CSV.")

    recorded = (
        user if user is not None and getattr(user, "is_authenticated", False) else None
    )

    with transaction.atomic():
        count = 0
        for vol, days in rows_parsed:
            if vol.pk is None:
                vol.full_clean()
                vol.save()

            # Keep ingestion idempotent for accidental re-uploads:
            # first try to create the monthly row; if another upload already
            # created it (or race condition), update the existing row instead.
            try:
                obj, created = VolunteerOfficeDutyMonth.objects.get_or_create(
                    volunteer=vol,
                    year=year,
                    month=month,
                    defaults={
                        "days_worked": days,
                        "recorded_by": recorded,
                    },
                )
            except IntegrityError:
                obj = VolunteerOfficeDutyMonth.objects.get(
                    volunteer=vol,
                    year=year,
                    month=month,
                )
                created = False

            if not created:
                obj.days_worked = days
                obj.recorded_by = recorded
                obj.full_clean()
                obj.save()
            count += 1
        OfficeDutyMonthSubmission.objects.update_or_create(
            unit=unit,
            year=year,
            month=month,
            defaults={"submitted_by": recorded},
        )
    return count
