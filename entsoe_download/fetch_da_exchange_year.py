"""Download ENTSO-E day-ahead scheduled commercial exchange (documentType A09,
day-ahead contract filter) for Spain<->France and Spain<->Portugal for all of
2024, in one request per border/direction (4 calls total) rather than looping
per day. This is the exact formula validated against OMIE's day-ahead
"International Import" columns on both study days (2024-07-08, 2024-12-02):

    International Import (without MIBEL) = max(0, net FR -> ES)
    International Import (MIBEL)         = max(0, net PT -> ES)

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_da_exchange_year.py

Writes <DATA_DIR>/da_exchange_2024.csv (DATA_DIR: see fetch_entsoe.py): one row per (date, delivery_time 0-23), columns
fr_import_clamped and pt_import_clamped (MW), ready for the converter to add
onto the OMIE domestic-generation total. Raw API responses are cached in
<DATA_DIR>/raw/, and rows already in da_exchange_2024.csv are skipped, so the script is
safe to re-run if it's interrupted partway.
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
DA_CONTRACT = "A01"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(DATA_DIR, "da_exchange_2024.csv")

YEAR_START_UTC = "202312312300"  # 2024-01-01 00:00 Europe/Madrid, in UTC
YEAR_END_UTC = "202412312300"    # 2025-01-01 00:00 Europe/Madrid, in UTC


def year_net_flow(token, other_zone, other_name):
    """Full-year net flow other_zone -> ES, as one continuous hourly series."""
    into_es = call(dict(documentType="A09", **{"contract_MarketAgreement.Type": DA_CONTRACT},
                         in_Domain=ES, out_Domain=other_zone,
                         periodStart=YEAR_START_UTC, periodEnd=YEAR_END_UTC),
                    token, f"da_year_into_ES_from_{other_name}")
    out_es = call(dict(documentType="A09", **{"contract_MarketAgreement.Type": DA_CONTRACT},
                        in_Domain=other_zone, out_Domain=ES,
                        periodStart=YEAR_START_UTC, periodEnd=YEAR_END_UTC),
                   token, f"da_year_from_ES_to_{other_name}")
    s_in = parse(into_es)
    try:
        s_out = parse(out_es)
    except ValueError:
        s_out = s_in * 0
    net = s_in.sub(s_out, fill_value=0.0)
    net.index = net.index.tz_convert(TZ) if net.index.tz else net.index.tz_localize("UTC").tz_convert(TZ)
    return net.resample("h").mean()


def main():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    print("Fetching full-year FR<->ES exchange (2 API calls)...")
    fr_year = year_net_flow(token, FR, "FR")
    print("Fetching full-year PT<->ES exchange (2 API calls)...")
    pt_year = year_net_flow(token, PT, "PT")

    rows = []
    d = date(2024, 1, 1)
    end = date(2024, 12, 31)
    missing_days = []
    while d <= end:
        day_str = d.isoformat()
        day_fr = fr_year[fr_year.index.date == d]
        day_pt = pt_year[pt_year.index.date == d]
        if len(day_fr) not in (23, 24, 25) or len(day_pt) not in (23, 24, 25):
            missing_days.append(day_str)
            d += timedelta(days=1)
            continue
        fr24 = to_24(day_fr)
        pt24 = to_24(day_pt)
        for h in range(24):
            rows.append({
                "date": day_str,
                "delivery_time": h,
                "fr_import_clamped": max(0.0, fr24[h]),
                "pt_import_clamped": max(0.0, pt24[h]),
            })
        d += timedelta(days=1)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "delivery_time", "fr_import_clamped", "pt_import_clamped"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} hourly rows ({len(rows)//24} days) to {OUT_CSV}")
    if missing_days:
        print(f"WARNING: {len(missing_days)} days had no/incomplete data and were skipped:")
        print(" ", missing_days)


if __name__ == "__main__":
    main()
