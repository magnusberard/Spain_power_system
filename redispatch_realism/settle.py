"""Settle a run's redispatch the way REE settles technical constraints (P.O. 14.4) — step RD1.

Reads results/<run>/ (piece by piece, like publish_run.py) and reports, over the solved AC hours:
energy turned up and down per unit against the anchor schedule, the grid losses the AC stage adds,
and the redispatch cost in two forms:

  extra cost  EC = Σ up·(p_up − p_DA) + Σ down·(p_DA − p_down)
              what the redispatch costs on top of leaving the same energy at the day-ahead price.
              This is how REE's cost of technical constraints is defined: payments and refunds
              measured against the day-ahead market (P.O. 14.4 §17.15, §18.8).
  marginal    Σ c·Δ, the valuation publish_run.py and the results viewer use today.

The two differ by exactly p_DA·(Σ up − Σ down), i.e. the value of the losses (and any other net
energy) at the day-ahead price:  marginal = EC + p_DA·(up − down)  when p_up = p_down = c.

Prices: p_up and p_down are the unit's marginal cost c from gen_dispatch.csv, optionally marked
up per technology with --bids (a CSV with columns fuel,technology,up_markup,down_markup, where
p_up = c·(1+up_markup) and p_down = c·(1−down_markup)). --down-refund da prices every downward
MWh at the day-ahead price instead, which is the phase I rule (a cancelled day-ahead sale).

    python redispatch_realism/settle.py results/2024_by_month/2024-12
    python redispatch_realism/settle.py results/my_run --esios ../spain-model-runs/reference/esios_2024.js
    python redispatch_realism/settle.py results/my_run --bids my_markups.csv --down-refund da

Writes results/<run>/settlement/{hourly,monthly,by_type,hour_of_day}.csv and prints a summary.
With --esios it also prints REE's 2024 figures over the same hours (phases I, II, real time).
It also prints the run's loss share, the value to put in [redispatch].loss_share (step RD2).
"""
import argparse
import json
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

CHUNK = 500_000
SOLVED = {"LOCALLY_SOLVED", "OPTIMAL", "ALMOST_LOCALLY_SOLVED"}
# pseudo-units with no market schedule: load shedding, the slack machine, border injections,
# switchable reactors ([reactors].switchable, reactive power only)
PSEUDO = ("LS_", "SLACK", "XB_", "RX_")
# the results viewer's redispatch groups (viewer.js RD_TYPES)
def rd_type(fuel, tech):
    if fuel == "Hydro" and tech == "pumped_storage":
        return "Pumped storage"
    if fuel == "Hydro":
        return "Hydro"
    if fuel == "Gas":
        return "Gas"
    if fuel in ("Wind", "Solar"):
        return "Wind and solar"
    return "Other"


def anchor_file(rdir, anchor):
    if anchor != "auto":
        return rdir / f"{anchor}_dispatch.csv"
    for s in ("bal", "cid", "id3", "id2", "da"):
        if (rdir / f"{s}_dispatch.csv").exists():
            return rdir / f"{s}_dispatch.csv"
    raise SystemExit(f"{rdir}: no market dispatch file to anchor to")


def load_bids(path):
    if path is None:
        return {}
    b = pd.read_csv(path)
    return {(r.fuel, r.technology): (float(r.up_markup), float(r.down_markup)) for r in b.itertuples(index=False)}


def read_anchor(path, keys):
    """MW per (date, hour, unit) of the anchor schedule, for the solved hours only."""
    parts = []
    for ch in pd.read_csv(path, chunksize=CHUNK, usecols=["date", "hour", "gen_id", "dispatch_mw"]):
        ch = ch.rename(columns={"gen_id": "unit_name", "dispatch_mw": "anchor_mw"})
        parts.append(ch.merge(keys, on=["date", "hour"]))
    return pd.concat(parts, ignore_index=True)


STORAGE = {("Hydro", "reservoir"), ("Hydro", "pumped_storage"), ("Battery", "Li-Ion")}


def phase1_in_chain(rdir):
    """True if phase I ran inside the market chain ([redispatch.phase1].in_chain in the run's config)."""
    f = rdir / "config_used.toml"
    if not f.exists():
        return False
    with open(f, "rb") as fh:
        c = tomllib.load(fh)
    return bool(c.get("redispatch", {}).get("phase1", {}).get("in_chain", False))


