"""Compare a run's redispatch with REE's, day by day: volume, cost, technology mix and units.

Model: phase I/II from rd_phase1_summary.csv / rd_phase1.csv (RD8), real time settled by
settle.py with the run's own pricing rule. REE: e·sios national totals per phase (as the results
viewer pools them) and I90 per unit (phase I upward units, mapped to model units with
ree_unit_crosswalk.csv).

    python redispatch_realism/compare_ree.py results/W1 results/W2 --bids bids.csv
    python redispatch_realism/compare_ree.py results/run --bids bids.csv --storage-at-da --out report.csv
    python redispatch_realism/compare_ree.py <solstorm out folder> ...   # its day subfolders

Prints one row per day and a total; --out writes the table.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

import settle

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def ree_esios(path, days):
    t = Path(path).read_text(encoding="utf-8")
    e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    ix = {d: i for i, d in enumerate(e["days"])}
    s = {k: np.array([np.nan if v is None else v for v in vals], float) for k, vals in e["series"].items()}
    rows = []
    for d in days:
        sl = slice(ix[d] * 24, ix[d] * 24 + 24)
        g = lambda k: float(np.nansum(s[k][sl]))
        rows.append(dict(date=d,
                         ree_ph1_up_gwh=g("rt1_up") / 1e3, ree_ph2_down_gwh=g("rt2_down") / 1e3,
                         ree_rt_up_gwh=g("rtr_up") / 1e3,
                         ree_ph12_meur=(g("rt1_up_cost") - g("rt1_down_cost") + g("rt2_up_cost") - g("rt2_down_cost")) / 1e6,
                         ree_rt_meur=(g("rtr_up_cost") + g("rtr_down_cost")) / 1e6))
    return pd.DataFrame(rows)


def ree_units(i90, days):
    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv")[["ree_unit", "model_unit_id"]]
    ph = pd.read_csv(i90 / "i90_tc_phase.csv.gz")
    ph = ph[ph.date.isin(days) & ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")]
    ph = ph.merge(x, left_on="Unidad de Programación", right_on="ree_unit", how="left")
    return ph.groupby("date").agg(ree_units=("ree_unit", "nunique"),
                                  ree_model_units=("model_unit_id", lambda s: set(s.dropna()))).reset_index(), ph


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--bids", type=Path)
    ap.add_argument("--storage-at-da", action="store_true")
    ap.add_argument("--esios", type=Path, default=REPO.parent / "spain-model-runs" / "reference" / "esios_2024.js")
    ap.add_argument("--i90", type=Path, default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    # a parent folder (a Solstorm day-by-day run) stands for its finished day folders
    runs = []
    for r in a.runs:
        if (r / "summary.csv").exists():
            runs.append(r)
        else:
            runs += sorted(p for p in r.iterdir() if (p / "summary.csv").exists())
    days_rows = []
    for run in runs:
        hourly, *_ = settle.settle(run, bids=a.bids, down_refund="da", storage_at_da=a.storage_at_da)
        rt = hourly.groupby("date").agg(rt_up_gwh=("up_mwh", lambda v: v.sum() / 1e3),
                                        rt_down_gwh=("down_mwh", lambda v: v.sum() / 1e3),
                                        rt_meur=("extra_cost_eur", lambda v: v.sum() / 1e6),
                                        rt_starts=("starts", "sum"),
                                        solved_h=("hour", "size"))
        p1f = run / "rd_phase1_summary.csv"
        if p1f.exists():
            p1 = pd.read_csv(p1f).groupby("date").agg(ph1_up_gwh=("up_mwh", lambda v: v.sum() / 1e3),
                                                      ph1_starts=("starts", "sum"),
                                                      ph1_meur=("extra_cost_eur", lambda v: v.sum() / 1e6),
                                                      ph1_units_per_h=("units_committed", "mean"))
            com = pd.read_csv(run / "rd_phase1.csv")
            com = com[com.committed].groupby("date").unit.apply(set).rename("ph1_units")
            rt = rt.join(p1, how="left").join(com, how="left")
        days_rows.append(rt.reset_index())
    m = pd.concat(days_rows, ignore_index=True).sort_values("date")
    days = m.date.tolist()
    r = ree_esios(a.esios, days)
    u, ph = ree_units(a.i90, days)
    t = m.merge(r, on="date").merge(u, on="date", how="left")
    t["ree_units_per_h"] = [ph[ph.date == d].groupby("hour").ree_unit.nunique().mean() for d in t.date]
    t["ph1_units_matching_ree"] = [len((p if isinstance(p, set) else set()) & q) for p, q in zip(t.get("ph1_units", [set()] * len(t)), t.ree_model_units)]
    t["model_up_gwh"] = t.rt_up_gwh + t.get("ph1_up_gwh", 0).fillna(0)
    t["ree_up_gwh"] = t.ree_ph1_up_gwh + t.ree_rt_up_gwh
    t["model_meur"] = t.rt_meur + t.get("ph1_meur", 0).fillna(0)
    t["ree_meur"] = t.ree_ph12_meur + t.ree_rt_meur
    cols = ["date", "solved_h", "model_up_gwh", "ree_up_gwh", "model_meur", "ree_meur",
            "ph1_up_gwh", "ree_ph1_up_gwh", "ph1_units_per_h", "ree_units_per_h", "ph1_units_matching_ree", "ree_units",
            "rt_up_gwh", "ree_rt_up_gwh", "rt_starts"]
    out = t[[c for c in cols if c in t.columns]].copy()
    tot = out.select_dtypes("number").sum()
    for c in ("ph1_units_per_h", "ree_units_per_h"):
        if c in out:
            tot[c] = out[c].mean()
    out = pd.concat([out, pd.DataFrame([{"date": "total", **tot.to_dict()}])], ignore_index=True)
    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(out.round(2).to_string(index=False))
    print(f"\nmodel / REE: volume {tot.model_up_gwh / tot.ree_up_gwh:.0%}, cost {tot.model_meur / tot.ree_meur:.0%}"
          + (f", phase I volume {tot.ph1_up_gwh / tot.ree_ph1_up_gwh:.0%}" if "ph1_up_gwh" in tot else ""))
    if a.out:
        out.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
