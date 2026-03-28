"""
Management command: seed_equipment

Usage:
    uv run python manage.py seed_equipment
    uv run python manage.py seed_equipment --xlsx /path/to/Equipment list.xlsx
    uv run python manage.py seed_equipment --dry-run

What it does:
    1. Reads "Equipment list.xlsx" (the district-level equipment register).
    2. The sheet has a PIVOT layout:
         Row 0 : equipment type names (every odd column from col 1 onwards)
         Row 1 : "Total" / "Functional" sub-headers (pairs of columns)
         Row 2+ : one row per district/unit — col 0 = district name,
                  then pairs of numbers (total, functional) for each type.
    3. For every district × equipment-type pair where total > 0:
         - Resolves the district name to a DB Unit (via UNIT_NAME_MAP).
         - Units that don't yet exist (e.g. Purba Medinipur) are created.
         - Creates one Equipment DB row per physical unit (total rows, not
           one aggregated row).
         - unique_id = "{UNIT_SLUG_UPPER}-{EQUIP_CODE}-{SL_NO:03d}"
           e.g. "ALIPURDUAR-GEN-SET-001"
    4. Functional assignment logic:
         - "Earlier serial number ⟹ bought earlier ⟹ more likely worn out"
         - The LAST `functional_count` items → is_functional=True, status="OK"
         - The FIRST `total - functional_count` items → is_functional=False,
           status="REPAIR"
         - e.g. Total=5, Functional=3 →
               SL 001, 002  : is_functional=False  (older)
               SL 003, 004, 005 : is_functional=True   (newer)
    5. Skipped rows:
         - "Total" summary row at the bottom of the sheet.
         - "Kolkata" (one row covering three separate DB units — cannot be
           automatically split, so it is skipped with a warning).

Unit name mapping:
    The equipment file uses mixed-case district names that differ from the
    all-caps, sometimes-abbreviated names stored in the DB from the volunteer
    import.  UNIT_NAME_MAP translates them explicitly so every district
    resolves correctly, including:
        • Bardhaman ↔ Burdwan  (old vs new official spelling)
        • "North 24 Pgs" ↔ "NORTH24 PGS"
        • "Kalimpong" ↔ "KALIMPOLNG"  (DB has a typo — we preserve it)

Idempotency:
    Equipment rows are upserted on `unique_id` (update_or_create), so the
    command is safe to re-run — it will update existing rows, not duplicate them.

New units:
    Purba Medinipur, Purulia, CCDTI, WBCEF, WWCD did not appear in the
    volunteer register (0 rows), so they were never seeded.  This command
    creates them automatically on first run.
"""

from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from civil_defence_app.equipment.models import Equipment, EquipmentCategory, EquipmentStatus
from civil_defence_app.personnel.models import Unit


# ─────────────────────────────────────────────────────────────────────────────
# DEFAULT FILE PATH
#
# This file lives at:
#   civil_defence_app/civil_defence_app/equipment/management/commands/seed_equipment.py
# parents[5] resolves to the project root:  civil_defence/
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_XLSX_PATH = Path(__file__).resolve().parents[5] / "Equipment list.xlsx"


# ─────────────────────────────────────────────────────────────────────────────
# UNIT NAME MAP
#
# Key   = district name as it appears in column 0 of the Excel sheet.
# Value = unit name as stored in the DB (from the volunteer import).
#
# Rules used to build this map:
#   • Simple case differences handled programmatically (key.upper()).
#   • "Bardhaman" vs "Burdwan" — Burdwan is the older colonial spelling still
#     used in the volunteer register; Bardhaman is the official current name.
#   • Spacing differences (e.g. "North 24 Pgs" vs "NORTH24 PGS").
#   • DB typo: KALIMPOLNG (should be Kalimpong) — we map to the existing typo.
#   • New units (not yet in DB) map to their intended DB name; they will be
#     created by get_or_create during the run.
#   • "Kolkata" maps to None → skip (covers 3 DB units: CSA, NSA, SSA).
#   • "Total" row maps to None → skip (summary row, not a real unit).
# ─────────────────────────────────────────────────────────────────────────────