def settle(rdir, anchor="auto", bids=None, down_refund="bid", storage_at_da=False):
    summ = pd.read_csv(rdir / "summary.csv")
    summ = summ[summ.status.isin(SOLVED)]
    keys = summ[["date", "hour"]]
    prices = pd.read_csv(rdir / "market_prices.csv")
    pda = prices[prices.stage == "DA"][["date", "hour", "price_eur_mwh"]].rename(columns={"price_eur_mwh": "p_da"})
    anc = read_anchor(anchor_file(rdir, anchor), keys)
    # RD8: real time is measured from the balancing schedule plus phase I/II's changes
    # (rd_phase1.csv), as REE's real-time constraints start from the programme phase I left.
    # With phase I inside the market chain the balancing schedule already holds them.
    p1f = rdir / "rd_phase1.csv"
    if p1f.exists() and not phase1_in_chain(rdir):
        p1 = pd.read_csv(p1f).assign(delta=lambda d: d.phase1_mw - d.da_mw)[["date", "hour", "unit", "delta"]]
        p1 = p1.rename(columns={"unit": "unit_name"})
        anc = anc.merge(p1, on=["date", "hour", "unit_name"], how="outer")
        anc["anchor_mw"] = anc.anchor_mw.fillna(0.0) + anc.delta.fillna(0.0)
        anc = anc.drop(columns="delta").merge(keys, on=["date", "hour"])
    markups = load_bids(bids)

    rows = []
    for ch in pd.read_csv(rdir / "gen_dispatch.csv", chunksize=CHUNK,
                          usecols=["date", "hour", "unit_name", "fuel", "technology", "dispatch_mw", "cost_eur_per_mwh"]):
        ch = ch.merge(keys, on=["date", "hour"])
        ch = ch[~ch.unit_name.str.startswith(PSEUDO)]
        if ch.empty:
            continue
        ch = ch.merge(anc, on=["date", "hour", "unit_name"], how="left").merge(pda, on=["date", "hour"], how="left")
        # a unit with no anchor row (e.g. an island unit kept out of the market) was scheduled at 0
        ch["anchor_mw"] = ch.anchor_mw.fillna(0.0)
        d = ch.dispatch_mw - ch.anchor_mw
        up, dn = d.clip(lower=0), (-d).clip(lower=0)
        c = ch.cost_eur_per_mwh
        if storage_at_da:                   # RD11: storage bids its opportunity cost, the day-ahead price
            c = c.where(~pd.Series([k in STORAGE for k in zip(ch.fuel, ch.technology)], index=ch.index), ch.p_da)
        mk = [markups.get(k, (0.0, 0.0)) for k in zip(ch.fuel, ch.technology)]
        mu = np.array([m[0] for m in mk]); md = np.array([m[1] for m in mk])
        p_up = c * (1 + mu)
        # "da" phase I refund; "bid_da" phase II's down bids as a share of the day-ahead price
        # (fit_phase2_bids.py, RD12); "bid" a cost-based down bid
        p_dn = ch.p_da if down_refund == "da" else (ch.p_da * (1 - md) if down_refund == "bid_da" else c * (1 - md))
        ch = ch.assign(up=up, down=dn, ec=up * (p_up - ch.p_da) + dn * (ch.p_da - p_dn), marginal=c * d,
                       type=[rd_type(f, t) for f, t in zip(ch.fuel, ch.technology)])
        rows.append(ch[["date", "hour", "type", "up", "down", "ec", "marginal", "p_da"]])
    u = pd.concat(rows, ignore_index=True)

    hourly = u.groupby(["date", "hour"]).agg(up_mwh=("up", "sum"), down_mwh=("down", "sum"),
                                              extra_cost_eur=("ec", "sum"), marginal_eur=("marginal", "sum"),
                                              p_da=("p_da", "first")).reset_index()
    # start-ups (step RD9, rd_startups.csv): REE pays a started unit's start-up cost (P.O. 3.2 Annex I)
    su_file = rdir / "rd_startups.csv"
    if su_file.exists():
        su = pd.read_csv(su_file).groupby(["date", "hour"]).agg(starts=("unit", "size"),
                                                                 startup_eur=("start_cost_eur", "sum")).reset_index()
        hourly = hourly.merge(su, on=["date", "hour"], how="left").fillna({"starts": 0, "startup_eur": 0.0})
    else:
        hourly["starts"], hourly["startup_eur"] = 0, 0.0
    hourly["extra_cost_eur"] += hourly.startup_eur
    hourly = hourly.merge(summ[["date", "hour", "total_load_mw", "mismatch_mw"]], on=["date", "hour"])
    hourly = hourly.rename(columns={"mismatch_mw": "losses_mw", "total_load_mw": "load_mw"})
    hourly["net_up_mwh"] = hourly.up_mwh - hourly.down_mwh
    by_type = u.groupby("type")[["up", "down", "ec", "marginal"]].sum().div([1e3, 1e3, 1e6, 1e6])
    by_type.columns = ["up_gwh", "down_gwh", "extra_cost_meur", "marginal_meur"]
    hourly["month"] = hourly.date.str[:7]
    monthly = hourly.groupby("month").agg(up_gwh=("up_mwh", "sum"), down_gwh=("down_mwh", "sum"),
                                          losses_gwh=("losses_mw", "sum"), extra_cost_meur=("extra_cost_eur", "sum"),
                                          marginal_meur=("marginal_eur", "sum"), starts=("starts", "sum"),
                                          hours=("hour", "size"))
    monthly[["up_gwh", "down_gwh", "losses_gwh"]] /= 1e3
    monthly[["extra_cost_meur", "marginal_meur"]] /= 1e6
    hod = hourly.groupby("hour")[["up_mwh", "down_mwh", "losses_mw"]].mean()
    return hourly, monthly, by_type, hod


