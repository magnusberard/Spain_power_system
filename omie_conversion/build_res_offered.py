"""Build Data/ES_old_offered/{Solar,Wind}: the day-ahead solar and wind
baseline PLUS the solar and wind that was offered in the OMIE day-ahead
auction but not accepted.

Why: Data/ES_old/{Solar,Wind} is OMIE's day-ahead programme (technology
report), i.e. what was accepted. In hours where the market turned solar or
wind away (price about 0), the model never sees that spare energy, so solar
and wind never set the price and the model price cannot reach zero. With
[run].res_input = "offered" the model reads these files instead and can
curtail the spare part itself.

    offered = ES_old (A + B: bilateral contracts + accepted in the auction)
            + C (offered in the auction but not accepted)

C comes from the bid curves per bidding unit (curva_pbc_uof, fetched by
fetch_omie_bid_curves.py): for each Spanish solar or wind unit and hour,
offered MW minus matched MW, never below zero. Units are mapped to a
technology with OMIE_data/unit_technology_map_merged.csv (built by
parse_unit_list.py + build_unit_map.py), using the same technology groups as
convert_omie_to_model_data.py. The bilateral part (A) never appears in the
bid file, which is why C is added to ES_old rather than taken from the bid
file alone: the bid file's matched solar and wind is 13-15 % below the
technology report (May 2024).

--max-bid-price X counts only unaccepted bid steps priced at or below X
EUR/MWh (accepted volume is assigned to a unit's cheapest steps first).
Default: no limit, every unaccepted solar and wind bid counts.

Load and every other input are unchanged. Hours without curtailment get C = 0
and the same value as ES_old.

Usage:
    python3 build_res_offered.py --from-date 2024-05-01 --to-date 2024-05-31
    python3 build_res_offered.py --date 2024-05-05 --dry-run    # print only
"""
import argparse
import csv
import io
import os
import sys
import zipfile
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from convert_omie_to_model_data import (  # noqa: E402
    OMIE_DATA, REPO_DATA, TECH_GROUPS, es_filename, to_24, write_series)

UNIT_MAP_CSV = os.path.join(OMIE_DATA, "unit_technology_map_merged.csv")
BIDS_DIR = os.path.join(OMIE_DATA, "curva_pbc_uof")
ES_OLD_DIR = os.path.join(REPO_DATA, "ES_old")
OUT_DIR = os.path.join(REPO_DATA, "ES_old_offered")

SPAIN = "ZONA ESPAÑOLA"
GROUP = {t: "Wind" for t in TECH_GROUPS["wind"]}
GROUP.update({t: "Solar" for t in TECH_GROUPS["solar_th"] + TECH_GROUPS["solar_pv"]})


def es_number(s):
    s = s.strip()
    return float(s.replace(".", "").replace(",", ".")) if s else 0.0


def load_res_units():
    """Spanish solar/wind unit code -> "Solar" | "Wind"."""
    if not os.path.isfile(UNIT_MAP_CSV):
        sys.exit(f"missing {UNIT_MAP_CSV} (build it with parse_unit_list.py + build_unit_map.py)")
    units = {}
    with open(UNIT_MAP_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = GROUP.get(r["technology"].replace("\n", " "))
            if g and r["zone"] == SPAIN:
                units[r["code"]] = g
    return units


def read_bid_day(d):
    """Lines of curva_pbc_uof_YYYYMMDD.1 from the month's zip, or None."""
    zpath = os.path.join(BIDS_DIR, f"curva_pbc_uof_{d.year}{d.month:02d}.zip")
    if not os.path.isfile(zpath):
        return None
    with zipfile.ZipFile(zpath) as z:
        name = next((n for n in z.namelist()
                     if n.startswith(f"curva_pbc_uof_{d:%Y%m%d}.")), None)
        if name is None:
            return None
        return io.TextIOWrapper(z.open(name), encoding="latin1").read().splitlines()


def spare_mw(lines, units, max_price=None):
    """Unaccepted solar and wind per OMIE hour: {"Solar": {h: MW}, "Wind": {...}}, n_hours."""
    offered = defaultdict(list)      # (unit, hour) -> [(price, MW)]
    matched = defaultdict(float)     # (unit, hour) -> MW
    n_hours = 0
    for line in lines:
        c = line.split(";")
        if len(c) < 8 or not c[0].strip().isdigit():
            continue
        h = int(c[0])
        n_hours = max(n_hours, h)
        if c[4] != "V" or c[3] not in units:
            continue
        if c[7] == "C":
            matched[(c[3], h)] += es_number(c[5])
        elif c[7] == "O":
            offered[(c[3], h)].append((es_number(c[6]), es_number(c[5])))
    out = {"Solar": defaultdict(float), "Wind": defaultdict(float)}
    for (unit, h), steps in offered.items():
        left = matched[(unit, h)]
        spare = 0.0
        for price, mw in sorted(steps):          # matched volume fills the cheapest steps
            take = min(mw, left)
            left -= take
            if max_price is None or price <= max_price:
                spare += mw - take
        out[units[unit]][h] += spare
    return out, n_hours


def read_es_old(resource, d):
    with open(os.path.join(ES_OLD_DIR, resource, es_filename(d)), newline="") as f:
        rows = sorted(csv.DictReader(f), key=lambda r: int(r["delivery_time"]))
    return [float(r["-12"]) for r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--from-date")
    ap.add_argument("--to-date")
    ap.add_argument("--max-bid-price", type=float, default=None,
                    help="count only unaccepted bids at or below this price (EUR/MWh); default: all")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args()
    if args.date:
        days = [date.fromisoformat(args.date)]
    elif args.from_date and args.to_date:
        d0, d1 = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
        days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
    else:
        sys.exit(__doc__)

    units = load_res_units()
    print(f"{len(units)} Spanish solar/wind units in the unit map; "
          f"bid price limit: {'none' if args.max_bid_price is None else args.max_bid_price}")
    print(f"{'day':>10} {'solar +GWh':>10} {'max MW':>7} {'wind +GWh':>10} {'max MW':>7}")
    missing = []
    for d in days:
        lines = read_bid_day(d)
        if lines is None or not os.path.isfile(os.path.join(ES_OLD_DIR, "Solar", es_filename(d))):
            missing.append(d.isoformat())
            continue
        spare, n = spare_mw(lines, units, args.max_bid_price)
        series = {}
        for res in ("Solar", "Wind"):
            c = to_24(spare[res], n)
            series[res] = [round(b + x, 4) for b, x in zip(read_es_old(res, d), c)]
            spare[res] = c
        print(f"{d.isoformat():>10} {sum(spare['Solar']) / 1000:>10.1f} {max(spare['Solar']):>7.0f} "
              f"{sum(spare['Wind']) / 1000:>10.1f} {max(spare['Wind']):>7.0f}")
        if not args.dry_run:
            write_series(series, d, args.out)
    if missing:
        print(f"\nSkipped {len(missing)} day(s) without a bid file or ES_old input: "
              f"{missing[0]} .. {missing[-1]}  (fetch_omie_bid_curves.py)")
    if not args.dry_run:
        print(f"\nWrote {len(days) - len(missing)} day(s) to {args.out}")


if __name__ == "__main__":
    main()
