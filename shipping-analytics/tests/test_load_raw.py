"""Tests for ingest/load_raw.py. Run from shipping-analytics/:  python -m pytest"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ingest.load_raw import SourceFileError, connect, load_csv, load_new_event_files, pick_merchant_export


def write_events(folder: Path, day: str, event_ids: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"events_{day}.jsonl").open("w", encoding="utf-8") as f:
        for event_id in event_ids:
            row = {
                "event_id": event_id,
                "shipment_id": "S1",
                "event": {"status": "in_transit", "timestamp": f"{day}T10:00:00"},
                "carrier": {"code": "DHL"},
            }
            f.write(json.dumps(row) + "\n")


@pytest.fixture
def con(tmp_path: Path):
    connection = connect(tmp_path / "test.duckdb")
    yield connection
    connection.close()


def test_csv_is_loaded_as_text_with_source_columns(con, tmp_path: Path):
    path = tmp_path / "carriers.csv"
    path.write_text("carrier_code,carrier_name\nDHL,DHL Parcel\n007,Bond Post\n", encoding="utf-8")

    rows = load_csv(con, "carriers", path)

    assert rows == 2
    # Codes stay text: '007' must not become the number 7
    assert con.execute("select carrier_code from raw.carriers order by 1").fetchall() == [("007",), ("DHL",)]
    assert con.execute("select distinct _source_file from raw.carriers").fetchone() == ("carriers.csv",)


def test_missing_column_stops_the_load(con, tmp_path: Path):
    path = tmp_path / "carriers.csv"
    path.write_text("carrier_code\nDHL\n", encoding="utf-8")

    with pytest.raises(SourceFileError, match="carrier_name"):
        load_csv(con, "carriers", path)


def test_empty_file_stops_the_load(con, tmp_path: Path):
    path = tmp_path / "carriers.csv"
    path.write_text("carrier_code,carrier_name\n", encoding="utf-8")

    with pytest.raises(SourceFileError, match="no rows"):
        load_csv(con, "carriers", path)


def test_latest_merchant_export_is_picked(tmp_path: Path):
    for day in ["2026-10-01", "2026-11-14", "2026-09-01"]:
        (tmp_path / f"merchants_{day}.csv").touch()
    (tmp_path / "merchants_backup.csv").touch()  # not a dated export: ignored

    assert pick_merchant_export(tmp_path).name == "merchants_2026-11-14.csv"
    assert pick_merchant_export(tmp_path, as_of=date(2026, 10, 31)).name == "merchants_2026-10-01.csv"
    with pytest.raises(SourceFileError):
        pick_merchant_export(tmp_path, as_of=date(2026, 1, 1))


def test_event_files_are_loaded_only_once(con, tmp_path: Path):
    folder = tmp_path / "tracking_events"
    write_events(folder, "2026-11-01", ["E1", "E2"])

    assert load_new_event_files(con, folder) == ["events_2026-11-01.jsonl"]
    assert load_new_event_files(con, folder) == []  # nothing new: nothing loaded

    write_events(folder, "2026-11-02", ["E3"])
    assert load_new_event_files(con, folder) == ["events_2026-11-02.jsonl"]
    assert con.execute("select count(*) from raw.tracking_events").fetchone() == (3,)
