"""Download ENTSO-E actual generation-by-fuel-type for Spain, for all of 2024,
needed to reproduce the [chp] per-day block-size calibration in config.toml
(see its comments for the derivation, confirmed against the two existing
study days):

    gas_mw       = (ENTSO-E Fossil Gas GWh/day − OMIE cleared CCGT GWh/day) * 1000 / 24
    waste_mw     = (ENTSO-E Biomass + Waste GWh/day) * 1000 / 24
    minihydro_mw = (ENTSO-E Hydro(all types) GWh/day − OMIE Hydropower GWh/day) * 1000 / 24

"OMIE cleared CCGT"/"OMIE Hydropower" are our own already-validated per-unit
reconstruction (convert_omie_to_model_data.py); this script only fetches the
ENTSO-E side (Fossil Gas, Biomass, Waste, and all 3 ENTSO-E hydro psrTypes),
in one request per type for the whole year (6 API calls total).

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_chp_entsoe_year.py

Writes <DATA_DIR>/chp_entsoe_2024.csv (DATA_DIR: see fetch_entsoe.py): one row per (date, delivery_time 0-23), columns
fossil_gas_mw, biomass_mw, waste_mw, hydro_pumped_mw, hydro_ror_mw, hydro_reservoir_mw.
"""
import csv
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import DATA_DIR, call, parse, to_24  # noqa: E402

ES = "10YES-REE------0"
TZ = "Europe/Madrid"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(DATA_DIR, "chp_entsoe_2024.csv")

YEAR_START_UTC = "202312312300"
YEAR_END_UTC = "202412312300"

PSR_TYPES = {
    "fossil_gas_mw":     "B04",
    "biomass_mw":        "B01",
    "waste_mw":          "B17",
    "hydro_pumped_mw":   "B10",
    "hydro_ror_mw":      "B11",
    "hydro_reservoir_mw": "B12",
}


def year_series(token, psr_type, name):
    xml = call(dict(documentType="A75", processType="A16", in_Domain=ES, psrType=psr_type,
                     periodStart=YEAR_START_UTC, periodEnd=YEAR_END_UTC),
               token, f"chp_year_{name}")
    s = parse(xml, skip_consumption=True)
    s.index = s.index.tz_convert(TZ) if s.index.tz else s.index.tz_localize("UTC").tz_convert(TZ)
    return s.resample("h").mean()


def main():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    series = {}
    for name, psr in PSR_TYPES.items():
        print(f"Fetching full-year {name} (psrType {psr})...")
        try:
            series[name] = year_series(token, psr, name)
        except ValueError as e:
            print(f"  no data for {name}: {e}")
            series[name] = None

    rows = []
    d = date(2024, 1, 1)
    end = date(2024, 12, 31)
    missing_days = []
    while d <= end:
        day_str = d.isoformat()
        day_vals = {}
        ok = True
        for name, s in series.items():
            if s is None:
                day_vals[name] = [0.0] * 24
                continue
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
            row = {"date": day_str, "delivery_time": h}
            for name in PSR_TYPES:
                row[name] = day_vals[name][h]
            rows.append(row)
        d += timedelta(days=1)

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "delivery_time"] + list(PSR_TYPES))
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {len(rows)} hourly rows ({len(rows)//24} days) to {OUT_CSV}")
    if missing_days:
        print(f"WARNING: {len(missing_days)} days had no/incomplete data and were skipped:")
        print(" ", missing_days)


if __name__ == "__main__":
    main()
