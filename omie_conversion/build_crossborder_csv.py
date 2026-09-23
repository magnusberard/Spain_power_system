"""
Build Data/crossborder.csv from entsoe_download/crossborder_2024.csv (ENTSO-E
actual physical flows, fetched by fetch_crossborder_year.py) for a date range.

Switches the "Day" column from the old "8_Jul"/"2_Dec" labels to plain ISO
dates ("2024-07-08"), which scales to any number of days without a growing
label dictionary. crossborder.jl and plotting/exports_ramp_2024.py are
updated alongside this to read the new format.

Usage:
    python3 build_crossborder_csv.py --from-date 2024-07-01 --to-date 2024-12-29
"""
import argparse
import csv
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ENTSOE_SRC = os.environ.get("ENTSOE_DIR") or os.path.join(HERE, "..", "..", "entsoe_download")
SRC_CSV = os.path.join(ENTSOE_SRC, "crossborder_2024.csv")
OUT_CSV = os.path.join(HERE, "..", "Data", "crossborder.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    args = ap.parse_args()

    src = {}
    with open(SRC_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            src.setdefault(r["date"], {})[int(r["delivery_time"])] = r

    d = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    rows = []
    missing = []
    while d <= end:
        d_str = d.isoformat()
        if d_str not in src:
            missing.append(d_str)
            d += timedelta(days=1)
            continue
        for h in range(24):
            r = src[d_str][h]
            rows.append({
                "Day": d_str,
                "Time": f"{h:02d}:00 - {(h + 1) % 24:02d}:00",
                "to_PT": r["to_PT"], "from_PT": r["from_PT"],
                "from_FR": r["from_FR"], "to_FR": r["to_FR"],
            })
        d += timedelta(days=1)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Day", "Time", "to_PT", "from_PT", "from_FR", "to_FR"])
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows ({len(rows)//24} days) to {OUT_CSV}")
    if missing:
        print(f"WARNING: {len(missing)} days missing from source, skipped: {missing}")


if __name__ == "__main__":
    main()
