"""Real hourly pumping consumption of 2024, for taking it out of the 2024 load ([run].remove_pumping).

The 2024 load (convert_omie_to_model_data.py) is OMIE's day-ahead production + imports, so it also
holds the energy the real pumps bought; the model's own pumped storage then pumps on top of it.
This writes the real pumping, per model hour, so run_market_chain.jl can subtract it (pumping.jl).

Source: REE e·sios indicator 25, "Generación programada PBF Consumo bombeo" (day-ahead schedule,
peninsula, negative MWh), fetched by esios_download/fetch_pumping.py (outside the repo) into
<esios-dir>/raw/25_*.json, summed per hour (so the quarter-hour periods from Oct 2024 give MWh per
hour). e·sios leaves out hours with no pumping: they are 0 here.

Hours follow the 2024 load's convention (convert_omie_to_model_data.to_24): the periods of the day
in time order; the 23-hour day repeats its last hour, the 25-hour day drops its third period.

    python omie_conversion/build_pumping_2024.py
    python omie_conversion/build_pumping_2024.py --esios-dir ../esios_download

Writes <out> (default Data/OMIE/pumping_2024.csv): date, hour (0-23), pumping_mw (>= 0).
"""
import argparse
import glob
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ESIOS_DIR = os.environ.get("ESIOS_DIR") or os.path.join(HERE, "..", "..", "esios_download")
OUT = os.path.join(HERE, "..", "Data", "OMIE", "pumping_2024.csv")
INDICATOR = 25


def to_24(v):
    """Same rule as convert_omie_to_model_data.to_24, on a list of the day's periods."""
    if len(v) == 24:
        return v
    if len(v) == 23:
        return v + [v[-1]]
    if len(v) == 25:
        return v[:2] + v[3:]
    raise ValueError(f"unexpected {len(v)} periods")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--esios-dir", default=ESIOS_DIR)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.esios_dir, "raw", f"{INDICATOR}_{args.year}-*.json")))
    if len(files) != 12:
        raise SystemExit(f"expected 12 monthly files {INDICATOR}_{args.year}-*.json in "
                         f"{args.esios_dir}/raw, found {len(files)}: run esios_download/fetch_pumping.py")
    values = [v for f in files for v in json.load(open(f, encoding="utf-8"))]
    df = pd.DataFrame(values)
    df = df[df.geo_name.str.startswith("Pen")]          # "Península" (the only geo of this series)
    utc = pd.to_datetime(df.datetime_utc, utc=True)
    mw = (-df.value).groupby(utc).sum()                  # consumption is negative in e·sios
    if (mw < -1e-6).any():
        raise SystemExit(f"{(mw < -1e-6).sum()} hours with positive pumping values: check the series")

    rows = []
    for d in pd.date_range(f"{args.year}-01-01", f"{args.year}-12-31", freq="D"):
        start = pd.Timestamp(d, tz="Europe/Madrid")
        # a DST day has 23/25 hours: build them in UTC so none is lost or repeated
        periods = pd.date_range(start.tz_convert("UTC"),
                                (start + pd.DateOffset(days=1)).tz_convert("UTC"), freq="h", inclusive="left")
        v = [float(mw.get(p, 0.0)) for p in periods]
        for h, x in enumerate(to_24(v)):
            rows.append((d.strftime("%Y-%m-%d"), h, round(max(x, 0.0), 3)))
    out = pd.DataFrame(rows, columns=["date", "hour", "pumping_mw"])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    out.to_csv(args.out, index=False, lineterminator="\n")

    print(f"{args.out}: {out.date.nunique()} days, {len(out)} hours")
    print(f"  pumping {out.pumping_mw.sum() / 1e6:.2f} TWh, max {out.pumping_mw.max():.0f} MW, "
          f"{(out.groupby('date').pumping_mw.sum() == 0).sum()} days without pumping")
    by_hour = out.groupby("hour").pumping_mw.mean().round().astype(int).tolist()
    print(f"  mean MW by hour: {by_hour}")


if __name__ == "__main__":
    main()
