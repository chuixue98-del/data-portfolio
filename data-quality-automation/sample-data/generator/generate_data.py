"""Generate the made-up data for the data quality workflows.

Contoso Foods is fictional: every partner name, ID and number is random.

    raw/partner_database.xlsx      partner list kept by the regions, one sheet per region
    raw/ops_export.xlsx            monthly volume and complaints from an operations platform
    raw/name_mapping.xlsx          production line name -> Factory ID
    snapshots/master_list_*.csv    three exports of the master factory list

Some errors are added on purpose (different headers per region, missing months,
unmapped names, sub-totals above the total, changes between exports), so the
checks in data-quality-automation have something to find.

Usage:  python generate_data.py
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent
START = date(2024, 1, 1)
END = date(2026, 10, 31)  # data is complete up to last month

REGIONS = {
    "Europe": ["Netherlands", "France", "Germany", "Poland", "Spain", "Belgium", "Italy"],
    "North America": ["United States", "Canada"],
    "Latin America": ["Brazil", "Mexico", "Argentina"],
    "Asia Pacific": ["Indonesia", "Australia", "Japan", "Vietnam"],
    "Greater China": ["China"],
    "Middle East & Africa": ["Turkey", "South Africa", "Morocco", "Egypt"],
}
REGION_W = [0.33, 0.15, 0.13, 0.17, 0.08, 0.14]
TYPES = ["Co-manufacturer", "Joint venture", "Licensee"]
TYPE_W = [0.66, 0.14, 0.20]
CATEGORIES = ["Dairy", "Plant-based", "Specialised nutrition", "Beverages"]
SCHEMES = ["FSSC 22000", "BRCGS", "IFS Food", "SQF"]

NAME_A = ["Nord", "Alta", "Riva", "Sol", "Vale", "Bryn", "Kest", "Lumo", "Oro", "Tara", "Mira", "Zen",
          "Hollo", "Fjell", "Cedro", "Iris", "Bora", "Delta", "Pania", "Quin", "Arden", "Velo", "Corvi", "Sela"]
NAME_B = ["vik", "mar", "dal", "ford", "lund", "berg", "haven", "stad", "polis", "wood", "mont", "field"]
NAME_C = ["Dairy", "Foods", "Nutrition", "Beverages", "Processing", "Creamery", "Bottling", "Labs"]
SUFFIX = ["B.V.", "GmbH", "S.A.", "Ltd", "Inc.", "S.p.A.", "Pty Ltd", "LLC"]

MONTHS = pd.period_range(START, END, freq="M")


def logistic(x):
    return 1 / (1 + np.exp(-x))


# ---------------------------------------------------------------- partners
def make_partners(rng, n):
    rows, used = [], set()
    for i in range(n):
        while True:
            name = f"{rng.choice(NAME_A)}{rng.choice(NAME_B)} {rng.choice(NAME_C)}"
            if name not in used:
                used.add(name)
                break
        region = rng.choice(list(REGIONS), p=REGION_W)
        ptype = rng.choice(TYPES, p=TYPE_W)
        q = float(np.clip(rng.normal(0, 1), -2.5, 2.5))
        certified = rng.random() < logistic(1.6 + 0.8 * q)
        rows.append({
            "factory_id": f"F-{10001 + i * 7:05d}",
            "name": name,
            "type": ptype,
            "category": rng.choice(CATEGORIES, p=[0.4, 0.2, 0.25, 0.15]),
            "region": region,
            "country": rng.choice(REGIONS[region]),
            "status": "Active" if rng.random() < 0.92 else "Inactive",
            "scheme": rng.choice(SCHEMES) if certified else None,
            "expiry": (END + timedelta(days=int(rng.integers(-60, 1000)))) if certified else None,
            "q": q,
            # line count drives volume
            "lines": int(rng.choice([1, 1, 1, 2, 2, 3])),
        })
    return pd.DataFrame(rows)


def write_partner_database(p: pd.DataFrame, path: Path, rng):
    """One sheet per region. Regions keep their own headers, as in real life."""
    header_variants = {
        "standard": ["Factory ID", "Partner Name", "Partner Type", "Business Category", "Country", "Status",
                     "Certification Scheme", "Certificate Expiry"],
        "variant": ["Factory Id", "Partner name", "Type", "Business Category", "Country", "Status",
                    "Certification", "Cert. expiry"],
    }
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for k, region in enumerate(REGIONS):
            r = p[p.region == region].copy()
            out = pd.DataFrame({
                0: r.factory_id, 1: r.name, 2: r.type, 3: r.category, 4: r.country,
                5: r.status, 6: r.scheme, 7: r.expiry,
            })
            # planted: trailing spaces in a type, one partner without ID yet
            if len(out) > 3:
                out.iloc[1, 2] = str(out.iloc[1, 2]) + " "
            if region == "Latin America":
                out.loc[len(out) + 10_000] = [None, "Pending Partner (new)", "Co-manufacturer", "Dairy",
                                              "Brazil", "Active", None, None]
            hv = header_variants["variant" if k in (2, 4) else "standard"]
            out.columns = hv
            out.to_excel(xw, sheet_name=region, index=False)


def write_snapshots(p: pd.DataFrame, folder: Path, rng):
    """Master list exports: one row per factory and ERP vendor ID."""
    rows, vid = [], 2_040_000
    for r in p.itertuples():
        for _ in range(int(rng.choice([1, 1, 1, 2, 2, 3]))):
            vid += int(rng.integers(3, 50))
            rows.append({"FACTORY_ID": r.factory_id, "FACTORY_NAME": r.name.upper(), "VENDOR_ID_ERP": str(vid)})
    base = pd.DataFrame(rows)

    # Snapshot 1: two factories not onboarded yet.
    late = p.factory_id.iloc[-2:].tolist()
    s1 = base[~base.FACTORY_ID.isin(late)]
    # Snapshot 2: both new factories appear.
    s2 = base.copy()
    # Snapshot 3: one vendor ID moves to another factory, one is removed,
    # and a factory appears that the regional database does not know yet.
    s3 = base.copy()
    multi = s3.groupby("FACTORY_ID").filter(lambda g: len(g) > 1)
    s3 = s3.drop(index=multi.index[0])
    s3.loc[multi.index[2], "FACTORY_ID"] = p.factory_id.iloc[5]
    s3.loc[multi.index[2], "FACTORY_NAME"] = p.name.iloc[5].upper()
    s3 = pd.concat([s3, pd.DataFrame([{"FACTORY_ID": "F-99901", "FACTORY_NAME": "NEWBRIDGE CO-PACKING", "VENDOR_ID_ERP": "2099001"}])])
    folder.mkdir(parents=True, exist_ok=True)
    for f in folder.glob("master_list_*.csv"):
        f.unlink()
    for d, s in [("2026-10-09-1015", s1), ("2026-10-23-0930", s2), ("2026-11-04-1741", s3)]:
        s.sort_values(["FACTORY_ID", "VENDOR_ID_ERP"]).to_csv(folder / f"master_list_{d}.csv", index=False)


# ---------------------------------------------------------------- volume & complaints
def monthly_volume(rng, p):
    """True monthly volume per partner and line (units). Returned in long form."""
    rows = []
    for r in p.itertuples():
        base = rng.lognormal(mean=14.2, sigma=0.6)  # ~1.5M units a month per line
        for line in range(1, r.lines + 1):
            lb = base * rng.uniform(0.5, 1.2)
            for m in MONTHS:
                season = 1 + 0.12 * np.sin((m.month - 3) / 12 * 2 * np.pi)
                trend = 1 + 0.03 * (m.year - 2024)
                rows.append({"factory_id": r.factory_id, "line": line, "month": m,
                             "units": int(lb * season * trend * rng.uniform(0.85, 1.15))})
    return pd.DataFrame(rows)


def complaint_counts(rng, p, vol):
    """Complaints per partner-month from volume and partner quality."""
    v = vol.groupby(["factory_id", "month"], as_index=False).units.sum()
    q = p.set_index("factory_id").q
    v["rate"] = 4.5e-6 * np.exp(-0.45 * v.factory_id.map(q))  # ~4.5 per million units
    v["complaints"] = rng.poisson(v.units * v.rate)
    v["manufacturing"] = rng.binomial(v.complaints, 0.45)
    v["packaging"] = rng.binomial(v.complaints - v.manufacturing, 0.5)
    return v.drop(columns="rate")



def write_ops_export(rng, p, vol, cc, path):
    """Operations platform answers, per production line and month, long format.

    Covers owned plants (to be filtered out), co-manufacturers and joint ventures,
    except North America. Complaint answers only for joint ventures.
    """
    p_idx = p.set_index("factory_id")
    keep = p[(p.region != "North America") & p.type.isin(["Co-manufacturer", "Joint venture"])].factory_id
    v = vol[vol.factory_id.isin(keep)].copy()
    v["Location"] = v.factory_id.map(p_idx.name) + " - Line " + v.line.astype(str)
    v["Location Type"] = v.factory_id.map(p_idx.type)
    v["YearMonth"] = v.month.dt.year * 100 + v.month.dt.month
    out = [v.assign(Question="Volume (units)", Value=v.units)[["Location", "Location Type", "YearMonth", "Question", "Value"]]]

    jv = p[(p.region != "North America") & (p.type == "Joint venture")]
    c = cc[cc.factory_id.isin(jv.factory_id)].copy()
    c["Location"] = c.factory_id.map(p_idx.name) + " - Line 1"
    c["Location Type"] = "Joint venture"
    c["YearMonth"] = c.month.dt.year * 100 + c.month.dt.month
    for qn, col in [("Complaints - total", "complaints"), ("Complaints - manufacturing", "manufacturing"),
                    ("Complaints - packaging", "packaging")]:
        out.append(c.assign(Question=qn, Value=c[col])[["Location", "Location Type", "YearMonth", "Question", "Value"]])

    # Owned plants are in the same export and must be dropped by the cleaning.
    owned = []
    for i in range(12):
        nm = f"Owned Plant {i + 1:02d} - Line 1"
        for m in MONTHS:
            owned.append({"Location": nm, "Location Type": "Owned", "YearMonth": m.year * 100 + m.month,
                          "Question": "Volume (units)", "Value": int(rng.integers(2e6, 6e6))})
    out.append(pd.DataFrame(owned))
    ops = pd.concat(out, ignore_index=True)

    # planted: missing months (answers not submitted)
    drop = rng.random(len(ops)) < 0.03
    ops = ops[~drop]
    # planted: sub-total larger than total for a few JV months
    tot = ops[ops.Question == "Complaints - total"].sample(4, random_state=1).index
    for i in tot:
        key = ops.loc[i, ["Location", "YearMonth"]]
        m = (ops.Location == key.Location) & (ops.YearMonth == key.YearMonth) & (ops.Question == "Complaints - manufacturing")
        ops.loc[m, "Value"] = ops.loc[i, "Value"] + int(rng.integers(1, 4))
    ops = ops.sample(frac=1, random_state=2).reset_index(drop=True)
    ops.to_excel(path, index=False, sheet_name="Export")
    return ops




def main():
    rng = np.random.default_rng(7)
    raw = DATA / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    p = make_partners(rng, 180)
    write_partner_database(p, raw / "partner_database.xlsx", rng)
    write_snapshots(p, DATA / "snapshots", rng)

    vol = monthly_volume(rng, p)
    cc = complaint_counts(rng, p, vol)
    ops = write_ops_export(rng, p, vol, cc, raw / "ops_export.xlsx")

    # Name mapping for the production lines. Three are left out on purpose.
    names = p.set_index("factory_id").name
    by_name = {n: fid for fid, n in names.items()}
    lines = sorted(set(ops.Location[ops["Location Type"] != "Owned"]))
    mapping = pd.DataFrame({"Source Name": lines, "Factory ID": [by_name[n.rsplit(" - Line", 1)[0]] for n in lines]})
    mapping.drop(index=mapping.sample(3, random_state=4).index).to_excel(raw / "name_mapping.xlsx", index=False, sheet_name="Mapping")
    print(f"partners {len(p)}, ops export rows {len(ops)}")


if __name__ == "__main__":
    main()
