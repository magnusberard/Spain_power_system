"""Cost per stage, hour and place for a run, next to REE's and OMIE's own figures (step F; Felipe, 8 Oct, O7).

O7 asked what "total cost" sums and whether the AC redispatch is in it. This script reports each piece
separately, so the thesis can say which one a number is:

  markets      price of each gate (DA, ID2, ID3, CID, BAL) and the energy each gate re-trades
               (Σ|ΔP|/2 against the gate before); real prices: OMIE day-ahead, e·sios IDA2 and continuous
  balancing    energy moved from CID to BAL, up and down, valued at the BAL price; REE: aFRR + mFRR + RR
               activated energy at their e·sios prices (up bought, down sold back)
  redispatch   phase I + II and real time, energy and extra cost as REE settles it (P.O. 14.4 §17.15,
               §18.8: up at the bid, down refunded, both against the day-ahead price). Phase I from
               rd_phase1_summary.csv (the model's own objective, start-ups included), real time from
               settle.py with the run's own rule; REE: e·sios rt1 (phase I), rt2 (phase II), rtr (real time)
  resource     Σ unit cost × output for the day-ahead schedule and for the final dispatch; the difference
               is the physical cost of every adjustment after the day-ahead (redispatch included)

By place: phase I and real-time energy and extra cost per NUTS2 region (unit → bus → Data/bus_nuts3.csv);
phase I per unit is priced like the model's objective (start-ups not allocated to regions).

    python redispatch_realism/stage_costs.py <run or Solstorm parent folder> --bids redispatch_realism/bids_fitted.csv \
        --storage-at-da --esios ../spain-model-runs/reference/esios_2024.js \
        --real ../spain-model-runs/reference/real_hourly_2024.csv.gz [--out <folder>]

Writes <out>/hourly.csv, <out>/by_region.csv, <out>/totals.csv (default <run>/stage_costs/) and prints the totals.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import settle
from compare_ree import run_down_refund

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NUTS2 = {"ES11": "Galicia", "ES12": "Asturias", "ES13": "Cantabria", "ES21": "País Vasco", "ES22": "Navarra",
         "ES23": "La Rioja", "ES24": "Aragón", "ES30": "Madrid", "ES41": "Castilla y León",
         "ES42": "Castilla-La Mancha", "ES43": "Extremadura", "ES51": "Cataluña", "ES52": "C. Valenciana",
         "ES53": "Illes Balears", "ES61": "Andalucía", "ES62": "Murcia", "ES63": "Ceuta", "ES64": "Melilla"}
STAGES = ["DA", "ID2", "ID3", "CID", "BAL"]
FILES = {"DA": "da_dispatch.csv", "ID2": "id2_dispatch.csv", "ID3": "id3_dispatch.csv", "CID": "cid_dispatch.csv",
         "BAL": "bal_dispatch.csv"}


def ree_hourly(path, days):
    t = Path(path).read_text(encoding="utf-8")
    e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    ix = {d: i for i, d in enumerate(e["days"])}
    s = e["series"]
    v = lambda k, i: (s[k][i] or 0.0) if k in s else 0.0
    rows = []
    for d in days:
        for h in range(24):
            i = ix[d] * 24 + h
            bal_up = v("afrr_up", i) + v("mfrr_up", i) + v("rr_up", i)
            bal_dn = v("afrr_down", i) + v("mfrr_down", i) + v("rr_down", i)
            bal_val = (v("afrr_up", i) * v("afrr_up_price", i) + v("mfrr_up", i) * v("mfrr_up_price", i)
                       + v("rr_up", i) * v("rr_price", i)
                       - v("afrr_down", i) * v("afrr_down_price", i) - v("mfrr_down", i) * v("mfrr_down_price", i)
                       - v("rr_down", i) * v("rr_price", i))
            rows.append(dict(date=d, hour=h, real_ida2=s["ida2"][i], real_cid=s["cid"][i],
                             ree_bal_up_mwh=bal_up, ree_bal_down_mwh=bal_dn, ree_bal_value_eur=bal_val,
                             ree_ph1_up_mwh=v("rt1_up", i), ree_ph1_cost_eur=v("rt1_up_cost", i) - v("rt1_down_cost", i),
                             ree_ph2_cost_eur=v("rt2_up_cost", i) - v("rt2_down_cost", i),
                             ree_rt_up_mwh=v("rtr_up", i), ree_rt_cost_eur=v("rtr_up_cost", i) + v("rtr_down_cost", i)))
    return pd.DataFrame(rows)


def one_run(run, a, bus_region, cost_by):
    keys = ["date", "hour"]
    pr = pd.read_csv(run / "market_prices.csv")
    p = pr.pivot_table(index=keys, columns="stage", values="price_eur_mwh").reindex(columns=STAGES)
    p.columns = [f"p_{c.lower()}" for c in p.columns]
    out = p.reset_index()
    # unit cost per unit-hour (the final dispatch file carries it for every unit)
    g = pd.read_csv(run / "gen_dispatch.csv", usecols=keys + ["unit_name", "fuel", "technology", "dispatch_mw", "cost_eur_per_mwh"])
    g = g[~g.unit_name.str.startswith(settle.PSEUDO)]
    cost = g[keys + ["unit_name", "cost_eur_per_mwh"]]
    out = out.merge(g.assign(r=g.dispatch_mw * g.cost_eur_per_mwh).groupby(keys).r.sum().rename("final_resource_eur").reset_index(),
                    on=keys, how="left")
    sched = {}
    for st in STAGES:
        f = run / FILES[st]
        if not f.exists():
            continue
        d = pd.read_csv(f, usecols=keys + ["gen_id", "dispatch_mw"]).rename(columns={"gen_id": "unit_name"})
        sched[st] = d[~d.unit_name.str.startswith(settle.PSEUDO)]
    if "DA" in sched:
        da = sched["DA"].merge(cost, on=keys + ["unit_name"], how="left")
        out = out.merge((da.dispatch_mw * da.cost_eur_per_mwh.fillna(0)).groupby([da.date, da.hour]).sum()
                        .rename("da_resource_eur").reset_index(), on=keys, how="left")
    prev = "DA"
    for st in ["ID2", "ID3", "CID", "BAL"]:
        if st not in sched or prev not in sched:
            continue
        m = sched[st].merge(sched[prev], on=keys + ["unit_name"], how="outer", suffixes=("", "_prev")).fillna(0.0)
        dd = m.dispatch_mw - m.dispatch_mw_prev
        t = pd.DataFrame({"date": m.date, "hour": m.hour, "up": dd.clip(lower=0), "dn": (-dd).clip(lower=0)}).groupby(keys).sum()
        out = out.merge(((t.up + t.dn) / 2).rename(f"{st.lower()}_retraded_mwh").reset_index(), on=keys, how="left")
        if st == "BAL":
            out = out.merge(t.rename(columns={"up": "bal_up_mwh", "dn": "bal_down_mwh"}).reset_index(), on=keys, how="left")
        prev = st
    if "bal_up_mwh" in out:
        out["bal_value_eur"] = (out.bal_up_mwh - out.bal_down_mwh) * out.p_bal
    # phase I + II: the model's own settled cost per hour (start-ups included)
    sf = run / "rd_phase1_summary.csv"
    if sf.exists():
        s = pd.read_csv(sf)[keys + ["up_mwh", "down_mwh", "extra_cost_eur"]]
        out = out.merge(s.rename(columns={"up_mwh": "ph1_up_mwh", "down_mwh": "ph1_down_mwh", "extra_cost_eur": "ph1_cost_eur"}),
                        on=keys, how="left")
    # real time: settle.py with the run's own rule
    hourly, _, _, _, u = settle.settle(run, bids=a.bids, down_refund=run_down_refund(run), storage_at_da=a.storage_at_da, units=True)
    out = out.merge(hourly[keys + ["up_mwh", "down_mwh", "extra_cost_eur"]].rename(
        columns={"up_mwh": "rt_up_mwh", "down_mwh": "rt_down_mwh", "extra_cost_eur": "rt_cost_eur"}), on=keys, how="left")
    # by place
    u["region"] = u.unit_name.map(bus_region)
    reg = [u.groupby("region").agg(rt_up_mwh=("up", "sum"), rt_down_mwh=("down", "sum"), rt_cost_eur=("ec", "sum"))]
    pf = run / "rd_phase1.csv"
    if pf.exists():
        q = pd.read_csv(pf).rename(columns={"unit": "unit_name"})
        q = q.merge(cost, on=keys + ["unit_name"], how="left").merge(out[keys + ["p_da"]], on=keys, how="left")
        mk = settle.load_bids(a.bids)
        c = q.cost_eur_per_mwh.fillna(q.p_da)
        if a.storage_at_da:
            c = c.where(~pd.Series([k in settle.STORAGE for k in zip(q.fuel, q.technology)], index=q.index), q.p_da)
        mu = np.array([mk.get(k, (0.0, 0.0))[0] for k in zip(q.fuel, q.technology)])
        md = np.array([mk.get(k, (0.0, 0.0))[1] for k in zip(q.fuel, q.technology)])
        dlt = q.phase1_mw - q.da_mw
        up, dn = dlt.clip(lower=0), (-dlt).clip(lower=0)
        p_up = np.maximum(c, q.p_da) * (1 + mu)                      # the model's objective (rd_bid_prices)
        p_dn = q.p_da * (1 - md)                                     # bid_da (RD12)
        q = q.assign(up=up, dn=dn, ec=up * (p_up - q.p_da) + dn * (q.p_da - p_dn), region=q.unit_name.map(bus_region))
        reg.append(q.groupby("region").agg(ph1_up_mwh=("up", "sum"), ph1_down_mwh=("dn", "sum"), ph1_cost_eur=("ec", "sum")))
    return out, pd.concat(reg, axis=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--bids", type=Path)
    ap.add_argument("--storage-at-da", action="store_true")
    ap.add_argument("--esios", type=Path, default=REPO.parent / "spain-model-runs" / "reference" / "esios_2024.js")
    ap.add_argument("--real", type=Path, default=REPO.parent / "spain-model-runs" / "reference" / "real_hourly_2024.csv.gz")
    ap.add_argument("--i90", type=Path, default=REPO.parent / "esios_download" / "i90", help="for REE's phase I per region")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    runs = [a.run] if (a.run / "summary.csv").exists() else sorted(p for p in a.run.iterdir() if (p / "summary.csv").exists())
    gen = pd.read_csv(REPO / "Data" / "generations.csv", usecols=["unit_id", "bus_id"])
    nuts = pd.read_csv(REPO / "Data" / "bus_nuts3.csv", usecols=["bus_id", "nuts3"])
    b = gen.merge(nuts, on="bus_id", how="left")
    bus_region = dict(zip(b.unit_id, b.nuts3.str[:4].map(NUTS2).fillna(b.nuts3.str[:4]).fillna("unknown")))
    hrs, regs = [], []
    for r in runs:
        h, g = one_run(r, a, bus_region, None)
        hrs.append(h); regs.append(g)
    hourly = pd.concat(hrs, ignore_index=True).sort_values(["date", "hour"])
    real = pd.read_csv(a.real, usecols=["date", "hour", "price"]).rename(columns={"price": "real_da"})
    hourly = hourly.merge(real, on=["date", "hour"], how="left").merge(ree_hourly(a.esios, sorted(hourly.date.unique())),
                                                                       on=["date", "hour"], how="left")
    by_region = pd.concat(regs).groupby(level=0).sum()
    # REE's phase I up per region over the same days: I90 per unit (UPO..., Subir), units the crosswalk maps to a
    # model unit (renewable portfolios are not mapped, so this covers the thermal side)
    if a.i90 is not None and (a.i90 / "i90_tc_phase.csv.gz").exists():
        x = pd.read_csv(HERE / "ree_unit_crosswalk.csv")[["ree_unit", "model_unit_id"]].dropna()
        ph = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz", low_memory=False, usecols=["date", "Redespacho", "Sentido", "Unidad de Programación", "mwh"])
        ph = ph[ph.date.isin(hourly.date.unique()) & ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")]
        tot = ph.mwh.sum()
        ph = ph.merge(x.drop_duplicates("ree_unit"), left_on="Unidad de Programación", right_on="ree_unit")
        ph["region"] = ph.model_unit_id.map(bus_region)
        by_region["ree_ph1_up_mwh"] = ph.groupby("region").mwh.sum()
        print(f"REE phase I up mapped to a region: {ph.mwh.sum() / 1e3:.0f} of {tot / 1e3:.0f} GWh")
    by_region = by_region.fillna(0.0).div(1e3).round(1).rename(columns=lambda c: c.replace("_mwh", "_gwh").replace("_eur", "_keur"))
    out = a.out or (a.run / "stage_costs")
    out.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(out / "hourly.csv", index=False)
    by_region.sort_values(by_region.columns[0], ascending=False).to_csv(out / "by_region.csv")
    H = hourly
    gwh = lambda c: H[c].sum() / 1e3 if c in H else np.nan
    meur = lambda c: H[c].sum() / 1e6 if c in H else np.nan
    mean = lambda c: H[c].mean() if c in H else np.nan
    rows = [("day-ahead price, €/MWh", mean("p_da"), mean("real_da")),
            ("ID2 price, €/MWh", mean("p_id2"), mean("real_ida2")),
            ("CID price, €/MWh", mean("p_cid"), mean("real_cid")),
            ("BAL price, €/MWh", mean("p_bal"), np.nan),
            ("ID2 re-traded, GWh", gwh("id2_retraded_mwh"), np.nan),
            ("CID re-traded, GWh", gwh("cid_retraded_mwh"), np.nan),
            ("balancing up, GWh", gwh("bal_up_mwh"), gwh("ree_bal_up_mwh")),
            ("balancing down, GWh", gwh("bal_down_mwh"), gwh("ree_bal_down_mwh")),
            ("balancing energy value, M€", meur("bal_value_eur"), meur("ree_bal_value_eur")),
            ("phase I up, GWh", gwh("ph1_up_mwh"), gwh("ree_ph1_up_mwh")),
            ("phase I + II extra cost, M€", meur("ph1_cost_eur"), meur("ree_ph1_cost_eur") + meur("ree_ph2_cost_eur")),
            ("real-time up, GWh", gwh("rt_up_mwh"), gwh("ree_rt_up_mwh")),
            ("real-time extra cost, M€", meur("rt_cost_eur"), meur("ree_rt_cost_eur")),
            ("redispatch extra cost, all phases, M€", meur("ph1_cost_eur") + meur("rt_cost_eur"),
             meur("ree_ph1_cost_eur") + meur("ree_ph2_cost_eur") + meur("ree_rt_cost_eur")),
            ("resource cost, day-ahead schedule, M€", meur("da_resource_eur"), np.nan),
            ("resource cost, final dispatch, M€", meur("final_resource_eur"), np.nan),
            ("  difference: physical cost of all adjustments, M€", meur("final_resource_eur") - meur("da_resource_eur"), np.nan)]
    t = pd.DataFrame(rows, columns=["measure", "model", "REE / OMIE"])
    t.to_csv(out / "totals.csv", index=False)
    print(f"{len(runs)} run folder(s), {H.date.nunique()} days, {len(H)} hours -> {out}")
    print(t.round(1).to_string(index=False))
    print("\nby region (GWh, k€):\n" + by_region.sort_values(by_region.columns[0], ascending=False).head(10).to_string())


if __name__ == "__main__":
    main()
