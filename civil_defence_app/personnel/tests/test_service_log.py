"""
Unit tests for personnel.service_log helpers.

These functions only depend on the standard library and Django timezone
utilities — no database required for the overlap / summary tests below.
"""

from __future__ import annotations

from datetime import date
from datetime import datetime

import pytest
from django.utils import timezone

from civil_defence_app.personnel.service_log import ServiceLogRow
from civil_defence_app.personnel.service_log import build_year_summary
from civil_defence_app.personnel.service_log import days_overlap_calendar_year
from civil_defence_app.personnel.service_log import effective_end_date_for_row
from civil_defence_app.personnel.service_log import inclusive_days_between


def test_inclusive_days_between_counts_endpoints():
    """Inclusive range: same start and end counts as one day."""
    d0 = date(2026, 3, 1)
    d1 = date(2026, 3, 5)
    assert inclusive_days_between(d0, d1) == 5


def test_days_overlap_calendar_year_splits_across_january():
    """A range crossing New Year contributes days to each year separately."""
    start = date(2025, 12, 30)
    end = date(2026, 1, 2)
    assert days_overlap_calendar_year(start, end, 2025) == 2
    assert days_overlap_calendar_year(start, end, 2026) == 2


def test_build_year_summary_empty():
    """No deployments → empty summary list."""
    assert build_year_summary([]) == []


def test_build_year_summary_operational_and_office(monkeypatch):
    """
    One operational row and one office row in the same year should both
    contribute to that year's totals.
    """
    fixed = timezone.make_aware(datetime(2026, 6, 15, 12, 0, 0))
    monkeypatch.setattr(timezone, "localdate", lambda: fixed.date())
    monkeypatch.setattr(timezone, "now", lambda: fixed)

    rows = [
        ServiceLogRow(
            deployment_kind="OPERATIONAL",
            label="X",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 3),
            incident_pk=1,
            sort_key=fixed,
        ),
        ServiceLogRow(
            deployment_kind="OFFICE",
            label="Office duty",
            period_start=date(2026, 3, 10),
            period_end=date(2026, 3, 12),
            incident_pk=None,
            sort_key=fixed,
        ),
    ]
    summary = build_year_summary(rows)
    assert len(summary) == 1
    row = summary[0]
    assert row["year"] == 2026
    assert row["operational_days"] == 3
    assert row["office_days"] == 3
    assert row["total_days"] == 6


def test_effective_end_date_for_row_uses_today_when_open(monkeypatch):
    """Open deployments (period_end None) use the mocked local date for totals."""
    fixed = date(2026, 4, 1)
    monkeypatch.setattr(timezone, "localdate", lambda: fixed)
    row = ServiceLogRow(
        deployment_kind="OFFICE",
        label="Office duty",
        period_start=date(2026, 3, 1),
        period_end=None,
        incident_pk=None,
        sort_key=timezone.now(),
    )
    assert effective_end_date_for_row(row) == fixed
