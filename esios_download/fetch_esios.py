"""Download REE e·sios balancing, redispatch and imbalance series for 2024, per hour.

These are the real counterparts of the model's last stages (find_indicators.py lists more):
balancing energy (aFRR, mFRR, RR) for BAL, technical-constraint and real-time redispatch for the
AC redispatch, and the net imbalance. Volumes are summed per hour and prices averaged, which is
what the model reports. Only the Spanish peninsula is kept when a series is split by region.

Usage (token is read from the environment, never from a file):
    $env:ESIOS_TOKEN = '...'          # PowerShell
    python esios_download/fetch_esios.py                                  # all of 2024
    python esios_download/fetch_esios.py --from 2024-05-01 --to 2024-05-31 --ids 701 702

Raw responses are cached per series and month in <DATA_DIR>/raw/, so a rerun only fetches what
is missing. Writes <DATA_DIR>/hourly/<id>_<key>.csv with columns date, hour (0-23, Spanish local
time; 23 or 25 rows on clock-change days), geo, value. DATA_DIR: see find_indicators.py.
"""
import argparse
import json
import os
import sys
import time
from datetime import date

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ESIOS_DIR") or os.path.join(HERE, "..", "..", "esios_download")
API = "https://api.esios.ree.es"
PENINSULA = "Península"
SPAIN = "España"

# id: (file key, what it is, how hours are aggregated)
INDICATORS = {
    680: ("afrr_up_mwh", "aFRR activated energy, up", "sum"),
    681: ("afrr_down_mwh", "aFRR activated energy, down", "sum"),
    682: ("afrr_up_price", "aFRR energy price, up", "average"),
    683: ("afrr_down_price", "aFRR energy price, down", "average"),
    10395: ("mfrr_up_mwh", "mFRR assigned energy, up", "sum"),
    10394: ("mfrr_down_mwh", "mFRR assigned energy, down", "sum"),
    677: ("mfrr_up_price", "mFRR marginal price, up (scheduled activation)", "average"),
    676: ("mfrr_down_price", "mFRR marginal price, down (scheduled activation)", "average"),
    # 10386/10387 (weighted average mFRR price) only exist from December 2024 on
    10386: ("mfrr_up_price_wavg", "mFRR weighted average price, up (Dec 2024 on)", "average"),
    10387: ("mfrr_down_price_wavg", "mFRR weighted average price, down (Dec 2024 on)", "average"),
    1783: ("rr_up_mwh", "RR assigned energy, up", "sum"),
    1784: ("rr_down_mwh", "RR assigned energy, down", "sum"),
    1782: ("rr_price", "RR energy price", "average"),
    701: ("rt1_up_mwh", "Technical constraints after day-ahead, phase I, up", "sum"),
    702: ("rt1_down_mwh", "Technical constraints after day-ahead, phase I, down", "sum"),
    703: ("rt2_up_mwh", "Technical constraints after day-ahead, phase II, up", "sum"),
    704: ("rt2_down_mwh", "Technical constraints after day-ahead, phase II, down", "sum"),
    720: ("rtr_up_mwh", "Real-time constraints, up", "sum"),
    721: ("rtr_down_mwh", "Real-time constraints, down", "sum"),
    1338: ("imbalance_net_mwh", "Net imbalance volume, generation and demand", "sum"),
}


def headers(token):
    return {"Accept": "application/json; application/vnd.esios-api-v1+json",
            "Content-Type": "application/json", "x-api-key": token}


def months(first, last):
    m = date(first.year, first.month, 1)
    while m <= last:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        yield max(m, first), min(date.fromordinal(nxt.toordinal() - 1), last)
        m = nxt


def fetch(token, ind, agg, a, b, raw_dir):
    """One series for one month, from the cache when it is there."""
    path = os.path.join(raw_dir, f"{ind}_{a:%Y-%m-%d}_{b:%Y-%m-%d}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f), False
    params = dict(start_date=f"{a:%Y-%m-%d}T00:00:00", end_date=f"{b:%Y-%m-%d}T23:59:59",
                  time_trunc="hour", time_agg=agg)
    for attempt in range(5):
        r = requests.get(f"{API}/indicators/{ind}", headers=headers(token), params=params, timeout=120)
        if r.status_code in (401, 403):
            sys.exit(f"e·sios refused the token (HTTP {r.status_code}). Check ESIOS_TOKEN.")
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        values = r.json()["indicator"]["values"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(values, f)
        return values, True
    sys.exit(f"e·sios kept failing for indicator {ind}, {a}..{b}; try again later (cached months are kept).")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="first", default="2024-01-01")
    ap.add_argument("--to", dest="last", default="2024-12-31")
    ap.add_argument("--ids", type=int, nargs="*", help="only these indicator ids (default: all in INDICATORS)")
    args = ap.parse_args()
    first, last = date.fromisoformat(args.first), date.fromisoformat(args.last)
    ids = args.ids or list(INDICATORS)
    unknown = [i for i in ids if i not in INDICATORS]
    if unknown:
        sys.exit(f"Not in INDICATORS (add them there first): {unknown}")
    token = os.environ.get("ESIOS_TOKEN")
    if not token:
        sys.exit("Set ESIOS_TOKEN first: $env:ESIOS_TOKEN = '...'")

    raw_dir, out_dir = os.path.join(DATA_DIR, "raw"), os.path.join(DATA_DIR, "hourly")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    for ind in ids:
        key, label, agg = INDICATORS[ind]
        values, n_new = [], 0
        for a, b in months(first, last):
            v, new = fetch(token, ind, agg, a, b, raw_dir)
            values += v
            n_new += new
            if new:
                time.sleep(0.3)
        df = pd.DataFrame(values)
        if df.empty:
            print(f"{ind:>6} {key:<18} no data")
            continue
        # keep the peninsula when the series is split by region, Spain when it is split by country
        # (the European RR market gives one price per country); otherwise the one series there is
        geos = sorted(df.geo_name.unique())
        for keep in (PENINSULA, SPAIN):
            if keep in geos:
                df = df[df.geo_name == keep]
                break
        local = pd.to_datetime(df.datetime_utc, utc=True).dt.tz_convert("Europe/Madrid")
        out = pd.DataFrame({"date": local.dt.strftime("%Y-%m-%d"), "hour": local.dt.hour,
                            "geo": df.geo_name.values, "value": df.value.values})
        out = out.sort_values(["date", "hour"])
        if out.duplicated(["date", "hour", "geo"]).any():
            print(f"  warning: {key} has more than one value in some hours")
        out.to_csv(os.path.join(out_dir, f"{ind}_{key}.csv"), index=False, encoding="utf-8")
        print(f"{ind:>6} {key:<18} {out.date.nunique():>3} days, {len(out):>5} hours, "
              f"geo {', '.join(geos)}; {n_new} months downloaded  ({label})")

    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(DATA_DIR) for f in fs)
    print(f"\n{DATA_DIR}: {size / 1e6:.1f} MB in total")


if __name__ == "__main__":
    main()
