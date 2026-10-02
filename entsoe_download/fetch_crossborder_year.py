"""Download ENTSO-E ACTUAL (realized, metered) physical cross-border flows for
Spain<->France and Spain<->Portugal for all of 2024, in one request per
border/direction (4 calls total), matching Data/crossborder.csv's schema
(gross to_PT/from_PT/from_FR/to_FR, not netted) so the output can extend that
file directly for new study days.

This is documentType A11 (always real-time metered -- there is no day-ahead
version), the correct source for crossborder.csv per its own docstring
("the market-cleared cross-border schedule") and per docs/method note that
the original 2 study days' crossborder.csv values are real settled flows,
confirmed against these same ENTSO-E actual physical flows during this
session (hour 0, 8 Jul: 1623.5 MW modelled vs 1623 MW ENTSO-E actual).

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_crossborder_year.py

Writes <DATA_DIR>/crossborder_2024.csv (DATA_DIR: see fetch_entsoe.py): one row per (date, delivery_time 0-23), columns
to_PT, from_PT, from_FR, to_FR (MW) -- the exact 4 columns crossborder.csv
uses.
"""
import csv
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import DATA_DIR, call, parse, to_24  # noqa: E402

ES = "10YES-REE------0"
FR = "10YFR-RTE------C"
PT = "10YPT-REN------W"
TZ = "Europe/Madrid"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(DATA_DIR, "crossborder_2024.csv")

YEAR_START_UTC = "202312312300"
YEAR_END_UTC = "202412312300"


def year_flow(token, in_zone, out_zone, name):
    """Full-year hourly flow out_zone -> in_zone, MW."""
    xml = call(dict(documentType="A11", in_Domain=in_zone, out_Domain=out_zone,
                     periodStart=YEAR_START_UTC, periodEnd=YEAR_END_UTC),
               token, f"xb_year_{name}")
    s = parse(xml)
    s.index = s.index.tz_convert(TZ) if s.index.tz else s.index.tz_localize("UTC").tz_convert(TZ)
    return s.resample("h").mean()


def main():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    print("Fetching FR->ES (import)...")
    from_fr = year_flow(token, ES, FR, "from_FR")
    print("Fetching ES->FR (export)...")
    to_fr = year_flow(token, FR, ES, "to_FR")
    print("Fetching PT->ES (import)...")
    from_pt = year_flow(token, ES, PT, "from_PT")
    print("Fetching ES->PT (export)...")
    to_pt = year_flow(token, PT, ES, "to_PT")

    series = {"from_FR": from_fr, "to_FR": to_fr, "from_PT": from_pt, "to_PT": to_pt}

    rows = []
    d = date(2024, 1, 1)
    end = date(2024, 12, 31)
    missing_days = []
    while d <= end:
        day_str = d.isoformat()
        day_vals = {}
        ok = True
        for name, s in series.items():
            day_s = s[s.index.date == d]
            if len(day_s) not in (23, 24, 25):
                ok = False
                break
            day_vals[name] = to_24(day_s)
        if not ok:
            missing_days.append(day_str)
            d += timedelta(days=1)
            continue
        for h in range(24):
            rows.append({
                "date": day_str, "delivery_time": h,
                "to_PT": day_vals["to_PT"][h], "from_PT": day_vals["from_PT"][h],
                "from_FR": day_vals["from_FR"][h], "to_FR": day_vals["to_FR"][h],
            })
        d += timedelta(days=1)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "delivery_time", "to_PT", "from_PT", "from_FR", "to_FR"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} hourly rows ({len(rows)//24} days) to {OUT_CSV}")
    if missing_days:
        print(f"WARNING: {len(missing_days)} days had no/incomplete data and were skipped:")
        print(" ", missing_days)


if __name__ == "__main__":
    main()
