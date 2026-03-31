"""Unit tests for training.parsers (legacy text → structured fields)."""

from __future__ import annotations

import datetime

from civil_defence_app.training.parsers import _parse_dd_mm_yyyy
from civil_defence_app.training.parsers import canonical_training_specs
from civil_defence_app.training.parsers import parse_basic_training_details
from civil_defence_app.training.parsers import parse_special_training_details


def test_parse_basic_alipurduar_example():
    raw = "PLACE-ALIPURDUAR CIRCUIT HOUSE,  (09.12.2013 TO 13.12.2013)"
    out = parse_basic_training_details(raw)
    assert out is not None
    assert "ALIPURDUAR" in out["location"].upper() or "CIRCUIT" in out["location"].upper()
    assert out["start_date"] == datetime.date(2013, 12, 9)
    assert out["end_date"] == datetime.date(2013, 12, 13)


def test_parse_basic_empty():
    assert parse_basic_training_details("") is None
    assert parse_basic_training_details("   ") is None


def test_parse_basic_unparseable_returns_none():
    """No PLACE- block and no (DD.MM.YYYY TO DD.MM.YYYY) pair → None."""
    assert parse_basic_training_details("random text without dates") is None


def test_parse_special_numbered_example():
    raw = "1.AAPDA MITRA 2.MDT  3. FIRE FIGHTING 4.WARDEN SERVICE 5.TOT"
    names = parse_special_training_details(raw)
    assert names == [
        "Aapda Mitra",
        "MDT",
        "Fire Fighting",
        "Warden Service",
        "TOT",
    ]


def test_parse_special_dedupes():
    raw = "1.AAPDA MITRA 1.AAPDA MITRA"
    names = parse_special_training_details(raw)
    assert names == ["Aapda Mitra"]


def test_parse_special_empty():
    assert parse_special_training_details("") == []


def test_parse_dd_mm_yyyy_rejects_non_matching_token():
    assert _parse_dd_mm_yyyy("not-a-date") is None


def test_parse_dd_mm_yyyy_rejects_invalid_calendar_date():
    assert _parse_dd_mm_yyyy("31.02.2020") is None


def test_parse_basic_primary_returns_none_when_dates_invalid():
    """Primary PLACE- regex matches but date tokens fail validation → None."""
    raw = "PLACE-SOMEWHERE, (31.02.2013 TO 13.12.2013)"
    assert parse_basic_training_details(raw) is None


def test_parse_basic_fallback_parentheses_only_dates():
    """Fallback path: dates without PLACE- prefix; venue empty string."""
    raw = "(09.12.2013 TO 13.12.2013)"
    out = parse_basic_training_details(raw)
    assert out is not None
    assert out["location"] == ""
    assert out["start_date"] == datetime.date(2013, 12, 9)
    assert out["end_date"] == datetime.date(2013, 12, 13)


def test_canonical_training_specs_returns_seed_metadata():
    specs = canonical_training_specs()
    assert len(specs) >= 6
    names = {s["name"] for s in specs}
    assert "Civil Defence Basic Training" in names
    assert all("training_type" in s and "description" in s for s in specs)
