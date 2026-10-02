"""Download ENTSO-E actuals for Spain and build candidate Data/ES_old files.

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_entsoe.py 2024-07-08 2024-12-02        # actual (measured) values
    python3 fetch_entsoe.py --forecast 2024-07-08 2024-12-02   # day-ahead forecasts
    python3 fetch_entsoe.py --range 2024-07-02 2024-07-31 # a date range

Output goes to <DATA_DIR>/out/ES_old_candidate_<actual|fc>/<load|Wind|Solar>/<d>_<m>_<yyyy>.csv
in the model's format (delivery_time 0-23, column "-12", MW, Spanish local time).
Raw responses are cached in <DATA_DIR>/raw/ so a rerun does not hit the API again.
If the repo's existing Data/ES_old file for a day exists, the difference is printed.

DATA_DIR is $ENTSOE_DIR, else the entsoe_download/ folder NEXT TO the repo
(../../entsoe_download from here) -- the same place omie_conversion/ reads from.
Downloads and caches are kept out of the repo; only these scripts are tracked.
"""
import os
import sys
import time
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import pandas as pd

API = "https://web-api.tp.entsoe.eu/api"
ES = "10YES-REE------0"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ENTSOE_DIR") or os.path.join(HERE, "..", "..", "entsoe_download")
RAW = os.path.join(DATA_DIR, "raw")
OUT_BASE = os.path.join(DATA_DIR, "out")
REPO_ES_OLD = os.path.join(HERE, "..", "Data", "ES_old")
TZ = "Europe/Madrid"

MODE = "actual"          # "actual" (processType A16) or "fc" (day-ahead forecast, A01)


def make_queries(process):
    # kind -> list of API queries whose series are summed
    return {
        "load": [dict(documentType="A65", processType=process, outBiddingZone_Domain=ES)],
        "Wind": [dict(documentType=DOC_GEN, processType=process, in_Domain=ES, psrType="B19"),
                 dict(documentType=DOC_GEN, processType=process, in_Domain=ES, psrType="B18")],
        "Solar": [dict(documentType=DOC_GEN, processType=process, in_Domain=ES, psrType="B16")],
    }


DOC_GEN = "A75"
QUERIES = make_queries("A16")


def local_day_bounds(day):
    """Local midnight to next local midnight (23/25 h on daylight-saving days)."""
    d = date.fromisoformat(day)
    return pd.Timestamp(d, tz=TZ), pd.Timestamp(d + timedelta(days=1), tz=TZ)


def utc_window(day):
    """Local calendar day -> (start, end) as UTC strings for the API."""
    s, e = local_day_bounds(day)
    f = lambda t: t.tz_convert("UTC").strftime("%Y%m%d%H%M")
    return f(s), f(e)


def call(params, token, cache_name):
    path = os.path.join(RAW, cache_name + ".xml")
    if os.path.exists(path):
        return open(path, "rb").read()
    q = dict(params, securityToken=token)
    url = API + "?" + urllib.parse.urlencode(q)
    body = b""
    for attempt in range(3):
        # curl uses the macOS certificate store; the URL (with the token) goes via
        # stdin so it never appears in the process list
        r = subprocess.run(["curl", "-sS", "-m", "90", "-w", "\n%{http_code}", "--config", "-"],
                           input=f'url = "{url}"\n'.encode(), capture_output=True)
        if r.returncode != 0:
            if attempt == 2:
                sys.exit("curl failed: " + r.stderr.decode(errors="replace").strip())
            time.sleep(5)
            continue
        body, _, code = r.stdout.rpartition(b"\n")
        code = int(code or 0)
        if code == 401:
            sys.exit("HTTP 401: token rejected. Check ENTSOE_TOKEN.")
        if code == 429 and attempt < 2:
            time.sleep(20)
            continue
        break
    os.makedirs(RAW, exist_ok=True)
    open(path, "wb").write(body)
    time.sleep(0.3)
    return body


