"""Compare the two latest master list snapshots and log what changed.

The master factory list is exported by hand from a master data app. Every export
lands in sample-data/snapshots as master_list_<yyyy-MM-dd-HHmm>.csv. The file name date
is the export date, so the script finds the two latest exports by itself.

Key: FACTORY_ID + VENDOR_ID_ERP (one factory can have several ERP vendor IDs).

Checks
    New factories        FACTORY_ID only in the newer snapshot
    Removed factories    FACTORY_ID only in the older snapshot
    Vendor ID changes    same factory, ERP vendor IDs added or removed
    Moved vendor IDs     a vendor ID that now belongs to another factory

Writes
    output/snapshot_check_<date>.txt    full result
    output/version_log.md               one line per snapshot

Usage:  python snapshot_check.py [--snapshots DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_SNAPSHOTS = HERE.parent / "sample-data" / "snapshots"
PATTERN = re.compile(r"master_list_(\d{4}-\d{2}-\d{2}-\d{4})\.csv$")


@dataclass
class Diff:
    old_label: str
    new_label: str
    rows: int
    factories: int
    new: pd.DataFrame
    removed: pd.DataFrame
    vendor_added: dict[str, list[str]] = field(default_factory=dict)
    vendor_removed: dict[str, list[str]] = field(default_factory=dict)
    moved: list[tuple[str, str, str]] = field(default_factory=list)  # vendor, from, to

    @property
    def identical(self) -> bool:
        return self.new.empty and self.removed.empty and not self.vendor_added and not self.vendor_removed

    def summary(self) -> str:
        if self.identical:
            return "Identical to previous"
        parts = []
        if len(self.new):
            parts.append(f"+{len(self.new)} new: " + ", ".join(f"{r.FACTORY_NAME} ({r.FACTORY_ID})" for r in self.new.itertuples()))
        if len(self.removed):
            parts.append(f"-{len(self.removed)} removed: " + ", ".join(self.removed.FACTORY_ID))
        for v, a, b in self.moved:
            parts.append(f"vendor {v} moved {a} -> {b}")
        n_add = sum(map(len, self.vendor_added.values())) - len(self.moved)
        n_rem = sum(map(len, self.vendor_removed.values())) - len(self.moved)
        if n_add > 0:
            parts.append(f"+{n_add} vendor ID(s)")
        if n_rem > 0:
            parts.append(f"-{n_rem} vendor ID(s)")
        return "; ".join(parts)


def find_snapshots(folder: Path) -> list[tuple[str, Path]]:
    found = [(m.group(1), p) for p in folder.glob("master_list_*.csv") if (m := PATTERN.search(p.name))]
    return sorted(found)


def load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str).fillna("")
    for c in df.columns:
        df[c] = df[c].str.strip()
    return df[df.FACTORY_ID != ""]


def compare(old: pd.DataFrame, new: pd.DataFrame, old_label: str = "old", new_label: str = "new") -> Diff:
    old_ids, new_ids = set(old.FACTORY_ID), set(new.FACTORY_ID)
    names = new.drop_duplicates("FACTORY_ID").set_index("FACTORY_ID").FACTORY_NAME
    old_names = old.drop_duplicates("FACTORY_ID").set_index("FACTORY_ID").FACTORY_NAME

    added_f = sorted(new_ids - old_ids)
    removed_f = sorted(old_ids - new_ids)
    new_df = pd.DataFrame({"FACTORY_ID": added_f, "FACTORY_NAME": [names[i] for i in added_f]})
    rem_df = pd.DataFrame({"FACTORY_ID": removed_f, "FACTORY_NAME": [old_names[i] for i in removed_f]})

    va, vr = {}, {}
    old_v = old.groupby("FACTORY_ID").VENDOR_ID_ERP.apply(set)
    new_v = new.groupby("FACTORY_ID").VENDOR_ID_ERP.apply(set)
    for fid in sorted(old_ids & new_ids):
        a = sorted(new_v[fid] - old_v[fid])
        r = sorted(old_v[fid] - new_v[fid])
        if a:
            va[fid] = a
        if r:
            vr[fid] = r

    owner_old = dict(zip(old.VENDOR_ID_ERP, old.FACTORY_ID))
    owner_new = dict(zip(new.VENDOR_ID_ERP, new.FACTORY_ID))
    moved = sorted((v, owner_old[v], owner_new[v]) for v in owner_old.keys() & owner_new.keys() if owner_old[v] != owner_new[v])

    return Diff(old_label, new_label, len(new), len(new_ids), new_df, rem_df, va, vr, moved)


def report_text(d: Diff) -> str:
    lines = [f"Master list check: {d.new_label} vs {d.old_label}", "",
             f"Rows: {d.rows}   Factories: {d.factories}", ""]
    if d.identical:
        return "\n".join(lines + ["No changes."]) + "\n"
    lines.append(f"New factories ({len(d.new)})")
    lines += [f"  {r.FACTORY_ID}  {r.FACTORY_NAME}" for r in d.new.itertuples()] or ["  none"]
    lines += ["", f"Removed factories ({len(d.removed)})"]
    lines += [f"  {r.FACTORY_ID}  {r.FACTORY_NAME}" for r in d.removed.itertuples()] or ["  none"]
    lines += ["", "Vendor ID changes"]
    for fid in sorted(d.vendor_added.keys() | d.vendor_removed.keys()):
        lines.append(f"  {fid}  added {d.vendor_added.get(fid, [])}  removed {d.vendor_removed.get(fid, [])}")
    if not (d.vendor_added or d.vendor_removed):
        lines.append("  none")
    if d.moved:
        lines += ["", "Moved vendor IDs (check the factory mapping in the dashboard)"]
        lines += [f"  {v}: {a} -> {b}" for v, a, b in d.moved]
    return "\n".join(lines) + "\n"


def append_log(log: Path, d: Diff) -> None:
    if not log.exists():
        log.write_text("# Master list version log\n\n| Snapshot | Rows | Factories | Changes vs previous |\n|---|---|---|---|\n", encoding="utf-8")
    text = log.read_text(encoding="utf-8")
    if f"| {d.new_label} |" in text:
        return  # already logged
    with log.open("a", encoding="utf-8") as f:
        f.write(f"| {d.new_label} | {d.rows} | {d.factories} | {d.summary()} |\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOTS)
    ap.add_argument("--out", type=Path, default=HERE / "output")
    args = ap.parse_args()

    snaps = find_snapshots(args.snapshots)
    if len(snaps) < 2:
        raise SystemExit(f"Need at least two snapshots in {args.snapshots}, found {len(snaps)}.")
    args.out.mkdir(parents=True, exist_ok=True)
    log = args.out / "version_log.md"
    if not log.exists():
        # First run: build the log from the full snapshot history.
        for (ol, op), (nl, np_) in zip(snaps[:-2], snaps[1:-1]):
            append_log(log, compare(load(op), load(np_), ol, nl))

    (old_label, old_path), (new_label, new_path) = snaps[-2], snaps[-1]
    d = compare(load(old_path), load(new_path), old_label, new_label)

    out = args.out / f"snapshot_check_{new_label}.txt"
    out.write_text(report_text(d), encoding="utf-8")
    append_log(args.out / "version_log.md", d)
    print(d.summary())
    print(f"report: {out}")


if __name__ == "__main__":
    main()
