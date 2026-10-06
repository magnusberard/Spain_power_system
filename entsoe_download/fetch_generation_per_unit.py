"""Download ENTSO-E actual generation per generation unit (documentType A73) for Spain.

ENTSO-E publishes measured hourly output for each large unit (roughly 100 MW and up:
nuclear, coal, combined cycles, large hydro, some wind and solar parks). This is the real
reference for the plant map's output; smaller units are only in the per-type totals
(fetch_generation_entsoe.py). ENTSO-E serves this report one day per request, so the
script makes one request per day (all production types at once). Responses are cached
in <DATA_DIR>/raw/, so a rerun only fetches days it does not have.

Usage (token is read from the environment, never from a file):
    $env:ENTSOE_TOKEN = '...'          # PowerShell
    python entsoe_download/fetch_generation_per_unit.py                       # January 2024
    python entsoe_download/fetch_generation_per_unit.py --from 2024-01-01 --to 2024-12-31

Writes one file per month, <DATA_DIR>/generation_per_unit/<yyyy-mm>.csv (DATA_DIR: see
fetch_entsoe.py), so a whole year never sits in memory. Long format: date, delivery_time
(0-23, Spanish local time), unit_eic, unit_name, psr_type, mw. Days already in a month's
file are replaced, other days are kept.
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import DATA_DIR, call, local_day_bounds, to_24  # noqa: E402

ES = "10YES-REE------0"
TZ = "Europe/Madrid"
OUT_DIR = os.path.join(DATA_DIR, "generation_per_unit")
COLS = ["date", "delivery_time", "unit_eic", "unit_name", "psr_type", "mw"]


def utc_window(day):
    s, e = local_day_bounds(day)
    f = lambda t: t.tz_convert("UTC").strftime("%Y%m%d%H%M")
    return f(s), f(e)


def parse_units(xml_bytes):
    """A73 response -> list of (unit_eic, unit_name, psr_type, hourly Series in UTC)."""
    root = ET.fromstring(xml_bytes)
    tag = lambda el: el.tag.split("}")[-1]
    if tag(root) == "Acknowledgement_MarketDocument":
        msg = " ".join(t.text or "" for t in root.iter() if tag(t) == "text")
        raise ValueError(msg.strip() or "empty acknowledgement")
    out = []
    for ts in root.iter():
        if tag(ts) != "TimeSeries":
            continue
        # generation units only; pumping consumption comes as an outBiddingZone series
        if any(tag(c) == "outBiddingZone_Domain.mRID" for c in ts):
            continue
        eic = name = psr = None
        for el in ts.iter():
            if tag(el) == "psrType":
                psr = el.text
            if tag(el) == "PowerSystemResources":
                for c in el:
                    if tag(c) == "mRID":
                        eic = c.text
                    if tag(c) == "name":
                        name = c.text
        pieces = []
        for per in (p for p in ts if tag(p) == "Period"):
            start = end = res = None
            pts = {}
            for el in per:
                if tag(el) == "timeInterval":
                    for c in el:
                        if tag(c) == "start":
                            start = pd.Timestamp(c.text)
                        if tag(c) == "end":
                            end = pd.Timestamp(c.text)
                elif tag(el) == "resolution":
                    res = pd.Timedelta(pd.tseries.frequencies.to_offset(
                        {"PT15M": "15min", "PT30M": "30min", "PT60M": "60min"}[el.text]))
                elif tag(el) == "Point":
                    pos = int([c for c in el if tag(c) == "position"][0].text)
                    qty = float([c for c in el if tag(c) == "quantity"][0].text)
                    pts[pos] = qty
            if start is None or res is None:
                continue
            n = int((end - start) / res)
            idx = pd.date_range(start, periods=n, freq=res)
            pieces.append(pd.Series([pts.get(i + 1) for i in range(n)], index=idx, dtype=float).ffill())
        if pieces:
            s = pd.concat(pieces).sort_index()
            out.append((eic or "?", name or "?", psr or "?", s.resample("h").mean()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="first", default="2024-01-01")
    ap.add_argument("--to", dest="last", default="2024-01-31")
    args = ap.parse_args()
    first, last = date.fromisoformat(args.first), date.fromisoformat(args.last)

    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: $env:ENTSOE_TOKEN = '...'")

    os.makedirs(OUT_DIR, exist_ok=True)
    rows, failed, written = [], [], []

    def flush(month):
        """Write the collected days of one month into its file, replacing those days."""
        if not rows:
            return
        new = pd.DataFrame(rows, columns=COLS)
        path = os.path.join(OUT_DIR, f"{month}.csv")
        if os.path.exists(path):
            old = pd.read_csv(path)
            new = pd.concat([old[~old.date.isin(new.date.unique())], new])
        new.sort_values(["date", "delivery_time", "unit_eic"]).to_csv(path, index=False)
        written.append(f"{month}: {new.date.nunique()} days, {new.unit_eic.nunique()} units, "
                       + ", ".join(f"{k} {v}" for k, v in new.groupby("psr_type").unit_eic.nunique().items()))
        rows.clear()

    d = first
    while d <= last:
        day = d.isoformat()
        if rows and rows[-1][0][:7] != day[:7]:
            flush(rows[-1][0][:7])
        a, b = utc_window(day)
        try:
            xml = call(dict(documentType="A73", processType="A16", in_Domain=ES, periodStart=a, periodEnd=b),
                       token, f"unit_gen_{day}")
            units = parse_units(xml)
        except (ValueError, ET.ParseError) as e:
            print(f"{day}: no data ({e})")
            failed.append(day)
            d += timedelta(days=1)
            continue
        lo, hi = local_day_bounds(day)
        n_ok = 0
        for eic, name, psr, s in units:
            s = s.tz_convert(TZ)
            s = s[(s.index >= lo) & (s.index < hi)]
            if len(s) not in (23, 24, 25):
                continue
            for h, mw in enumerate(to_24(s)):
                rows.append((day, h, eic, name, psr, None if pd.isna(mw) else round(float(mw), 1)))
            n_ok += 1
        print(f"{day}: {n_ok} units")
        d += timedelta(days=1)
    if rows:
        flush(rows[-1][0][:7])

    print(f"\nWrote to {OUT_DIR}:")
    for w in written:
        print("  " + w)
    if failed:
        print(f"No data for {len(failed)} days: {failed}")


if __name__ == "__main__":
    main()