UNIT_NAME_MAP: dict[str, str | None] = {
    "Alipurduar":       "ALIPURDUAR",
    "Bankura":          "BANKURA",
    "Birbhum":          "BIRBHUM",
    "Coochbehar":       "COOCHBEHAR",
    "Dakshin Dinajpur": "DAKSHIN DINAJPUR",
    "Darjeeling":       "DARJEELING",
    "Howrah":           "HOWRAH",
    "Hooghly":          "HOOGHLY",
    "Jalpaiguri":       "JALPAIGURI",
    "Jhargram":         "JHARGRAM",
    "Kalimpong":        "KALIMPOLNG",        # DB has this typo — preserve it
    "Malda":            "MALDA",
    "Murshidabad":      "MURSHIDABAD",
    "Nadia":            "NADIA",
    "North 24 Pgs":     "NORTH24 PGS",
    "Paschim Bardhaman":"PASCHIM BURDWAN",   # Bardhaman = Burdwan (old spelling)
    "Paschim Medinipur":"PASCHIM MEDINIPUR",
    "Purba Medinipur":  "PURBA MEDINIPUR",   # will be created (0 volunteers)
    "Purba Bardhaman":  "PURBA BURDWAN",     # Bardhaman = Burdwan
    "Purulia":          "PURULIA",           # will be created (0 volunteers)
    "South 24 Pgs":     "SOUTH24 PGS",
    "Uttar Dinajpur":   "UTTAR DINAJ PUR",
    "CCDTI":            "CCDTI",             # training institute — new unit
    "WBCEF":            "WBCEF",             # new unit
    "WWCD":             "WWCD",              # new unit
    # Kolkata → None: single row in the file covers 3 DB units (CSA/NSA/SSA).
    # Cannot be split automatically; skipped with a warning.
    "Kolkata":          None,
    # The bottom row of the sheet is a grand-total summary — not a unit.
    "Total":            None,
}


# ─────────────────────────────────────────────────────────────────────────────
# EQUIPMENT CODE MAP
#
# Key   = exact equipment name string from row 0 of the Excel (may have leading/
#         trailing spaces or unusual spelling — we strip before lookup).
# Value = (short_code, category)
#   short_code  : uppercase alphanumeric token used inside the unique_id.
#   category    : one of the EquipmentCategory choice values.
#
# Naming convention for short_code:
#   ≤ 10 characters, hyphens allowed, abbreviate logically so IDs are human-
#   readable (e.g. "ALIPURDUAR-GEN-SET-001" is immediately understandable).
# ─────────────────────────────────────────────────────────────────────────────

