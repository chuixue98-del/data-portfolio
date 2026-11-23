"""Manual backup of the Office Script: same checks, same workbook, run locally.

Use it when the flow is down, or to test rule changes before editing the Office Script.
Reads the newest query export in history/ (dq_raw_<timestamp>.csv, the file the
flow saves) or a file given with --csv.

Usage:  python generate_dq_output.py [--csv FILE] [--out output/dq_nc_quantity.xlsx]
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Power BI returns 'Table[Column]' or '[Column]' headers. Keep the column name."""
    return df.rename(columns=lambda c: str(c).split("[")[-1].rstrip("]"))


def is_blank(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype(str).str.strip() == "")


def check(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    rows = clean_columns(rows)
    missing = rows[is_blank(rows["Quantity Impacted"])]
    wrong = rows[~is_blank(rows["Quantity Impacted"]) & (rows["UoM"].fillna("").astype(str).str.strip() != "CU")]
    return {"Missing quantity": missing, "Wrong unit": wrong, "Raw Data": rows}


def write(result: dict[str, pd.DataFrame], out: Path) -> None:
    info = pd.DataFrame([
        ("Last run", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Rows checked", len(result["Raw Data"])),
        ("Missing quantity", len(result["Missing quantity"])),
        ("Wrong unit", len(result["Wrong unit"])),
    ], columns=["Item", "Value"])
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for name, df in result.items():
            df.to_excel(xw, sheet_name=name, index=False)
        info.to_excel(xw, sheet_name="Update Info", index=False)
        xw.book["Raw Data"].sheet_state = "hidden"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--out", type=Path, default=HERE / "output" / "dq_nc_quantity.xlsx")
    args = ap.parse_args()

    src = args.csv or max((HERE / "history").glob("dq_raw_*.csv"), default=None)
    if src is None:
        raise SystemExit("No query export found in history/. Pass one with --csv.")
    rows = pd.read_csv(src)
    if rows.empty:
        raise SystemExit("Query returned no rows. Workbook not changed.")
    result = check(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write(result, args.out)
    print(f"{src.name}: {len(rows)} rows, {len(result['Missing quantity'])} missing quantity, {len(result['Wrong unit'])} wrong unit")


if __name__ == "__main__":
    main()
