"""What REE paid for technical-constraint redispatch, by technology, against the day-ahead price.

Reads the I90 tables from fetch_i90.py and the unit crosswalk ree_unit_crosswalk.csv (REE/OMIE
programming unit → technology → model unit_id; built from OMIE's LISTA_UNIDADES, REE e·sios
archives 81/82 and OMIE's June 2024 unit list; see its source/notes columns). Day-ahead price:
spain-model-runs/reference/real_hourly_2024.csv.gz (OMIE, column price).

    python redispatch_realism/i90_prices.py
    python redispatch_realism/i90_prices.py --days 2024-12-02 2024-12-04 --model-run results/<run>

Prints phase I upward and real-time upward energy, the energy-weighted price paid and the
day-ahead price in the same hours, by technology and (CCGT) by month. With --model-run it adds
the model's own cost per technology from gen_dispatch.csv and the implied up mark-up
(paid / model cost − 1) for [redispatch.bids].
"""
import argparse
import os
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def weighted(d):
    return pd.Series({"gwh": d.mwh.sum() / 1e3,
                      "paid": (d.mwh * d.eur_mwh).sum() / d.mwh.sum(),
                      "p_da": (d.mwh * d.p_da).sum() / d.mwh.sum()})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90")
    ap.add_argument("--da", type=Path, default=REPO.parent / "spain-model-runs" / "reference" / "real_hourly_2024.csv.gz")
    ap.add_argument("--days", nargs=2, metavar=("FIRST", "LAST"))
    ap.add_argument("--model-run", type=Path)
    a = ap.parse_args()

    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv")[["ree_unit", "technology"]]
    da = pd.read_csv(a.da, usecols=["date", "hour", "price"]).rename(columns={"price": "p_da"})

    def prep(df):
        if a.days:
            df = df[(df.date >= a.days[0]) & (df.date <= a.days[1])]
        df = df.merge(x, left_on="Unidad de Programación", right_on="ree_unit", how="left").merge(da, on=["date", "hour"])
        df["technology"] = df.technology.fillna("unmapped")
        return df.dropna(subset=["eur_mwh", "p_da"])

    ph = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz")
    rt = pd.read_csv(a.i90 / "i90_tc_realtime.csv.gz")
    sets = {"Phase I up": prep(ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")]),
            "Real-time constraints up": prep(rt[(rt.Redespacho == "Restricciones Técnicas") & (rt.Sentido == "Subir")])}
    cost = None
    if a.model_run:
        g = pd.read_csv(a.model_run / "gen_dispatch.csv", usecols=["fuel", "technology", "cost_eur_per_mwh"])
        tech = {("Gas", "Combined_cycle"): "CCGT", ("Coal", "Coal"): "coal", ("Nuclear", "Nuclear"): "nuclear"}
        g["t"] = [tech.get(k) for k in zip(g.fuel, g.technology)]
        cost = g.dropna(subset=["t"]).groupby("t").cost_eur_per_mwh.median()
    for name, d in sets.items():
        t = d.groupby("technology").apply(weighted, include_groups=False).sort_values("gwh", ascending=False)
        t["paid/p_da"] = t.paid / t.p_da
        t["share_%"] = 100 * t.gwh / t.gwh.sum()
        if cost is not None:
            t["model_cost"] = cost.reindex(t.index)
            t["up_markup"] = t.paid / t.model_cost - 1
        tot = weighted(d)
        print(f"\n{name}: {tot.gwh:,.0f} GWh, paid {tot.paid:.1f} €/MWh, day-ahead {tot.p_da:.1f} €/MWh")
        print(t.round(2).to_string())
    ccgt = sets["Phase I up"][sets["Phase I up"].technology == "CCGT"].assign(month=lambda d: d.date.str[:7])
    if ccgt.month.nunique() > 1:
        m = ccgt.groupby("month").apply(weighted, include_groups=False)
        m["paid/p_da"] = m.paid / m.p_da
        print("\nCCGT phase I up by month:\n" + m.round(2).to_string())


if __name__ == "__main__":
    main()
