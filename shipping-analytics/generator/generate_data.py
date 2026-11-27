"""Create made-up data for a shipping platform, in the shapes real sources deliver.

All names and numbers are fictional. A fixed random seed makes every run identical.

Writes to data/raw/:
    carriers.csv                       carrier reference list
    merchants/merchants_<date>.csv     two exports of the merchant list (CRM)
    shipments.csv                      one row per label created (export has duplicates)
    tracking_events/events_<date>.jsonl one file per day, like an API delivers them

Errors are added on purpose, so the dbt tests have something to find:
    - duplicate shipment rows (the export repeats some rows)
    - carrier codes with mixed case and spaces, and one unknown code
    - a few negative weights
    - duplicate tracking events
    - some merchants change plan or country between the two exports

Usage:  python generate_data.py [--out DIR] [--seed N]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE.parent / "data" / "raw"

START = date(2026, 8, 17)  # first day with shipments
END = date(2026, 11, 14)  # last day with data (90 days)
FIRST_EXPORT = date(2026, 10, 1)  # older merchant export
SECOND_EXPORT = END  # newer merchant export
DECLINE_START = date(2026, 10, 1)  # some merchants start sending fewer parcels
CHURN_DATE = date(2026, 10, 10)  # two merchants stop shipping
GLS_PROBLEM_START = date(2026, 10, 24)  # GLS depot problem: many late parcels

CARRIERS = [
    # code, name, transit days (min, max), share of late deliveries
    ("POSTNL", "PostNL", (1, 2), 0.05),
    ("DHL", "DHL Parcel", (1, 3), 0.07),
    ("DPD", "DPD", (1, 3), 0.10),
    ("UPS", "UPS", (1, 4), 0.06),
    ("GLS", "GLS", (2, 4), 0.12),
    ("BPOST", "bpost", (1, 3), 0.09),
]
COUNTRIES = ["NL", "BE", "DE", "FR", "ES", "IT", "AT", "GB"]
PLANS = ["free", "lite", "growth", "premium", "pro"]
SERVICES = ["standard", "express", "mailbox"]
NAME_PARTS = (
    ["Green", "Urban", "Happy", "Nordic", "Tiny", "Bold", "Sunny", "Wild", "Pure", "Little"],
    ["Socks", "Plants", "Coffee", "Books", "Toys", "Bikes", "Candles", "Tea", "Shoes", "Paper"],
    ["Co", "Store", "Shop", "Lab", "House", "Market"],
)


def make_merchants(rng: random.Random, n: int = 200) -> list[dict]:
    merchants = []
    for i in range(1, n + 1):
        name = " ".join(rng.choice(part) for part in NAME_PARTS)
        merchants.append(
            {
                "merchant_id": f"M{i:04d}",
                "merchant_name": name,
                "country": rng.choices(COUNTRIES, weights=[30, 15, 20, 10, 8, 7, 5, 5])[0],
                "plan": rng.choices(PLANS, weights=[35, 25, 20, 15, 5])[0],
                "signup_date": (START - timedelta(days=rng.randint(30, 900))).isoformat(),
                # How many parcels a day this merchant sends, on average
                "_daily_volume": round(rng.lognormvariate(0.2, 1.0), 2),
                # Each merchant mostly uses one carrier
                "_carrier_bias": rng.choice([c[0] for c in CARRIERS]),
                "_trend": "stable",
            }
        )
    # Stories for the health model to find: some merchants slow down, two stop shipping
    busy = [m for m in merchants if m["_daily_volume"] > 3]
    for m in rng.sample(busy, 8):
        m["_trend"] = "declining"
    for m in rng.sample([m for m in busy if m["_trend"] == "stable"], 2):
        m["_trend"] = "churned"
    return merchants


def poisson(rng: random.Random, mean: float) -> int:
    """Random count of events with this average (Knuth's method; fine for small means)."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def volume_factor(trend: str, day: date) -> float:
    """How much of its usual volume a merchant sends on this day."""
    if trend == "declining" and day > DECLINE_START:
        weeks = (day - DECLINE_START).days / 7
        return max(0.35, 1 - 0.1 * weeks)
    if trend == "churned" and day > CHURN_DATE:
        return 0.0
    return 1.0


def late_share_on(carrier: str, usual: float, day: date) -> float:
    """GLS has a bad period at the end: a depot problem makes many parcels late."""
    if carrier == "GLS" and day >= GLS_PROBLEM_START:
        return 0.35
    return usual


def change_some_merchants(rng: random.Random, merchants: list[dict]) -> list[dict]:
    """Return the newer export: some merchants upgraded or moved country."""
    newer = [dict(m) for m in merchants]
    for m in rng.sample(newer, 12):
        current = PLANS.index(m["plan"])
        m["plan"] = PLANS[min(current + 1, len(PLANS) - 1)]
    for m in rng.sample(newer, 3):
        m["country"] = rng.choice([c for c in COUNTRIES if c != m["country"]])
    return newer


def messy_carrier_code(rng: random.Random, code: str) -> str:
    """Source systems are not consistent: lower case, spaces, one legacy code."""
    roll = rng.random()
    if roll < 0.04:
        return code.lower()
    if roll < 0.06:
        return f" {code} "
    if roll < 0.065:
        return "DHLX"  # legacy code nobody mapped
    return code


def make_shipments_and_events(rng: random.Random, merchants: list[dict]) -> tuple[list[dict], list[dict]]:
    carrier_info = {c[0]: c for c in CARRIERS}
    shipments: list[dict] = []
    events: list[dict] = []
    seq = 0
    event_seq = 0

    day = START
    while day <= END:
        weekday_factor = 0.4 if day.weekday() >= 5 else 1.0
        for m in merchants:
            expected = m["_daily_volume"] * weekday_factor * volume_factor(m["_trend"], day)
            count = poisson(rng, expected)
            for _ in range(count):
                seq += 1
                carrier = m["_carrier_bias"] if rng.random() < 0.8 else rng.choice(CARRIERS)[0]
                _, _, (tmin, tmax), usual_late_share = carrier_info[carrier]
                late_share = late_share_on(carrier, usual_late_share, day)
                created_at = datetime.combine(day, datetime.min.time()) + timedelta(
                    minutes=rng.randint(7 * 60, 21 * 60)
                )
                promised = day + timedelta(days=tmax)
                weight = round(rng.uniform(0.1, 15), 2)
                if rng.random() < 0.003:
                    weight = -weight  # typo in the source system

                shipment = {
                    "shipment_id": f"S{seq:07d}",
                    "merchant_id": m["merchant_id"],
                    "carrier_code": messy_carrier_code(rng, carrier),
                    "service_level": rng.choices(SERVICES, weights=[70, 15, 15])[0],
                    "destination_country": rng.choices(COUNTRIES, weights=[35, 15, 20, 10, 6, 6, 4, 4])[0],
                    "weight_kg": weight,
                    "shipping_cost_eur": round(4.5 + abs(weight) * 0.35 + rng.uniform(-0.5, 1.5), 2),
                    "created_at": created_at.isoformat(sep=" "),
                    "promised_delivery_date": promised.isoformat(),
                }
                shipments.append(shipment)
                if rng.random() < 0.01:
                    shipments.append(dict(shipment))  # duplicate row in the export

                # Tracking events for this parcel
                transit = rng.randint(tmin, tmax) + (rng.randint(1, 3) if rng.random() < late_share else 0)
                timeline = [("announced", created_at)]
                pickup = created_at + timedelta(hours=rng.randint(3, 20))
                timeline.append(("in_transit", pickup))
                end_state = rng.choices(["delivered", "returned", "exception"], weights=[95, 3, 2])[0]
                final_ts = datetime.combine(day + timedelta(days=transit), datetime.min.time()) + timedelta(
                    hours=rng.randint(9, 20)
                )
                if end_state == "delivered":
                    timeline.append(("out_for_delivery", final_ts - timedelta(hours=rng.randint(2, 6))))
                timeline.append((end_state, final_ts))

                for status, ts in timeline:
                    if ts.date() > END:
                        break  # not happened yet
                    event_seq += 1
                    event = {
                        "event_id": f"E{event_seq:08d}",
                        "shipment_id": shipment["shipment_id"],
                        "event": {"status": status, "timestamp": ts.isoformat()},
                        "carrier": {"code": carrier},
                    }
                    events.append(event)
                    if rng.random() < 0.005:
                        events.append(json.loads(json.dumps(event)))  # API sent it twice
        day += timedelta(days=1)
    return shipments, events


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [k for k in rows[0] if not k.startswith("_")]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_events_by_day(folder: Path, events: list[dict]) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[dict]] = {}
    for e in events:
        by_day.setdefault(e["event"]["timestamp"][:10], []).append(e)
    for day, rows in by_day.items():
        with (folder / f"events_{day}.jsonl").open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
    return len(by_day)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    merchants = make_merchants(rng)
    newer_merchants = change_some_merchants(rng, merchants)
    shipments, events = make_shipments_and_events(rng, merchants)

    write_csv(args.out / "carriers.csv", [{"carrier_code": c[0], "carrier_name": c[1]} for c in CARRIERS])
    write_csv(args.out / "merchants" / f"merchants_{FIRST_EXPORT}.csv", merchants)
    write_csv(args.out / "merchants" / f"merchants_{SECOND_EXPORT}.csv", newer_merchants)
    write_csv(args.out / "shipments.csv", shipments)
    days = write_events_by_day(args.out / "tracking_events", events)

    print(
        f"Wrote {len(merchants)} merchants, {len(shipments):,} shipment rows, "
        f"{len(events):,} events in {days} daily files to {args.out}"
    )


if __name__ == "__main__":
    main()