EQUIP_META: dict[str, tuple[str, str]] = {
    "Portable Generator Set":                ("GEN-SET",    EquipmentCategory.OTHER),
    "Air Compressor Machine":                ("AIR-COMP",   EquipmentCategory.RESCUE),
    "Power Ascender (Battery Operated)":     ("PWR-ASC",    EquipmentCategory.RESCUE),
    "Rope Delivery Gun (Rope Launcher)":     ("ROPE-GUN",   EquipmentCategory.RESCUE),
    "Circular Saw":                          ("CIRC-SAW",   EquipmentCategory.RESCUE),
    "Bullet Chain Saw":                      ("BLT-SAW",    EquipmentCategory.RESCUE),
    "Diamond Chain Saw":                     ("DMD-SAW",    EquipmentCategory.RESCUE),
    "Disposable Mask":                       ("DISP-MASK",  EquipmentCategory.PERSONAL),
    "Fiber Respac Stretcher":                ("FB-STRTCH",  EquipmentCategory.MEDICAL),
    "Life Jacket with Reflective Panel":     ("LIFE-JCKT",  EquipmentCategory.FLOOD),
    "Canvas Stretcher":                      ("CNV-STRTCH", EquipmentCategory.MEDICAL),
    "Screw Carabiner":                       ("SCR-CARAB",  EquipmentCategory.RESCUE),
    "Fire Axe":                              ("FIRE-AXE",   EquipmentCategory.FIRE),
    "Quick Draw (incl. 02 carabiners)":      ("QCK-DRAW",   EquipmentCategory.RESCUE),
    "Stop Lock Decender":                    ("STP-LOCK",   EquipmentCategory.RESCUE),
    "Fixe Pully":                            ("FXE-PULY",   EquipmentCategory.RESCUE),
    "Tandem Pully":                          ("TDM-PULY",   EquipmentCategory.RESCUE),
    "Gri-Gri":                               ("GRI-GRI",    EquipmentCategory.RESCUE),
    "Manual Ascender (Left & Right)":        ("MNL-ASC",    EquipmentCategory.RESCUE),
    "ID Jacket (Flourecent Orange Reflective)": ("ID-JCKT", EquipmentCategory.PERSONAL),
    "Semi Static Kernmental Rope 10-11 mm (100 mtr)": ("ROPE-SS-10", EquipmentCategory.RESCUE),
    "Kernmental Rope 5-6 mm (100 mtr)":     ("ROPE-5MM",   EquipmentCategory.RESCUE),
    "Kernmental Rope 12.72-13.5 mm (100 mtr)": ("ROPE-13MM", EquipmentCategory.RESCUE),
    "Harness Chair (Rescue Chair)":          ("HRNS-CHR",   EquipmentCategory.RESCUE),
    "Seat Harness Adjustable":               ("SEAT-HRNS",  EquipmentCategory.RESCUE),
    "Full Body Harness":                     ("BODY-HRNS",  EquipmentCategory.RESCUE),
    "Hand held Search Light":                ("SRCH-LITE",  EquipmentCategory.RESCUE),
    "Portable Emergency Lighting System":    ("EMRG-LITE",  EquipmentCategory.OTHER),
    "FRP Industrial Safety Helmet (Without Visor)": ("HLMT-FRP", EquipmentCategory.PERSONAL),
    "FRP Helmet with visor":                 ("HLMT-VSOR",  EquipmentCategory.PERSONAL),
    "Safety Helmet with LED Lamp":           ("HLMT-LED",   EquipmentCategory.PERSONAL),
    "Mitton Gloves":                         ("MITT-GLVS",  EquipmentCategory.PERSONAL),
    "Heavy Duty Working Gloves":             ("HD-GLVS",    EquipmentCategory.PERSONAL),
    "Free fall arrest net with stand":       ("FALL-NET",   EquipmentCategory.RESCUE),
    "Hydraulic Jack":                        ("HYD-JACK",   EquipmentCategory.RESCUE),
    "Telescopic Aluminum Ladder (35ft)":     ("TLSC-LADR",  EquipmentCategory.RESCUE),
    "Crow bar":                              ("CROW-BAR",   EquipmentCategory.RESCUE),
    "Spade (5ft)":                           ("SPADE",      EquipmentCategory.RESCUE),
    "Shovel":                                ("SHOVEL",      EquipmentCategory.RESCUE),
    "Sledge Hammer":                         ("SLDG-HAMR",  EquipmentCategory.RESCUE),
    "Foot Tape Sling 120cm":                 ("SLING-120",  EquipmentCategory.RESCUE),
    "Foot Tape Sling 150 cm":                ("SLING-150",  EquipmentCategory.RESCUE),
    "Come alone (Pulling & Lifting Machine)":("COME-ALON",  EquipmentCategory.RESCUE),
    "Woolen Blanket":                        ("WL-BLNKT",   EquipmentCategory.FLOOD),
    "First Aid Box (with medicine)":         ("FIRST-AID",  EquipmentCategory.MEDICAL),
    "Demolition Hammer":                     ("DEMO-HAMR",  EquipmentCategory.RESCUE),
    "Mega Phone with Sling":                 ("MEGA-PHON",  EquipmentCategory.COMM),
    "CBRN Mask With BA Set":                 ("CBRN-MASK",  EquipmentCategory.PERSONAL),
    "Search Camera with Accessories":        ("SRCH-CAM",   EquipmentCategory.RESCUE),
    "Tripod with Winch":                     ("TRPD-WNCH",  EquipmentCategory.RESCUE),
    "Fire entry Suit with BA set":           ("FIRE-SUIT",  EquipmentCategory.FIRE),
    "SCUBA Set with Accessories":            ("SCUBA",      EquipmentCategory.FLOOD),
    "Battery Operated Metal Cutter":         ("MTL-CUTR",   EquipmentCategory.RESCUE),
    "Boot Hard Toes (Gum Boot)":             ("GUM-BOOT",   EquipmentCategory.PERSONAL),
    "Knee Pad":                              ("KNEE-PAD",   EquipmentCategory.PERSONAL),
    "Telescopic Stand with 02 Helogen Light":("TLSC-LGHT",  EquipmentCategory.RESCUE),
    "Pole Purner":                           ("POLE-PRNR",  EquipmentCategory.RESCUE),
    "INF Boat along with Accessories":       ("INF-BOAT",   EquipmentCategory.FLOOD),
    "Out Board Motor (OBM)":                 ("OBM",        EquipmentCategory.FLOOD),
    "Life Buoy":                             ("LIFE-BUOY",  EquipmentCategory.FLOOD),
    "Civil Defence Rescue Vehicle (Big)":    ("VEH-BIG",    EquipmentCategory.OTHER),
    "Civil Defence Rescue Vehicle (Mini)":   ("VEH-MINI",   EquipmentCategory.OTHER),
}


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def clean_equip_name(raw: str) -> str:
    """
    Strip leading/trailing whitespace from an equipment name cell so it
    matches the keys in EQUIP_META regardless of Excel formatting.

    The Excel header row has cells like ' Gri-Gri' (leading space) or
    'Portable  Generator Set ' (trailing space, double internal space).
    We normalise to single internal spaces and strip edges.
    """
    import re
    return re.sub(r"\s+", " ", str(raw).strip())


