"""Fit phase II down bids per technology from REE's 2024 I90 files (step RD12).

In REE's phase II (P.O. 3.2) the energy phase I added is taken back at the units' own down bids:
a unit that goes down buys its day-ahead energy back at its bid. The model priced every down move
at the day-ahead price (phase I's rule), so who goes down was decided by the tie-break alone.

This script takes every phase II down move of 2024 (I90DIA03 energy, I90DIA09 price, redispatch
type ECO), maps the unit to a model technology (ree_unit_crosswalk.csv), divides its price by the
real day-ahead price of the hour (spain-model-runs/reference/real_hourly_2024.csv.gz, OMIE), and
takes the energy-weighted median ratio per technology. The model's down price is then
p_DA × (1 − down_markup) with down_markup = 1 − ratio ([redispatch.bids].down_refund = "bid_da").

    python redispatch_realism/fit_phase2_bids.py --i90 <esios_download/i90> --real <real_hourly_2024.csv.gz>
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
# REE production type → model (fuel, technology)
TYPE_MAP = {
    "Ciclo Combinado": ("Gas", "Combined_cycle"), "Gas Natural Cogeneración": ("Gas", "CHP"),
    "Hidráulica UGH": ("Hydro", "reservoir"), "Hidráulica no UGH": ("Hydro", "run_of_river"),
    "Turbinación bombeo": ("Hydro", "pumped_storage"), "Consumo bombeo": ("Hydro", "pumped_storage"),
    "Eólica terrestre": ("Wind", "Onshore"), "Solar fotovoltaica": ("Solar", "PV"), "Solar térmica": ("Solar", "Solar Thermal"),
    "Carbón de Importación": ("Coal", "Coal"), "Hulla antracita": ("Coal", "Coal"), "Hulla Antracita": ("Coal", "Coal"),
    "Hulla sub-bituminosa": ("Coal", "Coal"), "Nuclear": ("Nuclear", "Nuclear"), "Biomasa": ("Biomass", "Biomass"),
    "Biogás": ("Biomass", "Biomass"), "Residuos varios": ("Biomass", "CHP_Waste"),
    "Residuos domésticos y similares": ("Biomass", "CHP_Waste"), "Derivados del petróleo ó carbón": ("Oil", "Combined_cycle"),
    "Fuel": ("Oil", "Combined_cycle"),
}


def wmedian(x, w):
    o = np.argsort(x)
    c = np.cumsum(w[o])
    return float(x[o][np.searchsorted(c, c[-1] / 2)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, required=True)
    ap.add_argument("--real", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=HERE / "bids_fitted_phase2.csv")
    # calibration window (O14: fit on Jan-Jun, judge on Jul-Dec); default the whole year
    ap.add_argument("--days", nargs=2, metavar=("FIRST", "LAST"), default=["2024-01-01", "2024-12-31"])
    a = ap.parse_args()
    tc = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz")
    ucol = [c for c in tc.columns if c.startswith("Unidad")][0]
    tc = tc[(tc.Redespacho == "ECO") & (tc.Sentido == "Bajar") & tc.eur_mwh.notna()
            & (tc.date >= a.days[0]) & (tc.date <= a.days[1])].copy()
    cw = pd.read_csv(HERE / "ree_unit_crosswalk.csv")[["ree_unit", "ree_production_type"]]
    tc = tc.merge(cw, left_on=ucol, right_on="ree_unit", how="left")
    real = pd.read_csv(a.real, usecols=["date", "hour", "price"])
    tc = tc.merge(real, on=["date", "hour"], how="left")
    tc = tc[(tc.price > 5.0)]                                  # ratios near zero prices are noise
    tc["e"] = -tc.mwh
    tc["ratio"] = tc.eur_mwh / tc.price
    tot = tc.e.sum()
    print(f"phase II down 2024 with a positive day-ahead price: {tot / 1e3:.0f} GWh; mapped to a technology: "
          f"{tc[tc.ree_production_type.notna()].e.sum() / 1e3:.0f} GWh")
    rows = []
    for t, d in tc[tc.ree_production_type.notna()].groupby("ree_production_type"):
        if t not in TYPE_MAP or d.e.sum() < 1000:              # at least 1 GWh to fit
            continue
        rows.append(dict(type=t, fuel=TYPE_MAP[t][0], technology=TYPE_MAP[t][1], gwh=d.e.sum() / 1e3,
                         ratio=wmedian(d.ratio.values, d.e.values), mean_price=float(np.average(d.eur_mwh, weights=d.e))))
    r = pd.DataFrame(rows)
    # one value per model technology: energy-weighted across REE types
    m = r.groupby(["fuel", "technology"]).apply(lambda d: pd.Series(dict(
        gwh=d.gwh.sum(), ratio=np.average(d.ratio, weights=d.gwh), mean_price=np.average(d.mean_price, weights=d.gwh)))).reset_index()
    allr = wmedian(tc.ratio.values, tc.e.values)
    print(r.round(3).to_string(index=False))
    print(f"\nall phase II down: weighted median ratio to the day-ahead price {allr:.3f}")
    out = m.assign(down_markup=(1 - m.ratio).round(3))[["fuel", "technology", "down_markup", "ratio", "gwh", "mean_price"]]
    out.round(3).to_csv(a.out, index=False)
    print(f"\n{out.round(3).to_string(index=False)}\nwritten to {a.out}")


if __name__ == "__main__":
    main()
