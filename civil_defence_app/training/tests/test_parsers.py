"""Unit tests for training.parsers (legacy text → structured fields)."""

from __future__ import annotations

import datetime

from civil_defence_app.training.parsers import (
    parse_basic_training_details,
    parse_special_training_details,
)


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
