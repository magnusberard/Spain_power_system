"""The mid-term SDDP's own Spain in 2024, against REE and OMIE (the W6 diagnosis).

The water values the market chain uses are the marginal value of water INSIDE the SDDP. If the
SDDP's Spain is oversupplied with cheap energy, its prices are too low and so is the water value,
whatever the reservoir level. This reads the diagnostic simulation written by
`julia --project=. midterm_sddp4.jl resim` (results/midterm4_diag.csv, 20 sampled years) and
reports, for the 2024 stages (weeks 1-52):
  - the SDDP's Spanish price by month (the balance dual per 2-hour block / 2) vs OMIE;
  - the most frequent price levels (which unit cost sets the price);
  - the Spanish annual energy balance vs REE's 2024 generation by technology.

    python hydro_state/diagnose_sddp.py [--real <spain-model-runs>/reference/real_hourly_2024.csv.gz]
"""
import argparse
import os

import pandas as pd

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BLOCK_H = 2.0

# REE, peninsular system, 2024 (REData generacion/estructura-generacion), TWh
REE_2024 = {
    "nuclear + cogeneration + waste": 52.39 + 16.38 + 1.19 + 0.65,
    "combined cycle + coal": 29.11 + 2.97,
    "wind + solar + other renewables": 59.50 + 43.69 + 4.13 + 3.68,
    "hydro (all)": 34.95,
    "total generation": 248.64,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--diag", default=os.path.join(ROOT, "results", "midterm4_diag.csv"))
    ap.add_argument("--real", default=None, help="real_hourly_2024.csv.gz (OMIE price), optional")
    args = ap.parse_args()

    d = pd.read_csv(args.diag)
    d = d[d.t <= 52].copy()
    n = d.rep.nunique()
    d["price"] = d.pES / BLOCK_H
    d["month"] = (pd.Timestamp("2024-01-01") + pd.to_timedelta((d.t - 1) * 7, unit="D")).dt.month

    m = d.groupby("month").agg(sddp_price=("price", "mean"),
                               share_below_30=("price", lambda x: (x < 30).mean()),
                               reservoir_GW=("turbES", lambda x: x.mean() / 1e3),
                               mid_merit_GW=("midES", lambda x: x.mean() / 1e3))
    if args.real:
        r = pd.read_csv(args.real)
        m["omie"] = r.groupby(r.date.str[5:7].astype(int)).price.mean()
    print(f"SDDP Spanish price by month (mean of {n} sampled years, 2-hour blocks)")
    print(m.round(2).to_string())
    print(f"\nYear: SDDP {d.price.mean():.1f} EUR/MWh"
          + (f", OMIE {pd.read_csv(args.real).price.mean():.1f}" if args.real else ""))
    print("Most frequent price levels (EUR/MWh: share of blocks):",
          {k: round(v, 3) for k, v in d.price.round(1).value_counts(normalize=True).head(8).items()})

    twh = lambda c: d[c].sum() * BLOCK_H / n / 1e6
    model = {
        "nuclear + cogeneration + waste": twh("baseES"),
        "combined cycle + coal": twh("midES") + twh("peakES"),
        "wind + solar + other renewables": twh("resES"),
        "hydro (all)": twh("turbES") + twh("stsES"),
        "total generation": twh("baseES") + twh("midES") + twh("peakES") + twh("resES")
                            + twh("turbES") + twh("stsES"),
    }
    print("\nSpain 2024 energy balance, TWh (SDDP mean vs REE peninsular)")
    print(f"{'':34s}{'SDDP':>8s}{'REE':>8s}")
    for k in REE_2024:
        print(f"{k:34s}{model[k]:8.1f}{REE_2024[k]:8.1f}")
    print(f"{'net import from PT':34s}{twh('fPTES'):8.1f}")
    print(f"{'net export to FR':34s}{twh('fESFR'):8.1f}")
    print(f"{'demand':34s}{twh('dES'):8.1f}")
    print("\nBuckets follow midterm_sddp4.jl resim: base <= 30, mid 30-100, peak > 100 EUR/MWh;")
    print("'wind + solar + other' is the used renewable output incl. run-of-river (gres);")
    print("'hydro (all)' = reservoir turbine + pumped storage net.")


if __name__ == "__main__":
    main()
