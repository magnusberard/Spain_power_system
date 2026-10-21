"""Compare a run's redispatch with REE's, day by day: volume, cost, technology mix and units.

Model: phase I/II from rd_phase1_summary.csv / rd_phase1.csv (RD8), real time settled by
settle.py with the run's own pricing rule. REE: e·sios national totals per phase (as the results
viewer pools them) and I90 per unit (phase I upward units, mapped to model units with
ree_unit_crosswalk.csv).

    python redispatch_realism/compare_ree.py results/W1 results/W2 --bids bids.csv
    python redispatch_realism/compare_ree.py results/run --bids bids.csv --storage-at-da --out report.csv
    python redispatch_realism/compare_ree.py <solstorm out folder> ...   # its day subfolders
    python redispatch_realism/compare_ree.py results/run --bids bids.csv --profile-out prof.csv --zones

Prints one row per day and a total; --out writes the table. Also printed: phase I and phase II
apart (REE's phase II is mostly the down side that takes phase I's energy back), price per MWh
turned up, and REE's phase I by cause (voltage, N-1, distribution, other: e·sios codes CT, SCA,
RTD, the rest). --profile-out writes the average MW turned up per hour of the day, model and REE,
phase I and real time, and prints how well the shapes match. --zones prints phase I starts per
voltage zone (unit-hours started, model vs REE's I90, zones of [redispatch.mustrun]).
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
                         ree_ph1_meur=(g("rt1_up_cost") - g("rt1_down_cost")) / 1e6,
                         ree_ph2_meur=(g("rt2_up_cost") - g("rt2_down_cost")) / 1e6,
                         ree_rt_meur=(g("rtr_up_cost") + g("rtr_down_cost")) / 1e6,
                         # phase I up by cause (e·sios): CT voltage, SCA N-1, RTD distribution, the rest other
                         ree_ph1_volt_gwh=g("rt1_up_ct") / 1e3, ree_ph1_n1_gwh=g("rt1_up_sca") / 1e3,
                         ree_ph1_dist_gwh=g("rt1_up_rtd") / 1e3,
                         ree_ph1_other_gwh=(g("rt1_up_scb") + g("rt1_up_rsi") + g("rt1_up_otros")) / 1e3))
    return pd.DataFrame(rows)


def ree_hourly(path, days):
    """REE's phase I and real-time up per hour (MW) over `days`."""
    t = Path(path).read_text(encoding="utf-8")
    e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
    ix = {d: i for i, d in enumerate(e["days"])}
    rows = []
    for d in days:
        for h in range(24):
            k = ix[d] * 24 + h
            v = lambda s: e["series"][s][k] or 0.0
            rows.append(dict(date=d, hour=h, ree_ph1_up_mw=v("rt1_up"), ree_rt_up_mw=v("rtr_up")))
    return pd.DataFrame(rows)


