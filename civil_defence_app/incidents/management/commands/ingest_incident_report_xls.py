"""
Management command: ingest_incident_report_xls

Reads a legacy Civil Defence incident register (Excel .xls or .xlsx) such as
``Incident_report_Kolkata.xls`` and creates:

  * one ``Incident`` per data row (title, location, times, description from columns)
  * one ``IncidentLog`` per row (diary text built from "action" / narrative columns)

Run from the Django project directory (where ``manage.py`` lives), for example::

    uv run python manage.py ingest_incident_report_xls --unit kolkata-nsa
    uv run python manage.py ingest_incident_report_xls --xls /path/to/file.xls --dry-run

The workbook is not committed to the repo; place the file next to the inner
``civil_defence_app`` package or pass ``--xls`` explicitly.

Column headers are matched flexibly (case-insensitive, substring match) so
slightly different spellings in the sheet still map correctly. If your file
uses unusual names, extend ``TITLE_KEYS``, ``ACTION_KEYS``, etc. below.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone as django_timezone

from civil_defence_app.incidents.models import Incident
from civil_defence_app.incidents.models import IncidentLog
from civil_defence_app.incidents.models import IncidentStatus
from civil_defence_app.incidents.models import IncidentType
from civil_defence_app.personnel.models import Unit

# ---------------------------------------------------------------------------
# Default path to the Kolkata incident register (user-supplied file).
#
# Path layout:
#   .../civil_defence_app/civil_defence_app/incidents/management/commands/this_file.py
# parents[3] is the inner ``civil_defence_app`` Python package — we expect the
# spreadsheet to sit alongside that package as ``Incident_report_Kolkata.xls``.
# ---------------------------------------------------------------------------
DEFAULT_XLS_PATH = Path(__file__).resolve().parents[3] / "Incident_report_Kolkata.xls"

# ---------------------------------------------------------------------------
# Fallback diary text when no action/remark column matched any cell text.
# ---------------------------------------------------------------------------
_NO_ACTION_FALLBACK = (
    "(No narrative cell matched; see incident description.)"
)


# ---------------------------------------------------------------------------
# Header synonym lists: each list is tried in order when locating a column.
#
# ``_find_column`` normalises headers (lowercase, collapse whitespace) and
# returns the first column whose normalised name *contains* any of these
# substrings. That tolerates headers like "Date of Incident" matching "date".
# ---------------------------------------------------------------------------
DATE_KEYS = ("date", "dt", "reporting date", "incident date", "occurrence")
TIME_KEYS = ("time", "hour")
TITLE_KEYS = (
    "nature",
    "type",
    "incident",
    "subject",
    "headline",
    "brief",
    "particulars",
    "case",
)
LOCATION_KEYS = (
    "place",
    "location",
    "venue",
    "address",
    "ps",
    "police station",
    "area",
    "site",
)
ACTION_KEYS = (
    "action",
    "measure",
    "diary",
    "remark",
    "detail",
    "narrative",
    "description",
    "steps",
    "work done",
    "response",
)
# "ending" matches ``Ending Date & Time of Incident`` before generic "time"
# steals that column (see ``_resolve_columns`` order: end before time).
END_DATE_KEYS = ("ending", "end date", "closed", "completion", "relief")

# Explicit ``Incident Type`` column (Kolkata register) — resolved before TITLE_KEYS
# so the substring ``type`` does not need to compete with ``Incident Title``.
REGISTER_TYPE_KEYS = ("incident type",)

# ---------------------------------------------------------------------------
# Keyword groups → ``IncidentType`` value. First matching group wins.
# ---------------------------------------------------------------------------
_INCIDENT_TYPE_RULES: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"flood", "inundat"}), IncidentType.FLOOD),
    (frozenset({"fire", "blaze"}), IncidentType.FIRE),
    (frozenset({"collapse", "building"}), IncidentType.COLLAPSE),
    (frozenset({"cyclone", "storm"}), IncidentType.STORM),
    (frozenset({"accident", "collision", "crash"}), IncidentType.ACCIDENT),
    (frozenset({"drought"}), IncidentType.DROUGHT),
    (frozenset({"epidemic", "disease", "outbreak"}), IncidentType.EPIDEMIC),
    (frozenset({"search", "rescue"}), IncidentType.SEARCH),
)


# ---------------------------------------------------------------------------
# Normalise a single header cell to a comparable lowercase token string.
#
# Excel sometimes has trailing spaces or double spaces; stripping and regex
# collapse makes "Incident  Date" and "incident date" match the same pattern.
# ---------------------------------------------------------------------------
def _normalise_header(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        text = ""
    else:
        text = str(value)
    return re.sub(r"\s+", " ", text.strip().lower())


# ---------------------------------------------------------------------------
# Build a mapping: normalised header -> original column label on the DataFrame.
#
# Pandas keeps the original header strings as column names; we only use the
# normalised form for *searching*, but we must read cell values using the
# original names pandas assigned (especially if duplicates exist — then pandas
# renames to "Unnamed: N" which we still handle).
# ---------------------------------------------------------------------------
def _header_map(df: pd.DataFrame) -> dict[str, str]:
    result: dict[str, str] = {}
    for col in df.columns:
        key = _normalise_header(col)
        if key and key != "nan":
            result[key] = str(col)
    return result


# ---------------------------------------------------------------------------
# Pick the first DataFrame column whose normalised name contains a keyword.
#
# We iterate ``needles`` in order so more specific phrases (e.g. "incident date")
# can be listed before generic ones ("date") if you extend the tuples above.
#
# ``exclude_originals`` drops columns already assigned to another role — e.g.
# "Incident Date" must not double as the title column just because it contains
# the substring "incident".
# ---------------------------------------------------------------------------
def _find_column(
    header_to_col: dict[str, str],
    needles: tuple[str, ...],
    *,
    exclude_originals: set[str] | None = None,
) -> str | None:
    banned = exclude_originals or set()
    for norm, original in header_to_col.items():
        if original in banned:
            continue
        for needle in needles:
            if needle in norm:
                return original
    return None


# ---------------------------------------------------------------------------
# Convert a spreadsheet cell to a clean string (empty string if missing).
#
# pandas uses float NaN for blank cells; ``pd.isna`` catches that without
# turning numeric zeros into missing values incorrectly for our text fields.
# ---------------------------------------------------------------------------
def _cell_str(row: pd.Series, col: str | None) -> str:
    if col is None or col not in row.index:
        return ""
    val = row[col]
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


# ---------------------------------------------------------------------------
# Parse a date/time for one row: combine date column + optional time column.
#
# Indian registers often use DD/MM/YYYY; ``dayfirst=True`` reduces wrong
# month/day swaps. We attach the project ``TIME_ZONE`` (Asia/Kolkata) so
# stored datetimes are timezone-aware like the rest of the Django app.
# ---------------------------------------------------------------------------
def _parse_timestamp(
    row: pd.Series,
    date_col: str | None,
    time_col: str | None,
    tz: ZoneInfo,
) -> django_timezone.datetime | None:
    date_raw = _cell_str(row, date_col)
    time_raw = _cell_str(row, time_col)
    if not date_raw and not time_raw:
        return None

    combined = f"{date_raw} {time_raw}".strip()
    if not combined:
        return None

    parsed = pd.to_datetime(combined, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None

    # ``pd.Timestamp`` → Python ``datetime`` (naive). Django expects aware
    # datetimes when ``USE_TZ`` is True.
    naive = parsed.to_pydatetime()
    if django_timezone.is_naive(naive):
        return django_timezone.make_aware(naive, tz)
    return naive


# ---------------------------------------------------------------------------
# Best-effort ``IncidentType`` guess from free text (title + action + location).
#
# The model stores short codes like "FLOOD"; we scan for English keywords.
# Anything unmatched becomes ``OTHER`` — you can edit the incident in Admin.
# ---------------------------------------------------------------------------
def _guess_incident_type(blob: str) -> str:
    lower = blob.lower()
    for keywords, value in _INCIDENT_TYPE_RULES:
        if any(k in lower for k in keywords):
            return value
    return IncidentType.OTHER


# ---------------------------------------------------------------------------
# Map the spreadsheet ``Incident Type`` cell to a model ``IncidentType`` value.
#
# The Kolkata file uses short English labels (sometimes with typos or extra
# spaces). We normalise whitespace and lowercase, then look up a canonical
# dict; if nothing matches, return None so the caller can fall back to
# ``_guess_incident_type`` from title/description text.
# ---------------------------------------------------------------------------
def _incident_type_from_register_cell(raw: str) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = re.sub(r"\s+", " ", str(raw).strip().lower())
    aliases: dict[str, str] = {
        "fire": IncidentType.FIRE,
        "flood": IncidentType.FLOOD,
        "building collapse": IncidentType.COLLAPSE,
        "collapse": IncidentType.COLLAPSE,
        "search & rescue": IncidentType.SEARCH,
        "search and rescue": IncidentType.SEARCH,
        "storm / cyclone": IncidentType.STORM,
        "strom / cyclone": IncidentType.STORM,
        "storm": IncidentType.STORM,
        "cyclone": IncidentType.STORM,
        "road / rail accident": IncidentType.ACCIDENT,
        "accident": IncidentType.ACCIDENT,
        "drought": IncidentType.DROUGHT,
        "epidemic / disease outbreak": IncidentType.EPIDEMIC,
        "epidemic": IncidentType.EPIDEMIC,
        "others": IncidentType.OTHER,
        "other": IncidentType.OTHER,
    }
    return aliases.get(s)


# ---------------------------------------------------------------------------
# Build the diary text for ``IncidentLog.action_taken``.
#
# We prefer dedicated action/remark columns; if those are empty, we fall back
# to joining every other text column so no information is silently dropped.
# ---------------------------------------------------------------------------
def _build_action_taken(
    row: pd.Series,
    action_col: str | None,
    skip_cols: set[str],
) -> str:
    if action_col:
        direct = _cell_str(row, action_col)
        if direct:
            return direct

    parts: list[str] = []
    for col in row.index:
        col_id = str(col)
        if col_id in skip_cols:
            continue
        chunk = _cell_str(row, col_id)
        if chunk:
            parts.append(f"{col_id}: {chunk}")
    return "\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Build a short incident title (max 255 chars for ``Incident.title``).
#
# Priority: explicit title/nature column → first line of action text →
# generic placeholder so the row still imports.
# ---------------------------------------------------------------------------
def _build_title(row: pd.Series, title_col: str | None, action_col: str | None) -> str:
    if title_col:
        t = _cell_str(row, title_col)
        if t:
            return t[:255]
    if action_col:
        a = _cell_str(row, action_col)
        if a:
            line = a.splitlines()[0].strip()
            return line[:255] if line else "Imported incident"
    return "Imported incident"


# ---------------------------------------------------------------------------
# Build a longer ``Incident.description`` from key columns (not the full dump).
# ---------------------------------------------------------------------------
def _build_description(
    row: pd.Series,
    title_col: str | None,
    location_col: str | None,
    action_col: str | None,
) -> str:
    chunks: list[str] = []
    for label, col in (
        ("Nature / title", title_col),
        ("Location", location_col),
        ("Details", action_col),
    ):
        if col:
            val = _cell_str(row, col)
            if val:
                chunks.append(f"{label}: {val}")
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Read Excel with the right engine: legacy ``.xls`` needs xlrd; ``.xlsx`` uses
# openpyxl (already a project dependency). ``header`` is the 0-based header row
# index understood by pandas (same meaning as ``--header-row`` on the command).
# ---------------------------------------------------------------------------
def _read_excel(path: Path, sheet: str | int, header: int = 0) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        return pd.read_excel(path, sheet_name=sheet, engine="xlrd", header=header)
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, sheet_name=sheet, engine="openpyxl", header=header)
    msg = f"Unsupported spreadsheet extension {suffix!r}; use .xls or .xlsx"
    raise CommandError(msg)


# ---------------------------------------------------------------------------
# Resolved column names after heuristic header matching (see module docstring).
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _ResolvedColumns:
    date_col: str | None
    time_col: str | None
    register_type_col: str | None
    title_col: str | None
    location_col: str | None
    action_col: str | None
    end_date_col: str | None

    def skip_for_action(self) -> set[str]:
        return {
            c
            for c in (
                self.date_col,
                self.time_col,
                self.register_type_col,
                self.title_col,
                self.location_col,
                self.end_date_col,
            )
            if c
        }


# ---------------------------------------------------------------------------
# Assign each logical role to at most one physical column (no double-use).
# ---------------------------------------------------------------------------
def _resolve_columns(hmap: dict[str, str]) -> _ResolvedColumns:
    # Order matters: grab combined start datetime and end datetime before any
    # generic ``time`` match, otherwise ``Ending Date & Time`` is mistaken for
    # a supplemental *start* time column.
    date_col = _find_column(hmap, DATE_KEYS)
    assigned: set[str] = {c for c in (date_col,) if c}
    end_date_col = _find_column(hmap, END_DATE_KEYS, exclude_originals=assigned)
    if end_date_col:
        assigned = assigned | {end_date_col}
    time_col = _find_column(hmap, TIME_KEYS, exclude_originals=assigned)
    if time_col:
        assigned = assigned | {time_col}
    register_type_col = _find_column(
        hmap,
        REGISTER_TYPE_KEYS,
        exclude_originals=assigned,
    )
    if register_type_col:
        assigned = assigned | {register_type_col}
    title_col = _find_column(hmap, TITLE_KEYS, exclude_originals=assigned)
    if title_col:
        assigned = assigned | {title_col}
    location_col = _find_column(hmap, LOCATION_KEYS, exclude_originals=assigned)
    if location_col:
        assigned = assigned | {location_col}
    action_col = _find_column(hmap, ACTION_KEYS, exclude_originals=assigned)
    if action_col:
        assigned = assigned | {action_col}
    return _ResolvedColumns(
        date_col=date_col,
        time_col=time_col,
        register_type_col=register_type_col,
        title_col=title_col,
        location_col=location_col,
        action_col=action_col,
        end_date_col=end_date_col,
    )


# ---------------------------------------------------------------------------
# Parse ``--sheet``: numeric string → int index; otherwise treat as sheet name.
# ---------------------------------------------------------------------------
def _parse_sheet_argument(sheet_opt: str) -> str | int:
    if sheet_opt.isdigit():
        return int(sheet_opt)
    return sheet_opt


# ---------------------------------------------------------------------------
# Look up ``Unit`` by slug (preferred) or exact name (case-insensitive).
# ---------------------------------------------------------------------------
def _get_unit_or_raise(unit_token: str) -> Unit:
    unit = Unit.objects.filter(slug__iexact=unit_token).first()
    if unit is None:
        unit = Unit.objects.filter(name__iexact=unit_token).first()
    if unit is None:
        msg = f"Unknown unit {unit_token!r}; use slug or exact name"
        raise CommandError(msg)
    return unit


class Command(BaseCommand):
    help = (
        "Import Incident + IncidentLog rows from Incident_report_Kolkata.xls "
        "(or another register) for one handling unit."
    )

    # ------------------------------------------------------------------
    # Django wires command-line flags to handler methods via ``add_arguments``.
    # ------------------------------------------------------------------
    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--xls",
            type=Path,
            default=DEFAULT_XLS_PATH,
            help=f"Path to .xls or .xlsx register (default: {DEFAULT_XLS_PATH})",
        )
        parser.add_argument(
            "--unit",
            type=str,
            required=True,
            help="Handling unit: slug (e.g. kolkata-nsa) or exact Unit.name",
        )
        parser.add_argument(
            "--sheet",
            type=str,
            default="0",
            help='Sheet name or 0-based index as string (default: "0" = first sheet)',
        )
        parser.add_argument(
            "--header-row",
            type=int,
            default=0,
            help="0-based row index of column headers (default: 0)",
        )
        parser.add_argument(
            "--status",
            type=str,
            default=IncidentStatus.CLOSED,
            choices=[s.value for s in IncidentStatus],
            help=(
                "Incident.status for imported rows "
                "(default: CLOSED for historical registers)"
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and print counts without writing to the database",
        )

    # ------------------------------------------------------------------
    # ``handle`` is the command entry point: resolve unit, load sheet, loop rows.
    # ------------------------------------------------------------------
    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["xls"].resolve()
        if not path.is_file():
            msg = f"Spreadsheet not found: {path}"
            raise CommandError(msg)

        unit = _get_unit_or_raise(options["unit"].strip())
        sheet = _parse_sheet_argument(options["sheet"])
        header_row: int = options["header_row"]
        df = _read_excel(path, sheet, header=header_row)

        df = df.dropna(how="all")
        if df.empty:
            warn = "No data rows after skipping blank lines."
            self.stdout.write(self.style.WARNING(warn))
            return

        cols = _resolve_columns(_header_map(df))
        tz = ZoneInfo(str(settings.TIME_ZONE))
        target_status: str = options["status"]
        dry_run: bool = options["dry_run"]

        self.stdout.write(
            "Columns detected: "
            f"date={cols.date_col!r}, time={cols.time_col!r}, "
            f"register_type={cols.register_type_col!r}, "
            f"title={cols.title_col!r}, "
            f"location={cols.location_col!r}, action={cols.action_col!r}, "
            f"end={cols.end_date_col!r}",
        )

        skip_for_action = cols.skip_for_action()
        created_incidents = 0
        created_logs = 0

        # ------------------------------------------------------------------
        # Wrap the whole import in a transaction so a mid-file error rolls back.
        # ``dry_run`` still parses everything but rolls back at the end.
        # ------------------------------------------------------------------
        with transaction.atomic():
            for _idx, row in df.iterrows():
                action_taken = _build_action_taken(
                    row,
                    cols.action_col,
                    skip_for_action,
                )
                title = _build_title(row, cols.title_col, cols.action_col)
                # Skip blank template rows (e.g. trailing ``Sl No`` only) — require at
                # least one of the register's title or narrative cells, not merely
                # incidental columns like serial numbers or volunteer lists alone.
                has_title_cell = bool(
                    cols.title_col and _cell_str(row, cols.title_col),
                )
                has_desc_cell = bool(
                    cols.action_col and _cell_str(row, cols.action_col),
                )
                if not has_title_cell and not has_desc_cell:
                    continue
                if title == "Imported incident" and not action_taken:
                    continue

                start_time = _parse_timestamp(row, cols.date_col, cols.time_col, tz)
                end_time = _parse_timestamp(row, cols.end_date_col, None, tz)
                location_text = _cell_str(row, cols.location_col)[:500]
                description = _build_description(
                    row,
                    cols.title_col,
                    cols.location_col,
                    cols.action_col,
                )

                type_blob = f"{title} {action_taken} {location_text}"
                register_raw = _cell_str(row, cols.register_type_col)
                incident_type = (
                    _incident_type_from_register_cell(register_raw)
                    or _guess_incident_type(type_blob)
                )

                if dry_run:
                    created_incidents += 1
                    created_logs += 1
                    continue

                incident = Incident.objects.create(
                    unit=unit,
                    title=title,
                    incident_type=incident_type,
                    status=target_status,
                    location_text=location_text,
                    start_time=start_time,
                    end_time=end_time,
                    description=description,
                    reported_by=None,
                )

                log_ts = start_time or django_timezone.now()
                IncidentLog.objects.create(
                    incident=incident,
                    timestamp=log_ts,
                    action_taken=action_taken or _NO_ACTION_FALLBACK,
                    entered_by=None,
                )
                created_incidents += 1
                created_logs += 1

            if dry_run:
                transaction.set_rollback(True)

        mode = "DRY-RUN" if dry_run else "IMPORT"
        summary = (
            f"[{mode}] {created_incidents} incident(s), "
            f"{created_logs} log entry(ies) for unit {unit.name!r} from {path.name}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
