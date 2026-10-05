"""Download ENTSO-E actual generation per production type for Spain.

This is the "what plants really produced" reference for the redispatch stage
(OMIE's technology report only shows the day-ahead programme). It covers every
production type, from 2020-01-01 to yesterday by default, so a longer study period
needs no new download.

ENTSO-E serves at most one year per request, so the range is fetched one calendar
year per production type. Responses are cached in <DATA_DIR>/raw/; the 2024 files
for the six types fetch_chp_entsoe_year.py also needs are shared with it. A year
that is not over yet is cached under its end date, so a later run fetches ENTSO-E's
newest (possibly revised) data for it instead of reusing the old response.

Usage (token is read from the environment, never from a file):
    $env:ENTSOE_TOKEN = '...'          # PowerShell
    python entsoe_download/fetch_generation_entsoe.py
    python entsoe_download/fetch_generation_entsoe.py --from 2024-01-01 --to 2024-12-31

Writes <DATA_DIR>/generation_entsoe.csv (DATA_DIR: see fetch_entsoe.py): one row
per (date, delivery_time 0-23) in Spanish local time, one MW column per type.
Types ENTSO-E has no Spanish data for are written as 0 and listed at the end; a
day a type is missing is left blank.
"""
import argparse
import csv
import os
import sys
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import DATA_DIR, call, parse, to_24  # noqa: E402

ES = "10YES-REE------0"
TZ = "Europe/Madrid"
OUT_CSV = os.path.join(DATA_DIR, "generation_entsoe.csv")

PSR_TYPES = {
    "fossil_gas_mw":         "B04",
    "biomass_mw":            "B01",
    "waste_mw":              "B17",
    "hydro_pumped_mw":       "B10",
    "hydro_ror_mw":          "B11",
    "hydro_reservoir_mw":    "B12",
    "nuclear_mw":            "B14",
    "hard_coal_mw":          "B05",
    "lignite_mw":            "B02",
    "coal_gas_mw":           "B03",
    "fossil_oil_mw":         "B06",
    "wind_onshore_mw":       "B19",
    "wind_offshore_mw":      "B18",
    "solar_mw":              "B16",
    "other_renewable_mw":    "B15",
    "other_mw":              "B20",
    "energy_storage_mw":     "B25",
}
# full-year 2024 responses already downloaded by fetch_chp_entsoe_year.py
CHP_2024_CACHE = {name: f"chp_year_{name}" for name in list(PSR_TYPES)[:6]}


def utc_stamp(day):
    """Local midnight at the start of `day`, as ENTSO-E's UTC yyyymmddHHMM."""
    return pd.Timestamp(day).tz_localize(TZ).tz_convert("UTC").strftime("%Y%m%d%H%M")


def year_piece(token, name, psr, year, first, last):
    """One request: local days first..last (both inside `year`)."""
    full_year = first == date(year, 1, 1) and last == date(year, 12, 31)
    if full_year and year == 2024 and name in CHP_2024_CACHE:
        cache = CHP_2024_CACHE[name]
    elif full_year and last < date.today() - timedelta(days=60):
        cache = f"gen_{year}_{name}"
    else:  # partial or recent year: key on the dates so newer data is fetched later
        cache = f"gen_{name}_{first:%Y%m%d}_{last:%Y%m%d}"
    xml = call(dict(documentType="A75", processType="A16", in_Domain=ES, psrType=psr,
                    periodStart=utc_stamp(first), periodEnd=utc_stamp(last + timedelta(days=1))),
               token, cache)
    s = parse(xml, skip_consumption=True)
    s.index = s.index.tz_convert(TZ) if s.index.tz else s.index.tz_localize("UTC").tz_convert(TZ)
    return s.resample("h").mean()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="first", default="2020-01-01", help="first day (default 2020-01-01)")
    ap.add_argument("--to", dest="last", default=(date.today() - timedelta(days=1)).isoformat(),
                    help="last day (default yesterday)")
    args = ap.parse_args()
    first, last = date.fromisoformat(args.first), date.fromisoformat(args.last)

    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: $env:ENTSOE_TOKEN = '...'")

    series, empty = {}, []
    for name, psr in PSR_TYPES.items():
        print(f"{name} (psrType {psr}):", end=" ", flush=True)
        pieces = []
        for year in range(first.year, last.year + 1):
            a, b = max(first, date(year, 1, 1)), min(last, date(year, 12, 31))
            try:
                pieces.append(year_piece(token, name, psr, year, a, b))
                print(year, end=" ", flush=True)
            except ValueError:
                print(f"({year}: no data)", end=" ", flush=True)
        print()
        if pieces:
            s = pd.concat(pieces)
            s = s[~s.index.duplicated()]
            series[name] = {day: grp for day, grp in s.groupby(s.index.date)}
        else:
            series[name] = None
            empty.append(name)

    rows, missing_days = [], []
    d = first
    while d <= last:
        day_vals, ok = {}, True
        for name, s in series.items():
            if s is None:
                day_vals[name] = [0.0] * 24
                continue
            day_s = s.get(d)
            if day_s is None:  # this type has no data for this day: leave it blank, not 0
                day_vals[name] = [None] * 24
                continue
            if len(day_s) not in (23, 24, 25):
                ok = False
                break
            day_vals[name] = to_24(day_s)
        if ok:
            for h in range(24):
                row = {"date": d.isoformat(), "delivery_time": h}
                for name in PSR_TYPES:
                    row[name] = day_vals[name][h]
                rows.append(row)
        else:
            missing_days.append(d.isoformat())
        d += timedelta(days=1)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "delivery_time"] + list(PSR_TYPES))
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} hourly rows ({len(rows) // 24} days, {first} to {last}) to {OUT_CSV}")
    if empty:
        print(f"No Spanish data in the whole range (written as 0): {', '.join(empty)}")
    if missing_days:
        print(f"WARNING: {len(missing_days)} days had incomplete data and were skipped:")
        print(" ", missing_days)


if __name__ == "__main__":
    main()
