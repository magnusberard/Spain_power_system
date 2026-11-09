"""Voltage-zone need rules for 2035: three candidates fitted on 2024, tested out of year on 2023 (method fixed and committed
before any 2023 result is seen, 9 Nov 2026).

What a rule gives: per voltage zone and hour, a requirement "at least n synchronous units online" (RD5). The model then
starts units where its own day-ahead schedule has fewer than n. So every rule is scored on the units it would make the
model raise, given the day-ahead schedule:  raised(zone, h) = max(0, n_required - n_scheduled).

Zones: the 2024 zones (data/voltage_zone_units.csv), fixed. REE's truth per year, as build_voltage_zones.py builds it:
  n_raised(zone, h)   zone units REE raised in phase I for voltage (I90 UPO*, up, causes SOT/COT)
  n_online(zone, h)   zone units online in REE's PDVP (> 1 MW) in those hours
  n_sched(zone, h)    zone units online BEFORE phase I: PDVP minus phase I up (all causes) > 1 MW (REE's day-ahead state)
Load (both years the same source, REE's D+1 forecasts, e·sios): demand 1775; wind 1777, solar PV 1779 + solar thermal 543.

Candidates (each fitted on all of 2024):
  R0  the current rule: per zone and national-LOAD decile (edges in MW from the fit year), p_need = share of the bin's
      hours with a REE voltage need in the zone, n = median n_online in those hours; required if p_need >= 0.4
      (threshold chosen on Jan-Jun 2024 when the rule was built). Refitted here on the e·sios demand forecast (the rule as
      built used OMIE physical generation, which has no 2023 file here).
  R1  the same with NET load (demand - wind - solar).
  C   the alternative: a constant requirement per zone, n_z = median n_online over the zone's 2024 need hours, in every
      hour; the need then arises only where the day-ahead schedule has fewer than n_z units (REE's actual trigger).

Scores on 2023 (and, for reference, in sample on 2024):
  corr    hourly correlation of Spain's total units raised, rule vs REE      (primary)
  ratio   units raised per hour, rule / REE                                  (secondary: |log ratio| smaller is better)
  daily   daily correlation of the same totals
  prec / recall   zone-hours with raised > 0, rule vs REE
Choice: the best 2023 corr; if two are within 0.02, the one with |log ratio| closer to 0; if still tied, the simpler (C, R0, R1).

    python redispatch_realism/zone_rule_test_2023.py
"""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import PATHS, _esios                                   # noqa: E402
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
I90 = {2024: D / "i90", 2023: D / "i90_2023"}
P_MIN, ONLINE = 0.4, 1.0


def truth(year, zu, xw):
    ph = pd.read_csv(I90[year] / "i90_tc_phase.csv.gz")
    up = ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")].copy()
    up["unit"] = up["Unidad de Programación"].str.strip().map(xw)
    up = up.dropna(subset=["unit"]).merge(zu, left_on="unit", right_on="unit_id")
    volt = up[up["Tipo Restricción"].isin(["SOT", "COT"])]
    raised = volt.groupby(["date", "hour", "zone"]).unit.nunique().rename("n_raised")
    up_mwh = up.groupby(["date", "hour", "unit"]).mwh.sum()
    pv = pd.read_csv(I90[year] / "i90_pdvp.csv.gz")
    pv["unit"] = pv["Unidad de Programación"].str.strip().map(xw)
    pv = pv.dropna(subset=["unit"]).groupby(["date", "hour", "unit"], as_index=False).mwh.sum().merge(zu, left_on="unit", right_on="unit_id")
    pv["before"] = pv.mwh - [up_mwh.get(k, 0.0) for k in zip(pv.date, pv.hour, pv.unit)]
    online = pv[pv.mwh > ONLINE].groupby(["date", "hour", "zone"]).unit.nunique().rename("n_online")
    sched = pv[pv.before > ONLINE].groupby(["date", "hour", "zone"]).unit.nunique().rename("n_sched")
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    hours = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "hour": idx.hour})
    grid = hours.merge(pd.DataFrame({"zone": sorted(zu.zone.unique())}), how="cross")
    t = grid.merge(raised.reset_index(), how="left").merge(online.reset_index(), how="left").merge(sched.reset_index(), how="left")
    t = t.fillna({"n_raised": 0, "n_online": 0, "n_sched": 0})
    p = PATHS[year]
    dem, wind = _esios(p["fc"], 1775, idx), _esios(p["fc"], 1777, idx)
    sol = _esios(p["fc"], 1779, idx).fillna(0) + _esios(p["fc"], 543, idx).fillna(0)
    ld = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "hour": idx.hour, "load": dem.values, "net": (dem - wind.fillna(0) - sol).values})
    return t.merge(ld, on=["date", "hour"], how="left")


