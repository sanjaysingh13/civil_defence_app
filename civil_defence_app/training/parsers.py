"""
Parse legacy free-text training fields from Volunteer records.

The source Parquet / Excel stores:

  • basic_training_details  — e.g.
        "PLACE-ALIPURDUAR CIRCUIT HOUSE,  (09.12.2013 TO 13.12.2013)"
    We extract venue text plus start/end dates for linking to a
    TrainingInstance of the canonical "Civil Defence Basic Training" programme.

  • special_training_details — e.g.
        "1.AAPDA MITRA 2.MDT  3. FIRE FIGHTING 4.WARDEN SERVICE 5.TOT"
    We split on numbered list markers and map each token to a canonical
    Training row (Aapda Mitra, MDT, Fire Fighting, …).

These functions are pure (no DB access) so they are easy to unit-test.
"""

from __future__ import annotations

import datetime
import re
from typing import TypedDict


class BasicTrainingParsed(TypedDict):
    """Structured result of parsing ``basic_training_details``."""

    location: str
    start_date: datetime.date
    end_date: datetime.date


# ─────────────────────────────────────────────────────────────────────────────
# DATE PARSING  (DD.MM.YYYY as used throughout Indian government forms)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dd_mm_yyyy(token: str) -> datetime.date | None:
    """
    Convert a string like '09.12.2013' into a datetime.date.

    Returns None if the string does not match the expected pattern or is an
    invalid calendar date.
    """
    token = token.strip()
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", token)
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# BASIC TRAINING  —  PLACE-… , (DD.MM.YYYY TO DD.MM.YYYY)
# ─────────────────────────────────────────────────────────────────────────────

# Primary pattern: PLACE-venue, (start TO end)
_BASIC_PRIMARY = re.compile(
    r"PLACE[-\s]*(.+?),\s*\(\s*(\d{1,2}\.\d{1,2}\.\d{4})\s+TO\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*\)",
    flags=re.IGNORECASE | re.DOTALL,
)

# Fallback: parentheses block without leading "PLACE-"
_BASIC_FALLBACK = re.compile(
    r"\(\s*(\d{1,2}\.\d{1,2}\.\d{4})\s+TO\s+(\d{1,2}\.\d{1,2}\.\d{4})\s*\)",
    flags=re.IGNORECASE,
)


def parse_basic_training_details(raw: str) -> BasicTrainingParsed | None:
    """
    Parse ``Volunteer.basic_training_details`` into location + date range.

    Returns None if the text is empty or cannot be parsed reliably.
    """
    if not raw or not str(raw).strip():
        return None

    text = " ".join(str(raw).split())

    m = _BASIC_PRIMARY.search(text)
    if m:
        loc = m.group(1).strip()
        s = _parse_dd_mm_yyyy(m.group(2))
        e = _parse_dd_mm_yyyy(m.group(3))
        if s and e and loc:
            return {"location": loc[:255], "start_date": s, "end_date": e}
        return None

    # Fallback: only dates in parentheses (venue unknown)
    m2 = _BASIC_FALLBACK.search(text)
    if m2:
        s = _parse_dd_mm_yyyy(m2.group(1))
        e = _parse_dd_mm_yyyy(m2.group(2))
        if s and e:
            return {"location": "", "start_date": s, "end_date": e}

    return None


# ─────────────────────────────────────────────────────────────────────────────
# SPECIAL TRAINING  —  numbered list tokens
# ─────────────────────────────────────────────────────────────────────────────

# Split on "1." "2." etc. — the source often omits space after the dot.
_SPECIAL_SPLIT = re.compile(r"\d+\.\s*")

# Normalised UPPERCASE key → canonical Training.name (must match seed command)
SPECIAL_TOKEN_TO_TRAINING_NAME: dict[str, str] = {
    "AAPDA MITRA":     "Aapda Mitra",
    "AAPDAMITRA":      "Aapda Mitra",
    "MDT":             "MDT",
    "FIRE FIGHTING":   "Fire Fighting",
    "FIREFIGHTING":    "Fire Fighting",
    "WARDEN SERVICE":  "Warden Service",
    "WARDENSERVICE":   "Warden Service",
    "TOT":             "TOT",
    "TRAINER OF TRAINERS": "TOT",
}


def _normalise_special_token(fragment: str) -> str:
    """Collapse whitespace and uppercase for dictionary lookup."""
    return " ".join(fragment.split()).upper()


def parse_special_training_details(raw: str) -> list[str]:
    """
    Parse ``Volunteer.special_training_details`` into canonical programme names.

    Returns a de-duplicated list of Training.name strings in first-seen order.
    Unknown tokens are skipped (not every free-text variation is mapped).
    """
    if not raw or not str(raw).strip():
        return []

    text = str(raw).strip()
    # Split on numbered prefixes; first segment is often empty or preamble.
    parts = _SPECIAL_SPLIT.split(text)
    seen: set[str] = set()
    out: list[str] = []

    for part in parts:
        frag = part.strip()
        if not frag:
            continue
        # Some rows use "1.xxx 2.yyy" on one line — also split on " / " rarely
        key = _normalise_special_token(frag)
        name = SPECIAL_TOKEN_TO_TRAINING_NAME.get(key)
        if name and name not in seen:
            seen.add(name)
            out.append(name)

    return out


def canonical_training_specs():
    """
    Return metadata for every Training row created by the seed command.

    Keys: name, training_type (TrainingType value string), description.
    """
    from civil_defence_app.training.models import TrainingType  # local import avoids circularity at app load

    return [
        {
            "name": "Civil Defence Basic Training",
            "training_type": TrainingType.BASIC,
            "description": (
                "Mandatory foundation course for Civil Defence volunteers. "
                "Linked from legacy basic_training_details text."
            ),
        },
        {
            "name": "Aapda Mitra",
            "training_type": TrainingType.ADVANCED,
            "description": "Aapda Mitra disaster-response programme.",
        },
        {
            "name": "MDT",
            "training_type": TrainingType.ADVANCED,
            "description": "Multi-disciplinary team training.",
        },
        {
            "name": "Fire Fighting",
            "training_type": TrainingType.SPECIALIZED,
            "description": "Fire fighting and rescue techniques.",
        },
        {
            "name": "Warden Service",
            "training_type": TrainingType.SPECIALIZED,
            "description": "Shelter warden / evacuation warden duties.",
        },
        {
            "name": "TOT",
            "training_type": TrainingType.SPECIALIZED,
            "description": "Trainer of Trainers (TOT).",
        },
    ]