def zone_table(runs, ph, days):
    """Phase I starts per voltage zone: unit-hours a zone unit was started, model vs REE (I90)."""
    zu = pd.read_csv(HERE / "data" / "voltage_zone_units.csv")[["zone", "unit_id"]]
    com = pd.concat([pd.read_csv(r / "rd_phase1.csv") for r in runs if (r / "rd_phase1.csv").exists()])
    com = com[com.committed & com.date.isin(days)].merge(zu, left_on="unit", right_on="unit_id")
    model = com.groupby("zone").size().rename("model_started_unit_h")
    ree = ph.dropna(subset=["model_unit_id"]).drop_duplicates(["date", "hour", "model_unit_id"])
    ree = ree.merge(zu, left_on="model_unit_id", right_on="unit_id").groupby("zone").size().rename("ree_up_unit_h")
    return pd.concat([model, ree], axis=1).fillna(0).astype(int).sort_values("ree_up_unit_h", ascending=False)


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
    ap.add_argument("--profile-out", type=Path, help="hour-of-day profile of MW turned up, model and REE")
    ap.add_argument("--zones", action="store_true", help="phase I starts per voltage zone, model vs REE")
    a = ap.parse_args()

    # a parent folder (a Solstorm day-by-day run) stands for its finished day folders
    runs = []
    for r in a.runs:
        if (r / "summary.csv").exists():
            runs.append(r)
        else:
            runs += sorted(p for p in r.iterdir() if (p / "summary.csv").exists())
    days_rows = []
    hour_rows = []
    for run in runs:
        hourly, *_ = settle.settle(run, bids=a.bids, down_refund="da", storage_at_da=a.storage_at_da)
        hour_rows.append(hourly[["date", "hour", "up_mwh"]].rename(columns={"up_mwh": "rt_up_mw"}))
        if (run / "rd_phase1_summary.csv").exists():
            p1h = pd.read_csv(run / "rd_phase1_summary.csv")[["date", "hour", "up_mwh"]]
            hour_rows.append(p1h.rename(columns={"up_mwh": "ph1_up_mw"}))
        rt = hourly.groupby("date").agg(rt_up_gwh=("up_mwh", lambda v: v.sum() / 1e3),
                                        rt_down_gwh=("down_mwh", lambda v: v.sum() / 1e3),
                                        rt_meur=("extra_cost_eur", lambda v: v.sum() / 1e6),
                                        rt_starts=("starts", "sum"),
                                        solved_h=("hour", "size"))
        p1f = run / "rd_phase1_summary.csv"
        if p1f.exists():
            p1 = pd.read_csv(p1f).groupby("date").agg(ph1_up_gwh=("up_mwh", lambda v: v.sum() / 1e3),
                                                      ph1_down_gwh=("down_mwh", lambda v: v.sum() / 1e3),
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

    # phase I and phase II apart; price per MWh turned up; REE's phase I by cause
    s = t.select_dtypes("number").sum()
    print(f"price per MWh up: model {1e3 * s.model_meur / s.model_up_gwh:.0f} €/MWh, REE {1e3 * s.ree_meur / s.ree_up_gwh:.0f} €/MWh")
    if "ph1_up_gwh" in s:
        print(f"phase I/II: model up {s.ph1_up_gwh:.1f} / down {s.ph1_down_gwh:.1f} GWh, {s.ph1_meur:.2f} M€ (one stage) | "
              f"REE phase I up {s.ree_ph1_up_gwh:.1f} GWh, {s.ree_ph1_meur:.2f} M€; phase II down {s.ree_ph2_down_gwh:.1f} GWh, "
              f"{s.ree_ph2_meur:.2f} M€")
    print(f"real time: model up {s.rt_up_gwh:.1f} GWh, {s.rt_meur:.2f} M€ | REE up {s.ree_rt_up_gwh:.1f} GWh, {s.ree_rt_meur:.2f} M€")
    cause = {k: s[f"ree_ph1_{k}_gwh"] for k in ("volt", "n1", "dist", "other")}
    print("REE phase I up by cause: " + ", ".join(f"{k} {v:.1f} GWh ({v / max(sum(cause.values()), 1e-9):.0%})"
                                                 for k, v in cause.items())
          + " — the model's phase I has voltage (RD5 zones) and, with n1 on, N-1")

    if a.profile_out:
        mh = pd.concat(hour_rows).groupby(["date", "hour"], as_index=False).sum(numeric_only=True)
        rh = ree_hourly(a.esios, days)
        p = rh.merge(mh, on=["date", "hour"], how="left").fillna(0.0).groupby("hour").mean(numeric_only=True)
        p = p[[c for c in ("ph1_up_mw", "ree_ph1_up_mw", "rt_up_mw", "ree_rt_up_mw") if c in p.columns]].round(1)
        p.to_csv(a.profile_out)
        for m_, r_ in (("ph1_up_mw", "ree_ph1_up_mw"), ("rt_up_mw", "ree_rt_up_mw")):
            if m_ in p and p[m_].std() > 0 and p[r_].std() > 0:
                print(f"hour-of-day shape {m_[:-6]}: correlation with REE {np.corrcoef(p[m_], p[r_])[0, 1]:.2f}, "
                      f"peak model {p[m_].idxmax():02d} h vs REE {p[r_].idxmax():02d} h")
        print(f"profile written to {a.profile_out}")

    if a.zones:
        print("\nphase I per voltage zone (unit-hours; model: started units, REE: units raised in phase I, any cause):")
        print(zone_table(runs, ph, days).to_string())

    if a.out:
        out.to_csv(a.out, index=False)


if __name__ == "__main__":
    main()