def fit_bins(t, col):
    edges = np.nanquantile(t.drop_duplicates(["date", "hour"])[col], np.linspace(0, 1, 11))
    edges[0], edges[-1] = -np.inf, np.inf
    t = t.assign(bin=np.digitize(t[col], edges[1:-1]))
    need = t.n_raised > 0
    g = t.assign(need=need).groupby(["zone", "bin"])
    rule = pd.DataFrame({"p_need": g.need.mean(), "n": t[need].groupby(["zone", "bin"]).n_online.median()}).reset_index()
    return edges, rule.fillna({"n": 0})


def apply_bins(t, col, edges, rule):
    t = t.assign(bin=np.digitize(t[col], edges[1:-1])).merge(rule, on=["zone", "bin"], how="left")
    req = np.where(t.p_need.fillna(0) >= P_MIN, t.n.fillna(0), 0)
    return np.maximum(0, req - t.n_sched)


def scores(t, pred):
    t = t.assign(pred=pred)
    h = t.groupby(["date", "hour"])[["pred", "n_raised"]].sum()
    d = h.groupby(level=0).sum()
    hit = (t.pred > 0) & (t.n_raised > 0)
    return dict(corr=round(h.pred.corr(h.n_raised), 3), ratio=round(h.pred.sum() / h.n_raised.sum(), 2),
                daily=round(d.pred.corr(d.n_raised), 3), prec=round(hit.sum() / max(1, (t.pred > 0).sum()), 2),
                recall=round(hit.sum() / max(1, (t.n_raised > 0).sum()), 2), per_h=round(h.pred.mean(), 2), ree_per_h=round(h.n_raised.mean(), 2))


def main():
    zu = pd.read_csv(HERE / "data" / "voltage_zone_units.csv")[["zone", "unit_id"]]
    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv").dropna(subset=["model_unit_id"])
    xw = dict(zip(x.ree_unit.str.strip(), x.model_unit_id))
    t24, t23 = truth(2024, zu, xw), truth(2023, zu, xw)
    print(f"REE voltage zone-hours with a raise: 2024 {int((t24.n_raised > 0).sum())}, 2023 {int((t23.n_raised > 0).sum())}; "
          f"units raised per hour: 2024 {t24.groupby(['date','hour']).n_raised.sum().mean():.2f}, 2023 {t23.groupby(['date','hour']).n_raised.sum().mean():.2f}")
    rows = {}
    for name, col in (("R0 load", "load"), ("R1 net load", "net")):
        edges, rule = fit_bins(t24, col)
        rows[name] = {"2024 (fit)": scores(t24, apply_bins(t24, col, edges, rule)), "2023 (test)": scores(t23, apply_bins(t23, col, edges, rule))}
    nz = t24[t24.n_raised > 0].groupby("zone").n_online.median()
    predC = lambda t: np.maximum(0, t.zone.map(nz).fillna(0) - t.n_sched)
    rows["C scheduled units"] = {"2024 (fit)": scores(t24, predC(t24)), "2023 (test)": scores(t23, predC(t23))}
    out = pd.DataFrame({(r, y): s for r, v in rows.items() for y, s in v.items()}).T
    print(out.to_string())
    test = out.xs("2023 (test)", level=1)
    test = test.assign(gap=np.abs(np.log(test.ratio.astype(float))))
    best = test.corr.astype(float).max()
    close = test[test.corr.astype(float) >= best - 0.02].sort_values("gap")
    order = {"C scheduled units": 0, "R0 load": 1, "R1 net load": 2}
    close = close.assign(o=[order[i] for i in close.index]).sort_values(["gap", "o"])
    print(f"\nchosen (rule fixed beforehand): {close.index[0]}")
    out.to_csv(HERE / "data" / "zone_rule_test_2023.csv")


if __name__ == "__main__":
    main()