def safe_int(val) -> int:
    """
    Convert a cell value to a non-negative integer.

    Cells can be NaN (empty), float (e.g. 3.0), or already int.
    Any non-numeric or negative value is treated as 0.
    """
    try:
        result = int(float(val))
        return max(result, 0)
    except (ValueError, TypeError):
        return 0


def parse_equipment_sheet(xlsx_path: Path) -> list[dict]:
    """
    Parse the pivot-style 'All Item current' sheet into a flat list of dicts.

    Each dict represents one (district, equipment_type) pair and has:
        district_raw  : the district name as written in the file (col 0)
        equip_name    : the equipment type name (stripped, from row 0)
        total         : total quantity owned by this district
        functional    : how many of those are currently functional

    The sheet structure:
        Row 0   : [ "District",  "Equipment A",  NaN, "Equipment B",  NaN, … ]
        Row 1   : [ NaN,         "Total",  "Functional",  "Total", "Functional", … ]
        Row 2+  : [ "Alipurduar", 3,        2,             5,       5,           … ]

    Equipment names sit at even-indexed columns (0, 2, 4, …) if you count
    from the name-columns only; in raw DataFrame terms they are at columns
    1, 3, 5, … (every second column starting at 1).  The paired Total/
    Functional values sit immediately to the right at col_idx and col_idx+1.
    """
    import pandas as pd

    df = pd.read_excel(xlsx_path, sheet_name="All Item current", header=None)

    # ── Build equipment name → (total_col_idx, functional_col_idx) map ───────
    #
    # Row 0 has the equipment names in every odd column (1, 3, 5 …).
    # The Total count is in that same column; Functional is one column to the right.
    equipment_columns: list[tuple[str, int, int]] = []   # (equip_name, total_col, func_col)
    for col_idx in range(1, len(df.columns), 2):
        raw_name = df.iloc[0, col_idx]
        if not isinstance(raw_name, str):
            continue
        equip_name = clean_equip_name(raw_name)
        if not equip_name or equip_name.lower() == "nan":
            continue
        total_col = col_idx
        func_col  = col_idx + 1
        equipment_columns.append((equip_name, total_col, func_col))

    # ── Iterate over data rows (row index 2 onwards) ──────────────────────────
    #
    # Row index 0 = equipment names, row index 1 = Total/Functional headers,
    # row index 2+ = actual district data.
    records: list[dict] = []
    for row_idx in range(2, len(df)):
        district_raw = str(df.iloc[row_idx, 0]).strip()
        if not district_raw or district_raw.lower() == "nan":
            continue

        for equip_name, total_col, func_col in equipment_columns:
            total      = safe_int(df.iloc[row_idx, total_col])
            functional = safe_int(df.iloc[row_idx, func_col])

            # Clamp: functional can never exceed total (data quality guard)
            functional = min(functional, total)

            if total == 0:
                continue   # nothing to import for this cell

            records.append({
                "district_raw": district_raw,
                "equip_name":   equip_name,
                "total":        total,
                "functional":   functional,
            })

    return records


