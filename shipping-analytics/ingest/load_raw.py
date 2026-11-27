"""Load raw source files into the warehouse (DuckDB), schema `raw`.

The raw layer keeps the data as the source sent it: every column is text, nothing is
cleaned. Cleaning happens in dbt (staging models). Each table gets two extra columns:
    _source_file   which file the row came from
    _loaded_at     when this script loaded it (dbt uses it for freshness checks)

Tables
    raw.carriers          full reload
    raw.shipments         full reload
    raw.merchants         full reload of one export (the latest, or the one given)
    raw.tracking_events   incremental: only daily files not loaded before
    raw._loaded_files     log of every file loaded

Before loading, each file is checked: it must exist, not be empty and have the
expected columns. If a check fails, nothing is written for that table.

Usage:  python load_raw.py [--raw DIR] [--db FILE] [--merchants-as-of YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DEFAULT_RAW = PROJECT / "data" / "raw"
DEFAULT_DB = PROJECT / "warehouse.duckdb"

REQUIRED_COLUMNS = {
    "carriers": {"carrier_code", "carrier_name"},
    "merchants": {"merchant_id", "merchant_name", "country", "plan", "signup_date"},
    "shipments": {
        "shipment_id",
        "merchant_id",
        "carrier_code",
        "service_level",
        "destination_country",
        "weight_kg",
        "shipping_cost_eur",
        "created_at",
        "promised_delivery_date",
    },
    "tracking_events": {"event_id", "shipment_id", "event", "carrier"},
}
MERCHANT_FILE = re.compile(r"merchants_(\d{4}-\d{2}-\d{2})\.csv$")

log = logging.getLogger("load_raw")


class SourceFileError(Exception):
    """A source file is missing, empty or has the wrong columns."""


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    con.execute("create schema if not exists raw")
    con.execute(
        """
        create table if not exists raw._loaded_files (
            table_name varchar, file_name varchar, row_count bigint, loaded_at timestamp
        )
        """
    )
    return con


def check_columns(con: duckdb.DuckDBPyConnection, relation: str, table: str, path: Path) -> int:
    """Raise SourceFileError if the file has missing columns or no rows. Return the row count."""
    columns = {row[0] for row in con.execute(f"describe select * from {relation}").fetchall()}
    missing = REQUIRED_COLUMNS[table] - columns
    if missing:
        raise SourceFileError(f"{path.name}: missing columns {sorted(missing)}")
    rows = con.execute(f"select count(*) from {relation}").fetchone()[0]
    if rows == 0:
        raise SourceFileError(f"{path.name}: file has no rows")
    return rows


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def load_csv(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> int:
    """Replace raw.<table> with the content of one CSV file (all columns as text)."""
    if not path.exists():
        raise SourceFileError(f"{path} not found")
    relation = f"read_csv('{path.as_posix()}', all_varchar = true, header = true)"
    rows = check_columns(con, relation, table, path)
    loaded_at = _now()
    con.execute(
        f"""
        create or replace table raw.{table} as
        select *, ? as _source_file, ?::timestamp as _loaded_at
        from {relation}
        """,
        [path.name, loaded_at],
    )
    con.execute("insert into raw._loaded_files values (?, ?, ?, ?)", [table, path.name, rows, loaded_at])
    log.info("raw.%s: %s rows from %s", table, f"{rows:,}", path.name)
    return rows


def pick_merchant_export(folder: Path, as_of: date | None = None) -> Path:
    """Return the latest merchant export, or the latest one on or before `as_of`."""
    exports = []
    for path in folder.glob("merchants_*.csv"):
        match = MERCHANT_FILE.search(path.name)
        if match:
            export_date = date.fromisoformat(match.group(1))
            if as_of is None or export_date <= as_of:
                exports.append((export_date, path))
    if not exports:
        raise SourceFileError(f"no merchant export found in {folder}" + (f" on or before {as_of}" if as_of else ""))
    return max(exports)[1]


def load_new_event_files(con: duckdb.DuckDBPyConnection, folder: Path) -> list[str]:
    """Append daily tracking event files that were not loaded before. Return their names."""
    already = {
        row[0]
        for row in con.execute(
            "select file_name from raw._loaded_files where table_name = 'tracking_events'"
        ).fetchall()
    }
    new_files = sorted(p for p in folder.glob("events_*.jsonl") if p.name not in already)
    if not new_files:
        log.info("raw.tracking_events: no new files")
        return []

    table_exists = con.execute(
        "select count(*) from information_schema.tables where table_schema = 'raw' and table_name = 'tracking_events'"
    ).fetchone()[0]

    for path in new_files:
        relation = f"read_json('{path.as_posix()}', format = 'newline_delimited')"
        rows = check_columns(con, relation, "tracking_events", path)
        loaded_at = _now()
        select = f"""
            select event_id, shipment_id, to_json(event) as event, to_json(carrier) as carrier,
                   ? as _source_file, ?::timestamp as _loaded_at
            from {relation}
        """
        if table_exists:
            con.execute(f"insert into raw.tracking_events {select}", [path.name, loaded_at])
        else:
            con.execute(f"create table raw.tracking_events as {select}", [path.name, loaded_at])
            table_exists = True
        con.execute("insert into raw._loaded_files values ('tracking_events', ?, ?, ?)", [path.name, rows, loaded_at])
    log.info(
        "raw.tracking_events: loaded %d new files (%s to %s)", len(new_files), new_files[0].name, new_files[-1].name
    )
    return [p.name for p in new_files]


def run(raw: Path, db: Path, merchants_as_of: date | None = None) -> None:
    con = connect(db)
    try:
        load_csv(con, "carriers", raw / "carriers.csv")
        load_csv(con, "shipments", raw / "shipments.csv")
        load_csv(con, "merchants", pick_merchant_export(raw / "merchants", merchants_as_of))
        load_new_event_files(con, raw / "tracking_events")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--merchants-as-of",
        type=date.fromisoformat,
        default=None,
        help="load the merchant export of this date or earlier (default: latest)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.raw, args.db, args.merchants_as_of)


if __name__ == "__main__":
    main()