def parse(xml_bytes, skip_consumption=False):
    """XML -> hourly-agnostic UTC Series (MW). ENTSO-E omits points that repeat the
    previous value, so gaps inside a period are forward-filled."""
    root = ET.fromstring(xml_bytes)
    tag = lambda el: el.tag.split("}")[-1]
    if tag(root) == "Acknowledgement_MarketDocument":
        msg = " ".join(t.text or "" for t in root.iter() if tag(t) == "text")
        raise ValueError(msg.strip() or "empty acknowledgement")
    total = None
    for ts in root.iter():
        if tag(ts) != "TimeSeries":
            continue
        # generation queries also return consumption series (pumping); skip those
        if skip_consumption and any(tag(c) == "outBiddingZone_Domain.mRID" for c in ts):
            continue
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
            n = int((end - start) / res)
            idx = pd.date_range(start, periods=n, freq=res)
            s = pd.Series([pts.get(i + 1) for i in range(n)], index=idx, dtype=float).ffill()
            pieces.append(s)
        if pieces:
            s = pd.concat(pieces)
            total = s if total is None else total.add(s, fill_value=0.0)
    if total is None:
        raise ValueError("no TimeSeries in response")
    return total


def day_series(kind, day, token):
    a, b = utc_window(day)
    total = None
    for i, q in enumerate(QUERIES[kind]):
        params = dict(q, periodStart=a, periodEnd=b)
        name = f"{MODE}_{kind}_{i}_{day}"
        try:
            s = parse(call(params, token, name), skip_consumption=(kind != "load"))
        except ValueError as e:
            print(f"  {kind} query {i}: no data ({e})")
            continue
        total = s if total is None else total.add(s, fill_value=0.0)
    if total is None:
        return None
    total.index = total.index.tz_convert(TZ) if total.index.tz else total.index.tz_localize("UTC").tz_convert(TZ)
    hourly = total.resample("h").mean()
    lo, hi = local_day_bounds(day)
    hourly = hourly[(hourly.index >= lo) & (hourly.index < hi)]
    return hourly


def to_24(hourly):
    """DST days have 23/25 hours; the model expects exactly 24 local rows."""
    v = hourly.values
    if len(v) == 24:
        return v
    if len(v) == 23:            # spring forward: repeat the last hour
        return list(v) + [v[-1]]
    if len(v) == 25:            # autumn back: drop the repeated hour
        return list(v[:2]) + list(v[3:])
    raise ValueError(f"unexpected {len(v)} hourly values")


def fname(day):
    d = date.fromisoformat(day)
    return f"{d.day}_{d.month}_{d.year}.csv"


def main():
    global MODE, DOC_GEN, QUERIES
    args = sys.argv[1:]
    if args and args[0] == "--forecast":
        MODE, DOC_GEN = "fc", "A69"          # day-ahead wind/solar forecast, day-ahead load forecast
        QUERIES = make_queries("A01")
        args = args[1:]
    if not args:
        sys.exit(__doc__)
    OUT = os.path.join(OUT_BASE, "ES_old_candidate_" + MODE)
    if args[0] == "--range":
        d0, d1 = date.fromisoformat(args[1]), date.fromisoformat(args[2])
        days = [(d0 + timedelta(i)).isoformat() for i in range((d1 - d0).days + 1)]
    else:
        days = args
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    for day in days:
        print(day)
        for kind in QUERIES:
            hourly = day_series(kind, day, token)
            if hourly is None:
                print(f"  {kind}: nothing downloaded")
                continue
            vals = to_24(hourly)
            outdir = os.path.join(OUT, kind)
            os.makedirs(outdir, exist_ok=True)
            pd.DataFrame({"delivery_time": range(24), "-12": vals}).to_csv(
                os.path.join(outdir, fname(day)), index=False)
            ref = os.path.join(REPO_ES_OLD, kind, fname(day))
            if os.path.exists(ref):
                old = pd.read_csv(ref).sort_values("delivery_time")["-12"].values[:24]
                d = abs(pd.Series(vals[:24]).values - old)
                print(f"  {kind:5s} vs repo ES_old: max diff {d.max():8.1f} MW, mean {d.mean():8.1f} MW")
            else:
                print(f"  {kind:5s} written (no repo file to compare)")


if __name__ == "__main__":
    main()