def ree_same_hours(esios_js, hourly):
    """REE's 2024 redispatch over the same hours, pooled as the results viewer pools it."""
    t = Path(esios_js).read_text(encoding="utf-8")
    e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    day_i = {d: i for i, d in enumerate(e["days"])}
    idx = np.array([day_i[d] * 24 + h for d, h in zip(hourly.date, hourly.hour) if d in day_i])
    s = lambda k: float(np.nansum(np.array([np.nan if x is None else x for x in e["series"][k]], float)[idx]))
    ph1 = (s("rt1_up"), s("rt1_down"), s("rt1_up_cost") - s("rt1_down_cost"))
    ph2 = (s("rt2_up"), s("rt2_down"), s("rt2_up_cost") - s("rt2_down_cost"))
    rt = (s("rtr_up"), s("rtr_down"), s("rtr_up_cost") + s("rtr_down_cost"))
    return {"Phase I": ph1, "Phase II": ph2, "Real time": rt}, len(idx)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path, help="results/<run> folder")
    ap.add_argument("--anchor", default="auto", help="anchor schedule: bal, cid, id3, id2, da (default: last market stage present)")
    ap.add_argument("--bids", type=Path, help="CSV fuel,technology,up_markup,down_markup (default: marginal cost, no mark-up)")
    ap.add_argument("--down-refund", choices=["bid", "da", "bid_da"], default="bid",
                    help="price of downward energy: the unit's down bid (real time, phase II), the day-ahead price "
                         "(phase I), or bid_da: day-ahead × (1 − down_markup), phase II's bids (RD12)")
    ap.add_argument("--storage-at-da", action="store_true",
                    help="price reservoir/pumped hydro and batteries at the day-ahead price (RD11, objective = \"ree\")")
    ap.add_argument("--esios", type=Path, help="spain-model-runs/reference/esios_2024.js, to print REE over the same hours")
    ap.add_argument("--out", type=Path, help="output folder (default: <run>/settlement)")
    a = ap.parse_args()

    hourly, monthly, by_type, hod = settle(a.run, a.anchor, a.bids, a.down_refund, a.storage_at_da)
    out = a.out or a.run / "settlement"
    out.mkdir(parents=True, exist_ok=True)
    hourly.to_csv(out / "hourly.csv", index=False)
    monthly.round(3).to_csv(out / "monthly.csv")
    by_type.round(3).to_csv(out / "by_type.csv")
    hod.round(1).to_csv(out / "hour_of_day.csv")

    up, dn, loss = hourly.up_mwh.sum() / 1e3, hourly.down_mwh.sum() / 1e3, hourly.losses_mw.sum() / 1e3
    ec, mg = hourly.extra_cost_eur.sum() / 1e6, hourly.marginal_eur.sum() / 1e6
    print(f"\n{a.run}  ·  {len(hourly)} solved hours  ·  anchor {anchor_file(a.run, a.anchor).name}"
          f"  ·  down priced at {dict(da='day-ahead price', bid='down bid', bid_da='phase II bids (share of day-ahead)')[a.down_refund]}"
          f"  ·  {'mark-ups from ' + str(a.bids) if a.bids else 'no mark-ups'}")
    print(f"  turned up        {up:9.1f} GWh")
    print(f"  turned down      {dn:9.1f} GWh")
    print(f"  grid losses      {loss:9.1f} GWh   (up − down = {up - dn:.1f} GWh)")
    print(f"  extra cost       {ec:9.2f} M€    = {1e3 * ec / up if up else float('nan'):.1f} €/MWh up"
          f"   (of which start-ups {hourly.startup_eur.sum() / 1e6:.2f} M€, {int(hourly.starts.sum())} starts)")
    print(f"  marginal value   {mg:9.2f} M€    (the viewer's figure; the difference is the net energy at the day-ahead price)")
    print(f"  loss share       {hourly.losses_mw.sum() / hourly.load_mw.sum():.4f}   → [redispatch].loss_share for step RD2")
    print("\n  by type (GWh up / down, extra cost M€):")
    for t, r in by_type.iterrows():
        print(f"    {t:16s} {r.up_gwh:8.1f} {r.down_gwh:8.1f} {r.extra_cost_meur:9.2f}")
    if a.esios:
        ree, n = ree_same_hours(a.esios, hourly)
        print(f"\n  REE over the same {n} hours (GWh up / down, extra cost M€):")
        for k, (u, d, c) in ree.items():
            print(f"    {k:16s} {u / 1e3:8.1f} {d / 1e3:8.1f} {c / 1e6:9.2f}")
        tot = [sum(v[i] for v in ree.values()) for i in range(3)]
        print(f"    {'total':16s} {tot[0] / 1e3:8.1f} {tot[1] / 1e3:8.1f} {tot[2] / 1e6:9.2f}")
    print(f"\n  written to {out}")


if __name__ == "__main__":
    main()
