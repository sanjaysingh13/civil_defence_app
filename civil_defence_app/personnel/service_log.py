"""
Service log helpers for volunteers.

*Operational* rows come from IncidentAssignment + Incident: that is the *team*
response (several volunteers on one incident).  *Office* rows come from
OfficeDutyPeriod: *individual* office time per volunteer, not a shared unit-wide
shift.  This module merges both into one chronological list and computes
calendar-day totals per year for wage / summary displays.

Calendar-day counting uses inclusive ranges: one calendar day contributes 1
day.  Periods that span multiple years are split so each year receives only the
overlap with that year's Jan 1–Dec 31.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import Any

from django.utils import timezone

from civil_defence_app.incidents.models import IncidentStatus


# ─────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURE FOR ONE ROW IN THE SERVICE LOG TABLE
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ServiceLogRow:
    """
    One deployment segment shown on the volunteer detail page.

    OPERATIONAL = incident team deployment (this volunteer’s assignment to that
    incident).  OFFICE = individual office duty from OfficeDutyPeriod.
    period_end is None when still open (ongoing incident or open office stretch).
    """

    deployment_kind: str
    label: str
    period_start: date
    period_end: date | None
    incident_pk: int | None
    sort_key: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────────────────────────────────────


def local_date_from_datetime(dt: datetime | None) -> date | None:
    """Convert an aware or naive datetime to a date in the active timezone."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt).date()


def inclusive_days_between(start: date, end: date) -> int:
    """Inclusive count of calendar days from start through end (both ends count)."""
    if end < start:
        return 0
    return (end - start).days + 1


def days_overlap_calendar_year(range_start: date, range_end: date, year: int) -> int:
    """
    Return how many calendar days of [range_start, range_end] fall inside *year*.

    The volunteer may have served across a year boundary; this function only
    counts the portion inside the given *year*.
    """
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    seg_start = max(range_start, year_start)
    seg_end = min(range_end, year_end)
    return inclusive_days_between(seg_start, seg_end)


# ─────────────────────────────────────────────────────────────────────────────
# BUILD LOG + YEAR SUMMARY FROM ORM OBJECTS
# ─────────────────────────────────────────────────────────────────────────────


def build_service_log_rows(volunteer) -> list[ServiceLogRow]:
    """
    Collect operational (incident) and office-duty rows for *volunteer*.

    Expects prefetch_related on incident_assignments__incident and
    office_duty_periods to avoid N+1 queries when callers already optimized
    the queryset.
    """
    rows: list[ServiceLogRow] = []

    for assignment in volunteer.incident_assignments.all():
        incident = assignment.incident
        start_dt = incident.start_time or assignment.assigned_at

        if incident.end_time is not None:
            end_dt: datetime | None = incident.end_time
            ongoing = False
        elif incident.status == IncidentStatus.CLOSED:
            end_dt = incident.updated_at
            ongoing = False
        else:
            end_dt = None
            ongoing = True

        start_d = local_date_from_datetime(start_dt)
        if start_d is None:
            continue

        if ongoing:
            period_end: date | None = None
        else:
            period_end = local_date_from_datetime(end_dt) or start_d

        label = f"{incident.incident_number or '—'} — {incident.title}"
        sort_key = start_dt if start_dt else timezone.now()

        rows.append(
            ServiceLogRow(
                deployment_kind="OPERATIONAL",
                label=label,
                period_start=start_d,
                period_end=period_end,
                incident_pk=incident.pk,
                sort_key=sort_key,
            ),
        )

    for period in volunteer.office_duty_periods.all():
        start_d = local_date_from_datetime(period.started_at)
        if start_d is None:
            continue
        period_end_office = local_date_from_datetime(period.ended_at)
        rows.append(
            ServiceLogRow(
                deployment_kind="OFFICE",
                label="Office duty",
                period_start=start_d,
                period_end=period_end_office,
                incident_pk=None,
                sort_key=period.started_at,
            ),
        )

    rows.sort(key=lambda r: r.sort_key, reverse=True)
    return rows


def effective_end_date_for_row(row: ServiceLogRow) -> date:
    """
    Last calendar day to use when counting days for *row*.

    Open deployments use today's date so year summaries stay current.
    """
    if row.period_end is not None:
        return row.period_end
    return timezone.localdate()


def build_year_summary(rows: list[ServiceLogRow]) -> list[dict[str, Any]]:
    """
    Produce one summary dict per calendar year that overlaps any deployment.

    operational_days and office_days sum inclusive calendar days allocated to
    that year (split when a deployment crosses 1 January).
    """
    if not rows:
        return []

    min_year = min(r.period_start.year for r in rows)
    max_year = max(effective_end_date_for_row(r).year for r in rows)

    result: list[dict[str, Any]] = []
    for year in range(min_year, max_year + 1):
        operational_days = 0
        office_days = 0
        for row in rows:
            end_d = effective_end_date_for_row(row)
            overlap = days_overlap_calendar_year(row.period_start, end_d, year)
            if overlap == 0:
                continue
            if row.deployment_kind == "OPERATIONAL":
                operational_days += overlap
            else:
                office_days += overlap
        result.append(
            {
                "year": year,
                "operational_days": operational_days,
                "office_days": office_days,
                "total_days": operational_days + office_days,
            },
        )
    return result
