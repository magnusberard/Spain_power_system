"""REE's real-time technical-constraint cost per hour, as P.O. 14.4 §19.10 defines it (F1, 6 Nov 2026).

P.O. 14.4 §19.10 (BOE-A-2024-6215, p. 138): the cost of real-time constraints is what the units are paid
(energy at the offer price, start-ups, hourly terms) minus the real-time energy valued at a reference
price, which in 2024 is the day-ahead marginal price (the imbalance price later).

e·sios 1723/1724, which the comparisons used until 6 Nov, are REE's GROSS real-time payments: in 2024
1,295 M€, more than REE paid for all the real-time energy (I90: 1,147 M€). The cost here:
  energy:    I90 real-time technical constraints, priced records:
             up Σ mwh·(offer − p_DA) + down Σ |mwh|·(p_DA − price)
  start-ups: not in I90; estimated as e·sios 1723 − I90's gross up energy payment (2024: 148 M€)
Checks: 2024 ≈ 850 M€, and with REE's phase I/II (e·sios) 2.07 b€, against 2,057 M€ reported by REE
for 2024; 2023's I90 energy part (690 M€) plus the same ~148 M€ matches CNMC's 837 M€ (supervision
report 28 Jan 2025, p. 59). The start-up estimate is noisy per hour (it can be negative); use sums.

    from ree_rt_cost import rt_cost_hourly
    h = rt_cost_hourly(i90_dir, da_csv, esios_js)   # date, hour, energy_eur, startup_eur, cost_eur, gross_esios_eur
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd


def rt_cost_hourly(i90_dir, da_path, esios_js):
    p = pd.read_csv(Path(i90_dir) / "i90_tc_realtime.csv.gz")
    p = p[(p.Redespacho == "Restricciones Técnicas") & p.eur_mwh.notna()]
    da = pd.read_csv(da_path, usecols=["date", "hour", "price"]).rename(columns={"price": "p_da"})
    p = p.merge(da, on=["date", "hour"], how="left")
    up = p.Sentido == "Subir"
    p["energy_eur"] = np.where(up, p.mwh * (p.eur_mwh - p.p_da), p.mwh.abs() * (p.p_da - p.eur_mwh))
    p["gross_up_i90"] = np.where(up, p.mwh * p.eur_mwh, 0.0)
    h = p.groupby(["date", "hour"], as_index=False)[["energy_eur", "gross_up_i90"]].sum()
    t = Path(esios_js).read_text(encoding="utf-8")
    e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    ix = {d: i for i, d in enumerate(e["days"])}
    s = lambda k: [(d, hh, e["series"][k][ix[d] * 24 + hh] or 0.0) for d in e["days"] for hh in range(24)]
    es = pd.DataFrame(s("rtr_up_cost"), columns=["date", "hour", "gross_up_esios"])
    es["gross_esios_eur"] = es.gross_up_esios + pd.DataFrame(s("rtr_down_cost"), columns=["d", "h", "v"]).v
    h = es.merge(h, on=["date", "hour"], how="left").fillna({"energy_eur": 0.0, "gross_up_i90": 0.0})
    h["startup_eur"] = h.gross_up_esios - h.gross_up_i90
    h["cost_eur"] = h.energy_eur + h.startup_eur
    return h[["date", "hour", "energy_eur", "startup_eur", "cost_eur", "gross_esios_eur"]]