# ─────────────────────────────────────────────────────────────────────────────
# MANAGEMENT COMMAND
# ─────────────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    """
    Django management command that seeds the Equipment table from the district
    equipment register Excel file.

    BaseCommand gives us:
        self.stdout  — coloured output stream
        self.stderr  — error stream
        self.style   — colour helpers (.SUCCESS, .WARNING, .ERROR)
    """

    help = "Seed Equipment records from 'Equipment list.xlsx'"

    def add_arguments(self, parser):
        parser.add_argument(
            "--xlsx",
            type=str,
            default=str(DEFAULT_XLSX_PATH),
            help=f"Path to the Equipment list xlsx file (default: {DEFAULT_XLSX_PATH})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and print stats without writing anything to the database",
        )

    # ─────────────────────────────────────────────────────────────────────────

    def handle(self, *args, **options):
        xlsx_path = Path(options["xlsx"])
        dry_run   = options["dry_run"]

        self.stdout.write(f"XLSX file : {xlsx_path}")
        self.stdout.write(f"Dry run   : {dry_run}\n")

        # ── 1. Validate file exists ───────────────────────────────────────────
        if not xlsx_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {xlsx_path}"))
            return

        try:
            import pandas as pd  # noqa: F401
        except ImportError:
            self.stderr.write(self.style.ERROR(
                "pandas is not installed.  Run: uv add pandas openpyxl"
            ))
            return

        # ── 2. Parse the sheet into flat records ─────────────────────────────
        self.stdout.write("Parsing Excel sheet …")
        records = parse_equipment_sheet(xlsx_path)
        self.stdout.write(self.style.SUCCESS(
            f"  → {len(records)} (district × equipment) pairs with qty > 0"
        ))

        # ── 3. Resolve / create Unit objects ─────────────────────────────────
        #
        # We build a cache { db_unit_name → Unit instance } so we only hit the
        # DB once per unit instead of once per equipment row.
        self.stdout.write("\nResolving units …")

        unit_cache: dict[str, Unit] = {}
        skipped_districts: set[str] = set()
        # seen_in_dry_run tracks districts we've already printed a line for so
        # the console output shows one line per district, not one per record.
        seen_in_dry_run: set[str] = set()

        for rec in records:
            district_raw = rec["district_raw"]
            if district_raw in unit_cache or district_raw in skipped_districts:
                continue
            if dry_run and district_raw in seen_in_dry_run:
                continue

            db_name = UNIT_NAME_MAP.get(district_raw)

            if db_name is None:
                # Explicit None = intentionally skipped (e.g. "Kolkata", "Total")
                self.stdout.write(
                    self.style.WARNING(f"  [SKIP ] {district_raw!r} — no DB mapping (intentional)")
                )
                skipped_districts.add(district_raw)
                continue

            if district_raw not in UNIT_NAME_MAP:
                # Not in the map at all — unknown entry; skip with a louder warning
                self.stdout.write(
                    self.style.ERROR(f"  [WARN ] {district_raw!r} — not in UNIT_NAME_MAP; skipping")
                )
                skipped_districts.add(district_raw)
                continue

            if not dry_run:
                # get_or_create is idempotent: existing units are reused,
                # new ones (Purba Medinipur, Purulia, CCDTI, WBCEF, WWCD) are made.
                unit, created = Unit.objects.get_or_create(
                    name=db_name,
                    defaults={"slug": slugify(db_name)},
                )
                unit_cache[district_raw] = unit
                marker = "CREATED" if created else "EXISTS "
                self.stdout.write(f"  [{marker}] {district_raw!r} → {db_name!r}")
            else:
                self.stdout.write(f"  [DRY  ] {district_raw!r} → {db_name!r}")
                seen_in_dry_run.add(district_raw)

        # ── 4. Seed Equipment rows ────────────────────────────────────────────
        self.stdout.write("\nSeeding equipment …")

        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_count   = 0
        unknown_equip: set[str] = set()

        for rec in records:
            district_raw = rec["district_raw"]
            equip_name   = rec["equip_name"]
            total        = rec["total"]
            functional   = rec["functional"]

            # Skip rows whose district was not resolved
            if district_raw in skipped_districts:
                skipped_count += total
                continue

            # Resolve the equipment metadata (short code + category)
            meta = EQUIP_META.get(equip_name)
            if meta is None:
                # Try stripping the name again in case of minor whitespace variation
                meta = EQUIP_META.get(clean_equip_name(equip_name))

            if meta is None:
                if equip_name not in unknown_equip:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [WARN ] Equipment name not in EQUIP_META: {equip_name!r}"
                        )
                    )
                    unknown_equip.add(equip_name)
                skipped_count += total
                continue

            equip_code, category = meta

            if dry_run:
                skipped_count += total
                continue

            unit = unit_cache.get(district_raw)
            if unit is None:
                skipped_count += total
                continue

            # ── Determine which serial numbers are functional ─────────────
            #
            # We have `total` physical items and `functional` of them work.
            # Assumption: lower serial number = bought earlier = more worn out.
            # Therefore the LAST `functional` items get is_functional=True.
            #
            # non_functional_count = total - functional
            # SL 001 … (total - functional)  → is_functional=False
            # SL (total - functional + 1) … total → is_functional=True
            non_functional_count = total - functional
            unit_slug_upper = unit.slug.upper()

            for sl in range(1, total + 1):
                # sl goes 1, 2, 3, … total
                # Items 1 through non_functional_count are non-functional (older)
                is_functional = sl > non_functional_count
                status = EquipmentStatus.FUNCTIONAL if is_functional else EquipmentStatus.REPAIR

                unique_id = f"{unit_slug_upper}-{equip_code}-{sl:03d}"

                defaults = {
                    "name":         equip_name,
                    "category":     category,
                    "quantity":     1,          # individual-item tracking: always 1
                    "status":       status,
                    "is_functional": is_functional,
                }

                try:
                    _, was_created = Equipment.objects.update_or_create(
                        unique_id=unique_id,
                        defaults=defaults,
                        # unit FK can also change if data is corrected; update it too
                        create_defaults={"unit": unit, **defaults},
                    )
                    # For existing records, ensure the unit FK is always current.
                    # update_or_create's defaults don't update FK if the row existed,
                    # so we patch it explicitly only when needed.
                    if not was_created:
                        existing = Equipment.objects.get(unique_id=unique_id)
                        if existing.unit_id != unit.pk:
                            existing.unit = unit
                            existing.save(update_fields=["unit"])

                    if was_created:
                        created_count += 1
                    else:
                        updated_count += 1

                except Exception as exc:
                    error_count += 1
                    self.stderr.write(
                        self.style.WARNING(
                            f"  Row error ({unique_id}): {exc}"
                        )
                    )

        # ── 5. Print summary ──────────────────────────────────────────────────
        self.stdout.write("\n" + "─" * 55)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no records written to the database"))
            self.stdout.write(f"  Would process {len(records)} (district × equipment) pairs")
        else:
            self.stdout.write(self.style.SUCCESS(f"  Created  : {created_count:>6}"))
            self.stdout.write(self.style.SUCCESS(f"  Updated  : {updated_count:>6}"))
            self.stdout.write(f"  Skipped  : {skipped_count:>6}")
            if error_count:
                self.stdout.write(self.style.ERROR(f"  Errors   : {error_count:>6}"))
            else:
                self.stdout.write(f"  Errors   : {error_count:>6}")
            if unknown_equip:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Unknown equipment types ({len(unknown_equip)}): "
                        + ", ".join(sorted(unknown_equip))
                    )
                )
        self.stdout.write("─" * 55)
        self.stdout.write(self.style.SUCCESS("Done."))
