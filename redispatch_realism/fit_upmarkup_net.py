"""Refit the phase I up mark-up net of start-ups (step RD10b).

REE's phase I prices include start-ups: thermal units bid complex offers with start-up terms, and in
2024 units REE started were paid 150 €/MWh against 102 €/MWh for units only raised (I90DIA03/09,
redispatch type UPOPVPV). RD10's mark-up (paid / model cost − 1) was fitted to those all-in prices,
and phase I then adds the model's own start-up cost on top: start-ups counted twice.

Here, per technology over the chosen days:
    starts     = REE's phase I starts: a unit with no day-ahead energy raised in phase I, counted
                 once per run of consecutive hours
    start cost = starts × the model's start cost per MW (--start-eur-per-mw, by default the median of
                 the model's own start-ups in rd_startups.csv of --model-run) × the unit's size
    net price  = (Σ paid − start cost) / Σ energy
    up_markup  = net price / model cost − 1      (model cost: gen_dispatch.csv of --model-run)

    python redispatch_realism/fit_upmarkup_net.py --days 2024-12-01 2024-12-29 \
        --model-run results/2024_by_month/2024-12 --startups <run with rd_startups.csv>
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, required=True)
    ap.add_argument("--days", nargs=2, required=True)
    ap.add_argument("--model-run", type=Path, required=True, help="run whose gen_dispatch.csv gives the model's costs")
    ap.add_argument("--startups", type=Path, required=True, help="run whose rd_startups.csv gives start cost per MW")
    a = ap.parse_args()
    d0, d1 = a.days
    cw = pd.read_csv(HERE / "ree_unit_crosswalk.csv")[["ree_unit", "technology", "model_unit_id", "model_capacity_mw", "ree_capacity_mw"]]
    tc = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz")
    ucol = [c for c in tc.columns if c.startswith("Unidad")][0]
    tc = tc[(tc.date >= d0) & (tc.date <= d1)].rename(columns={ucol: "u"})
    up = tc[(tc.Redespacho == "UPOPVPV") & (tc.Sentido == "Subir") & tc.eur_mwh.notna()]
    up = up.groupby(["date", "hour", "u"], as_index=False).agg(mwh=("mwh", "sum"), eur=("eur_mwh", "mean"))
    pv = pd.read_csv(a.i90 / "i90_pdvp.csv.gz").rename(columns=lambda c: "u" if c.startswith("Unidad") else c)
    pv = pv[(pv.date >= d0) & (pv.date <= d1)].groupby(["date", "hour", "u"], as_index=False).mwh.sum().rename(columns={"mwh": "pdvp"})
    m = up.merge(pv, on=["date", "hour", "u"], how="left").fillna({"pdvp": 0.0})
    m["started"] = (m.pdvp - m.mwh) < 1.0
    m = m.merge(cw, left_on="u", right_on="ree_unit", how="inner")
    m = m[m.technology.isin(["CCGT", "Coal"])]
    # starts: consecutive started hours of a unit count once
    s = m[m.started].copy()
    s["t"] = pd.to_datetime(s.date) + pd.to_timedelta(s.hour, unit="h")
    s = s.sort_values(["u", "t"])
    s["new"] = s.groupby("u").t.diff().ne(pd.Timedelta(hours=1))
    st = pd.read_csv(a.startups / "rd_startups.csv")
    gd = pd.read_csv(a.model_run / "gen_dispatch.csv", usecols=["unit_name", "capacity_mw", "cost_eur_per_mwh", "dispatch_mw", "date", "technology", "fuel"])
    cap = gd.drop_duplicates("unit_name").set_index("unit_name").capacity_mw
    st["cap"] = st.unit.map(cap)
    per_mw = (st.start_cost_eur / st.cap).groupby(st.technology).median()
    gd = gd[(gd.date >= d0) & (gd.date <= d1) & (gd.dispatch_mw > 1)]
    rows = []
    for tech, mt in (("CCGT", "Combined_cycle"), ("Coal", "Coal")):
        e = m[m.technology == tech]
        if e.mwh.sum() <= 0:
            continue
        paid = (e.mwh * e.eur).sum()
        n_start = int(s[(s.technology == tech)].new.sum())
        size = s[(s.technology == tech) & s.new].ree_capacity_mw.fillna(s.model_capacity_mw).sum()
        eur_mw = float(per_mw.get(mt, np.nan))
        start_cost = size * eur_mw
        g = gd[gd.technology == mt]
        cost = float(np.average(g.cost_eur_per_mwh, weights=g.dispatch_mw))
        gross = paid / e.mwh.sum()
        net = (paid - start_cost) / e.mwh.sum()
        rows.append(dict(technology=mt, phase1_gwh=e.mwh.sum() / 1e3, paid_eur_mwh=gross, starts=n_start,
                         start_eur_per_mw=eur_mw, start_share_eur_mwh=start_cost / e.mwh.sum(),
                         net_eur_mwh=net, model_cost=cost, up_markup_gross=gross / cost - 1, up_markup_net=net / cost - 1))
    out = pd.DataFrame(rows)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
