"""E2, additional test chosen after the others (4 Nov, fixed before running): CCGT + coal + pumped storage, no hydro.

Available reserve = running CCGT/coal headroom + running pumped-storage turbine headroom + pumping that can be
stopped; no free parameter. Estimation on January-June only decides whether the aFRR band is in the requirement.

Based on e2_estimate_h.py:

Structure (P.O. 1.5 requirement, P.O. 3.2 remedy; the trigger is not specified, so one share is estimated):
    need = max(0, requirement - thermal headroom - h * hydro headroom)
    requirement  = REE's mFRR requirement (e·sios 1788) [+ assigned aFRR band (632)]
                   + P.O. 1.5 §4.4 gaps of the after-intraday programme (PHFC) against REE's D+1 forecasts
    headrooms    = running units in the per-unit PHFC programme (I90DIA36): CCGT + coal / reservoir hydro,
                   capacity - programmed output
Estimation, January-June only: h in 0, 0.05, ..., 1 and the variant (with / without aFRR), by the highest hourly
correlation with REE's identified need (e·sios 1880); ties: volume closest to REE's.
Test, July-December only, on the marks set before the E2 tests: >= 70 % of REE's need hours,
hourly correlation >= 0.5, volume 0.5-2x.

    python redispatch_realism/e2_estimate_h.py
"""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
HERE = Path(__file__).resolve().parent
idx = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")

def esios(path, ind):
    f = pd.read_csv(path); f = f[f.indicator == ind].copy()
    f["t"] = pd.to_datetime(f.datetime_utc).dt.tz_convert("Europe/Madrid").dt.tz_localize(None)
    s = f.set_index("t").value
    return s[~s.index.duplicated()].resample("h").mean().reindex(idx)

FC, RS, PH = (D / "forecasts" / "esios_forecasts_2024.csv.gz", D / "forecasts" / "reserve" / "esios_reserve_2024.csv.gz",
              D / "forecasts" / "phfc" / "esios_phfc_2024.csv.gz")
need = esios(RS, 1880).fillna(0)
tert, sec = esios(FC, 1788).ffill(), esios(RS, 632).ffill()
supp = ((esios(FC, 1775) - esios(PH, 10279)).clip(lower=0)
        + (esios(PH, 10281) - esios(FC, 1777)).clip(lower=0)
        + (esios(PH, 1413).fillna(0) + esios(PH, 1414).fillna(0) - esios(FC, 1779) - esios(FC, 543).fillna(0)).clip(lower=0))

u = pd.read_csv(D / "i90" / "i90_phfc.csv.gz", encoding="utf-8", encoding_errors="replace").iloc[:, [0, 1, 3, 4]]
u.columns = ["date", "unit", "hour", "mwh"]
u = u.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
t = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
t["ree_max_mw"] = pd.to_numeric(t.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
u = u.merge(t[["ree_unit", "group", "ree_max_mw"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")
def headroom(groups):
    run = u[u.group.isin(groups) & (u.mwh > 1)]
    return (run.ree_max_mw - run.mwh).clip(lower=0).groupby(run.t).sum().reindex(idx).fillna(0)
head_t = headroom(["CCGT", "coal"])
pump = -u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum().reindex(idx).fillna(0)
head_h = headroom(["pumped storage (turbine)"]) + pump          # pumped storage: turbine headroom + stoppable pumping
print("mean MW: CCGT/coal headroom", round(head_t.mean()), "| pumped storage", round(head_h.mean()))

ok = need.notna() & supp.notna() & (u.groupby("t").size().reindex(idx).fillna(0) > 0)
train = ok & (idx < "2024-07-01")
test = ok & (idx >= "2024-07-01")

def model(h, with_afrr):
    req = tert + supp + (sec if with_afrr else 0)
    return (req - head_t - h * head_h).clip(lower=0)

def score(x, m):
    x, y, hit = x[m], need[m], need[m] > 0
    s = x > 0
    return dict(corr=x.corr(y), recall=(s & hit).sum() / hit.sum(), precision=(s & hit).sum() / max(1, s.sum()),
                volume=x.sum() / y.sum(), hours=int(s.sum()), need_hours=int(hit.sum()),
                corr_day=pd.DataFrame({"x": x, "y": y}).resample("D").mean().pipe(lambda d: d.x.corr(d.y)))

grid = []
for wa in (True, False):
    for h in (1.0,):                                              # pumped storage counted in full
        sc = score(model(h, wa), train)
        grid.append(dict(h=h, aFRR=wa, **sc))
g = pd.DataFrame(grid)
g["vol_gap"] = (np.log(g.volume.clip(lower=1e-9))).abs()
best = g.sort_values(["corr", "vol_gap"], ascending=[False, True]).iloc[0]
print("Estimation (Jan-Jun), top 8 by hourly correlation:")
print(g.sort_values("corr", ascending=False).head(8).round(3).to_string(index=False))
print(f"\nchosen: h = {best.h}, aFRR band {'in' if best.aFRR else 'out'}")

res = score(model(best.h, bool(best.aFRR)), test)
marks = {"need hours caught >= 70 %": res["recall"] >= 0.7, "hourly corr >= 0.5": res["corr"] >= 0.5,
         "volume 0.5-2x": 0.5 <= res["volume"] <= 2}
print("\nTest (Jul-Dec, not used in the estimate):")
print({k: round(v, 3) if isinstance(v, float) else v for k, v in res.items()})
for k, v in marks.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("RESULT (additional test, chosen after the others):", "PASS" if all(marks.values()) else "FAIL")
ref = score(model(0.0, bool(best.aFRR)), test)
print(f"\nfor reference, h = 0 on Jul-Dec: corr {ref['corr']:.2f}, recall {ref['recall']:.2f}, volume {ref['volume']:.2f}")
