"""F2 (6 Nov 2026): a real-time up mark-up for CCGTs, fitted on REE's real-time prices Jan-Jun 2024, tested Jul-Dec.

Why: the model prices every up-move with one rule, bid_up = max(c, p_DA) * (1 + up_markup), and the CCGT mark-up
(0.451, RD10b) was fitted on REE's PHASE I prices. REE pays CCGTs more in real time: 213 vs 156 EUR/MWh in 2024
(I90, i90_prices.py). Real-time I90 prices are energy only (start-ups are separate terms since BOE-A-2024-6215 and
paid outside I90: ree_rt_cost.py), so unlike RD10b no start-up share is taken out.

Method (fixed before the data were read; committed before running):
  REE      I90 real-time technical constraints (i90_tc_realtime), up, priced, units the crosswalk maps to a model
           CCGT; per unit-hour: energy (MWh) and price paid (EUR/MWh)
  model    the published year run (default solstorm_results/y24act): per unit-hour the unit's own cost c
           (gen_dispatch.csv cost_eur_per_mwh) and the hour's model day-ahead price (market_prices.csv, stage DA);
           base = max(c, p_DA_model), the rule without its mark-up
  fit      m_rt = sum(MWh * paid) / sum(MWh * base) - 1 over January-June (energy-weighted level)
  test     July-December: per month the energy-weighted predicted price base * (1 + m) against REE's paid price;
           mean absolute monthly error, with m_rt and with the phase I mark-up 0.451
  keep     m_rt goes into [redispatch.bids].rt_by_type only if its July-December error is lower than 0.451's

    python redispatch_realism/fit_rt_upmarkup.py --i90 ../esios_download/i90 --model-run <solstorm_results/y24act>
Writes redispatch_realism/data/rt_upmarkup_fit.csv (per month: REE paid, base, predicted with both mark-ups).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PHASE1_MARKUP = 0.451          # bids_fitted.csv, Gas:Combined_cycle (RD10b)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, required=True)
    ap.add_argument("--model-run", type=Path, required=True, help="year run folder (weekly chunk subfolders)")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "rt_upmarkup_fit.csv")
    a = ap.parse_args()

    cw = pd.read_csv(HERE / "ree_unit_crosswalk.csv")
    cw = cw[(cw.technology == "CCGT") & cw.model_unit_id.notna()]
    ree_to_model = dict(zip(cw.ree_unit.str.strip(), cw.model_unit_id))
    p = pd.read_csv(a.i90 / "i90_tc_realtime.csv.gz")
    p = p[(p.Redespacho == "Restricciones Técnicas") & (p.Sentido == "Subir") & p.eur_mwh.notna()].copy()
    p["unit"] = p["Unidad de Programación"].str.strip().map(ree_to_model)
    p = p[p.unit.notna()]
    p = p.groupby(["date", "hour", "unit"], as_index=False).apply(
        lambda g: pd.Series({"mwh": g.mwh.sum(), "paid": np.average(g.eur_mwh, weights=g.mwh)}), include_groups=False)
    units = set(p.unit)

    chunks = sorted(d for d in a.model_run.iterdir() if (d / "gen_dispatch.csv").exists())
    cost, pda = [], []
    for d in chunks:
        for g in pd.read_csv(d / "gen_dispatch.csv", usecols=["date", "hour", "unit_name", "cost_eur_per_mwh"], chunksize=500_000):
            cost.append(g[g.unit_name.isin(units)])
        m = pd.read_csv(d / "market_prices.csv")
        pda.append(m[m.stage == "DA"][["date", "hour", "price_eur_mwh"]])
    cost = pd.concat(cost).drop_duplicates(["date", "hour", "unit_name"]).rename(columns={"unit_name": "unit", "cost_eur_per_mwh": "c"})
    pda = pd.concat(pda).drop_duplicates(["date", "hour"]).rename(columns={"price_eur_mwh": "p_da_model"})
    x = p.merge(cost, on=["date", "hour", "unit"], how="inner").merge(pda, on=["date", "hour"], how="inner")
    x["base"] = np.maximum(x.c, x.p_da_model)
    x["month"] = x.date.str[:7]
    print(f"REE real-time CCGT up, priced and mapped: {p.mwh.sum() / 1e3:,.0f} GWh; matched to the model run: "
          f"{x.mwh.sum() / 1e3:,.0f} GWh ({x.mwh.sum() / p.mwh.sum():.0%})")

    fit = x[x.month <= "2024-06"]
    m_rt = (fit.mwh * fit.paid).sum() / (fit.mwh * fit.base).sum() - 1
    mon = x.groupby("month").apply(lambda g: pd.Series({
        "gwh": g.mwh.sum() / 1e3, "ree_paid": np.average(g.paid, weights=g.mwh), "base": np.average(g.base, weights=g.mwh)}),
        include_groups=False)
    mon["pred_rt"] = mon.base * (1 + m_rt)
    mon["pred_phase1"] = mon.base * (1 + PHASE1_MARKUP)
    mon["err_rt"] = mon.pred_rt - mon.ree_paid
    mon["err_phase1"] = mon.pred_phase1 - mon.ree_paid
    a.out.parent.mkdir(parents=True, exist_ok=True)
    mon.round(2).to_csv(a.out)
    print(mon.round(1).to_string())
    test = mon[mon.index >= "2024-07"]
    mae_rt, mae_p1 = test.err_rt.abs().mean(), test.err_phase1.abs().mean()
    print(f"\nm_rt (fitted Jan-Jun) = {m_rt:.3f}   (phase I mark-up {PHASE1_MARKUP})")
    print(f"Jul-Dec mean absolute monthly error: m_rt {mae_rt:.1f} EUR/MWh, phase I mark-up {mae_p1:.1f} EUR/MWh")
    print(f"Jul-Dec bias (energy-weighted): m_rt {np.average(test.err_rt, weights=test.gwh):+.1f}, "
          f"phase I mark-up {np.average(test.err_phase1, weights=test.gwh):+.1f} EUR/MWh")
    print("KEEP: m_rt is better out of sample" if mae_rt < mae_p1 else "DROP: m_rt is not better out of sample; keep 0.451")


if __name__ == "__main__":
    main()
