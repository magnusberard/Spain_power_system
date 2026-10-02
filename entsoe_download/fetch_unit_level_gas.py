"""Check whether ENTSO-E's per-generation-unit data (documentType A73, "Actual
Generation per Generation Unit") lets us cross-check the gas_mw discrepancy at
unit level instead of via national-aggregate subtraction.

Note: ENTSO-E's reporting manual only requires unit-level reporting for
generation units above a capacity threshold (traditionally >100MW for most
member states) -- smaller industrial CHP plants are very likely NOT
individually listed here, and would fall back into the national aggregate
(A75) with no unit-level visibility at all. This script's job is just to
confirm that expectation with real data: list whatever units ARE reported for
Spain's Fossil Gas (psrType B04) on the two reference days, and how much of
the national total they cover.

Usage (token read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_unit_level_gas.py
"""
import os
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import call, local_day_bounds  # noqa: E402

ES = "10YES-REE------0"
TZ = "Europe/Madrid"
DAYS = ["2024-07-08", "2024-12-02"]


def utc_window(day):
    s, e = local_day_bounds(day)
    f = lambda t: t.tz_convert("UTC").strftime("%Y%m%d%H%M")
    return f(s), f(e)


def parse_per_unit(xml_bytes):
    """documentType A73 -> {(unit_mrid, unit_name): daily_total_mwh}."""
    root = ET.fromstring(xml_bytes)
    tag = lambda el: el.tag.split("}")[-1]
    if tag(root) == "Acknowledgement_MarketDocument":
        msg = " ".join(t.text or "" for t in root.iter() if tag(t) == "text")
        raise ValueError(msg.strip() or "empty acknowledgement")

    units = {}
    for ts in root.iter():
        if tag(ts) != "TimeSeries":
            continue
        unit_mrid = unit_name = None
        for el in ts.iter():
            if tag(el) == "PowerSystemResources":
                for c in el:
                    if tag(c) == "mRID":
                        unit_mrid = c.text
                    if tag(c) == "name":
                        unit_name = c.text
        key = (unit_mrid or "?", unit_name or "?")

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
            s = pd.Series([pts.get(i + 1) for i in range(n)], index=idx, dtype=float).ffill()
            hours = res.total_seconds() / 3600
            mwh = s.sum() * hours
            units[key] = units.get(key, 0.0) + mwh
    return units


def main():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    for day in DAYS:
        print(f"\n=== {day}: ENTSO-E Actual Generation per Generation Unit, Fossil Gas (B04) ===")
        a, b = utc_window(day)
        try:
            xml = call(dict(documentType="A73", processType="A16", in_Domain=ES, psrType="B04",
                             periodStart=a, periodEnd=b),
                       token, f"unit_level_gas_{day}")
            units = parse_per_unit(xml)
        except ValueError as e:
            print(f"  no data / error: {e}")
            continue

        if not units:
            print("  No unit-level TimeSeries returned.")
            continue

        total_gwh = sum(units.values()) / 1000
        for (mrid, name), mwh in sorted(units.items(), key=lambda kv: -kv[1]):
            print(f"  {name:40s} ({mrid}): {mwh/1000:8.2f} GWh")
        print(f"  --> {len(units)} units reported, summing to {total_gwh:.2f} GWh")


if __name__ == "__main__":
    main()
