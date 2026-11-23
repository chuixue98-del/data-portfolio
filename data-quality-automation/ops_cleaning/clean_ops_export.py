"""Clean the operations platform export for the dashboard and check its quality.

Input   sample-data/raw/ops_export.xlsx        long format: Location (production line),
                                        Location Type, YearMonth, Question, Value
        sample-data/raw/name_mapping.xlsx      Source Name -> Factory ID
        sample-data/raw/partner_database.xlsx  who is expected to report (one sheet per region)

Output  sample-data/clean/ops_volume.csv       Factory ID x month, units
        sample-data/clean/ops_complaints.csv   Factory ID x month, total / manufacturing / packaging
        output/ops_dq_report.xlsx       Summary, Missing reports, Unmapped names, Consistency

Rules
    * Owned plants are in the same export; only partner types are kept.
    * Lines are mapped to a Factory ID by name and summed per factory.
    * Every expected factory gets a row for every month up to the last month,
      blank if nothing was reported, so missing reports stay visible in Power BI.
    * A complaint sub-total may never exceed the total.

Usage:  python clean_ops_export.py [--until 2026-10]
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "sample-data"

KEEP_TYPES = {"Co-manufacturer", "Joint venture"}
VOLUME_Q = "Volume (units)"
CC_Q = {"Complaints - total": "complaints_total",
        "Complaints - manufacturing": "complaints_manufacturing",
        "Complaints - packaging": "complaints_packaging"}

# Regional sheets use different headers for the same thing.
HEADER_MAP = {
    "factory id": "factory_id", "partner name": "partner_name", "partner type": "partner_type", "type": "partner_type",
    "business category": "business_category", "country": "country", "status": "status",
    "certification scheme": "certification_scheme", "certification": "certification_scheme",
    "certificate expiry": "certificate_expiry", "cert. expiry": "certificate_expiry",
}


def read_partner_database(path: Path) -> pd.DataFrame:
    frames = []
    for region, df in pd.read_excel(path, sheet_name=None).items():
        df = df.rename(columns=lambda c: HEADER_MAP.get(str(c).strip().lower(), c))
        df["region"] = region
        frames.append(df)
    db = pd.concat(frames, ignore_index=True)
    for c in ["factory_id", "partner_type", "status", "partner_name"]:
        db[c] = db[c].astype("string").str.strip()
    return db[db.factory_id.notna()]


def expected_entities(db: pd.DataFrame) -> tuple[set, set]:
    """Who should report volume and complaints through the operations platform."""
    act = db[(db.status == "Active") & (db.region != "North America")]
    vol = set(act.factory_id[act.partner_type.isin(KEEP_TYPES)])
    cc = set(act.factory_id[act.partner_type == "Joint venture"])
    return vol, cc


def months_until(start: pd.Period, end: pd.Period) -> list[pd.Period]:
    return list(pd.period_range(start, end, freq="M"))


def clean(ops: pd.DataFrame, mapping: pd.DataFrame, exp_vol: set, exp_cc: set, until: pd.Period | None = None):
    issues = {}
    ops = ops.copy()
    ops["Location"] = ops["Location"].astype(str).str.strip()
    ops = ops[ops["Location Type"].isin(KEEP_TYPES)]
    ops["month"] = pd.PeriodIndex([pd.Period(year=v // 100, month=v % 100, freq="M") for v in ops["YearMonth"]])
    until = until or ops["month"].max()
    ops = ops[ops["month"] <= until]
    months = months_until(ops["month"].min(), until) if len(ops) else []

    m = dict(zip(mapping["Source Name"].astype(str).str.strip(), mapping["Factory ID"].astype(str).str.strip()))
    ops["factory_id"] = ops["Location"].map(m)
    unm = ops[ops.factory_id.isna()]
    issues["Unmapped names"] = (unm.groupby(["Location", "Location Type"], as_index=False)
                                .agg(rows=("Value", "size"), first_month=("month", "min"), last_month=("month", "max")))
    ops = ops[ops.factory_id.notna()]

    # Volume: sum lines per factory-month, then pad to every expected factory x month.
    v = ops[ops.Question == VOLUME_Q].groupby(["factory_id", "month"], as_index=False)["Value"].sum()
    grid = pd.MultiIndex.from_product([sorted(exp_vol), months], names=["factory_id", "month"]).to_frame(index=False)
    vol = grid.merge(v, how="left", on=["factory_id", "month"]).rename(columns={"Value": "units"})

    # Complaints: one column per question.
    c = ops[ops.Question.isin(CC_Q)].pivot_table(index=["factory_id", "month"], columns="Question", values="Value", aggfunc="sum").rename(columns=CC_Q).reset_index()
    grid_cc = pd.MultiIndex.from_product([sorted(exp_cc), months], names=["factory_id", "month"]).to_frame(index=False)
    cc = grid_cc.merge(c, how="left", on=["factory_id", "month"])
    for col in CC_Q.values():
        if col not in cc:
            cc[col] = pd.NA
    cc = cc[["factory_id", "month", *CC_Q.values()]]

    # Consistency: sub-total > total.
    bad = cc[(cc.complaints_manufacturing > cc.complaints_total) | (cc.complaints_packaging > cc.complaints_total)]
    issues["Consistency"] = bad.assign(rule="sub-total larger than total")

    miss_v = vol[vol.units.isna()].assign(dataset="Volume")[["factory_id", "month", "dataset"]]
    miss_c = cc[cc.complaints_total.isna()].assign(dataset="Complaints")[["factory_id", "month", "dataset"]]
    issues["Missing reports"] = pd.concat([miss_v, miss_c], ignore_index=True)
    return vol, cc, issues


def to_csv(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    out["month"] = out["month"].dt.to_timestamp().dt.strftime("%Y-%m-%d")
    for c in out.columns.drop(["factory_id", "month"]):
        out[c] = out[c].astype("Int64")
    out.to_csv(path, index=False)


def write_dq(issues: dict, vol: pd.DataFrame, cc: pd.DataFrame, path: Path, names: pd.Series) -> None:
    summary = pd.DataFrame([
        ("Run at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Factory-months, volume", len(vol)),
        ("  reported", int(vol.units.notna().sum())),
        ("  missing", int(vol.units.isna().sum())),
        ("Factory-months, complaints", len(cc)),
        ("  missing", int(cc.complaints_total.isna().sum())),
        ("Unmapped location names", len(issues["Unmapped names"])),
        ("Consistency issues", len(issues["Consistency"])),
    ], columns=["Check", "Value"])
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        for name, df in issues.items():
            df = df.copy()
            if "factory_id" in df:
                df.insert(1, "partner_name", df.factory_id.map(names))
            for c in df.columns:
                if isinstance(df[c].dtype, pd.PeriodDtype):
                    df[c] = df[c].astype(str)
            df.to_excel(xw, sheet_name=name, index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--until", help="last month to track, YYYY-MM (default: last month in the export)")
    args = ap.parse_args()

    ops = pd.read_excel(DATA / "raw" / "ops_export.xlsx")
    mapping = pd.read_excel(DATA / "raw" / "name_mapping.xlsx")
    db = read_partner_database(DATA / "raw" / "partner_database.xlsx")
    exp_vol, exp_cc = expected_entities(db)

    until = pd.Period(args.until, freq="M") if args.until else None
    vol, cc, issues = clean(ops, mapping, exp_vol, exp_cc, until)

    (DATA / "clean").mkdir(exist_ok=True)
    to_csv(vol, DATA / "clean" / "ops_volume.csv")
    to_csv(cc, DATA / "clean" / "ops_complaints.csv")
    (HERE / "output").mkdir(exist_ok=True)
    write_dq(issues, vol, cc, HERE / "output" / "ops_dq_report.xlsx", db.set_index("factory_id").partner_name)

    print(f"volume rows {len(vol)} (missing {vol.units.isna().sum()}), complaint rows {len(cc)} (missing {cc.complaints_total.isna().sum()})")
    print(f"unmapped names {len(issues['Unmapped names'])}, consistency issues {len(issues['Consistency'])}")


if __name__ == "__main__":
    main()
