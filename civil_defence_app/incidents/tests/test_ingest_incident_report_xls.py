"""
Tests for ``ingest_incident_report_xls`` management command.

We write a tiny .xlsx with pandas (openpyxl) so CI does not need a binary .xls
fixture; the command uses the same column-detection logic for both formats.
"""

from __future__ import annotations

import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from civil_defence_app.incidents.management.commands.ingest_incident_report_xls import (
    _header_map,
)
from civil_defence_app.incidents.management.commands.ingest_incident_report_xls import (
    _incident_type_from_register_cell,
)
from civil_defence_app.incidents.management.commands.ingest_incident_report_xls import (
    _resolve_columns,
)
from civil_defence_app.incidents.models import Incident
from civil_defence_app.incidents.models import IncidentLog
from civil_defence_app.incidents.models import IncidentType
from civil_defence_app.incidents.tests.factories import UnitFactory


@pytest.mark.django_db
def test_ingest_creates_incident_and_log(tmp_path) -> None:
    unit = UnitFactory.create(name="KOLKATA NSA", slug="kolkata-nsa")
    xlsx = tmp_path / "register.xlsx"
    df = pd.DataFrame(
        {
            "Incident Date": ["15/01/2024"],
            "Nature": ["Road accident"],
            "Place": ["Park Street"],
            "Action Taken": ["Team deployed; scene secured."],
        },
    )
    df.to_excel(xlsx, index=False, engine="openpyxl")

    call_command(
        "ingest_incident_report_xls",
        "--xls",
        str(xlsx),
        "--unit",
        "kolkata-nsa",
    )

    assert Incident.objects.filter(unit=unit).count() == 1
    inc = Incident.objects.get(unit=unit)
    assert "accident" in inc.title.lower() or "road" in inc.title.lower()
    assert IncidentLog.objects.filter(incident=inc).count() == 1


@pytest.mark.django_db
def test_dry_run_does_not_persist(tmp_path) -> None:
    UnitFactory.create(name="KOLKATA NSA", slug="kolkata-nsa")
    xlsx = tmp_path / "register.xlsx"
    df = pd.DataFrame(
        {
            "Date": ["10/02/2024"],
            "Remarks": ["Dry run only"],
        },
    )
    df.to_excel(xlsx, index=False, engine="openpyxl")

    call_command(
        "ingest_incident_report_xls",
        "--xls",
        str(xlsx),
        "--unit",
        "kolkata-nsa",
        "--dry-run",
    )

    assert Incident.objects.count() == 0
    assert IncidentLog.objects.count() == 0


def test_resolve_columns_kolkata_register_headers() -> None:
    """
    Regression: ``Ending Date & Time`` must not be picked as *start* ``time_col``
    (substring ``time``); it belongs in ``end_date_col`` only.
    """
    df = pd.DataFrame(
        columns=[
            "Sl No",
            "Incident Title",
            "Incident Type",
            "Location",
            "Incident Date & Time",
            "Incident Description",
            "Volunteers to Dispatch",
            "Equipment to Dispatch",
            "Photo / Video (if Any)",
            "Ending Date & Time of Incident",
            "Remarks",
        ],
    )
    cols = _resolve_columns(_header_map(df))
    assert cols.date_col == "Incident Date & Time"
    assert cols.end_date_col == "Ending Date & Time of Incident"
    assert cols.time_col is None
    assert cols.register_type_col == "Incident Type"
    assert cols.title_col == "Incident Title"
    assert cols.action_col == "Incident Description"


def test_register_incident_type_typo_strom() -> None:
    assert (
        _incident_type_from_register_cell("Strom / Cyclone") == IncidentType.STORM
    )


@pytest.mark.django_db
def test_unknown_unit_raises(tmp_path) -> None:
    xlsx = tmp_path / "stub.xlsx"
    pd.DataFrame({"Date": ["01/01/2024"]}).to_excel(
        xlsx,
        index=False,
        engine="openpyxl",
    )
    with pytest.raises(CommandError, match="Unknown unit"):
        call_command(
            "ingest_incident_report_xls",
            "--xls",
            str(xlsx),
            "--unit",
            "not-a-real-unit-slug-xyz",
        )
