"""E2 step B (fixed 4 Nov, before running): REE's reserve need as an episode, not an hour.

Window rule on top of the best single-hour shortfall (e2_test_ccgt_pumped.py: mFRR + aFRR + §4.4 gaps against PHFC
- CCGT/coal and pumped-storage headroom):
    need_t = max(shortfall_k for k in [t - (H - 1), t + L])
  L  look-ahead = median declared HOT start time to technical minimum of CCGTs for real time (I90DIA29,
     P.O. 3.2 §3.5.1), sampled on the 15th of each month of 2024, rounded up to whole hours
  H  hold       = median length of the consecutive blocks REE ran its RSI-started units in 2024 (I90 real-time
     constraints, cause RSI): how long REE's remedy lasts, not fitted to the target
Judged on July-December against REE's identified need (e·sios 1880) on the marks set before the E2 tests:
>= 70 % of the need hours, hourly correlation >= 0.5, volume 0.5-2x. Also printed: the single-hour rule.

    python redispatch_realism/e2_step_b_window.py
"""
import math, os, sys, zipfile
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_i90, xlrd
idx = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")
tech = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
ccgt_units = set(tech[tech.group == "CCGT"].ree_unit.astype(str).str.strip())

# L: declared hot start times of CCGTs for real time (I90DIA29), 12 sample days
zdir = D / "i90" / "zips_dia29"; zdir.mkdir(parents=True, exist_ok=True)
rows = []
for m in range(1, 13):
    d = f"2024-{m:02d}-15"
    z, raw = fetch_i90.fetch(d, zdir)
    sh = xlrd.open_workbook(file_contents=raw, on_demand=True).sheet_by_name("I90DIA29")
    head = [str(c).strip() for c in sh.row_values(1)]
    for r in range(2, sh.nrows):
        v = dict(zip(head, sh.row_values(r)))
        rows.append(dict(date=d, unit=str(v.get("Unidad de Programación", "")).strip(), market=v.get("Mercado"),
                         mode=v.get("Modo"), hot=pd.to_numeric(v.get(head[4]), errors="coerce")))
lt = pd.DataFrame(rows)
lt_rt = lt[(lt.market == "Tiempo Real") & lt.unit.isin(ccgt_units) & lt.hot.notna()]
per_unit = lt_rt.groupby("unit").hot.median()
L = math.ceil(per_unit.median() / 60)
print(f"L: CCGT hot start time for real time, {len(per_unit)} units: median {per_unit.median():.0f} min "
      f"(quartiles {per_unit.quantile(.25):.0f}-{per_unit.quantile(.75):.0f}) -> L = {L} h")

# H: how long REE ran its RSI-started units (consecutive hours per unit)
r = pd.read_csv(D / "i90" / "i90_tc_realtime.csv.gz", encoding="utf-8", encoding_errors="replace")
r.columns = ["date", "red", "tipo", "sentido", "unit", "tof", "tcalc", "signo", "trestr", "hour", "mwh", "eur"]
rsi = r[(r.sentido == "Subir") & (r.trestr == "RSI") & r.red.str.startswith("Restricciones")].copy()
rsi["t"] = pd.to_datetime(rsi.date) + pd.to_timedelta(rsi.hour, unit="h")
runs = []
for u_, g in rsi.groupby(rsi.unit.str.strip()):
    ts = np.sort(g.t.unique())
    br = np.where(np.diff(ts) != np.timedelta64(1, "h"))[0]
    starts = np.r_[0, br + 1]; ends = np.r_[br, len(ts) - 1]
    runs += list(ends - starts + 1)
runs = np.array(runs)
H = int(np.median(runs))
print(f"H: REE's RSI unit blocks, n={len(runs)}: median {np.median(runs):.0f} h (quartiles "
      f"{np.percentile(runs, 25):.0f}-{np.percentile(runs, 75):.0f}) -> H = {H} h")

# the best single-hour shortfall (as e2_test_ccgt_pumped.py)
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
t = tech.copy(); t["ree_max_mw"] = pd.to_numeric(t.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
u = u.merge(t[["ree_unit", "group", "ree_max_mw"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")
def headroom(groups):
    run = u[u.group.isin(groups) & (u.mwh > 1)]
    return (run.ree_max_mw - run.mwh).clip(lower=0).groupby(run.t).sum().reindex(idx).fillna(0)
pump = -u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum().reindex(idx).fillna(0)
short = (tert + sec + supp - headroom(["CCGT", "coal"]) - headroom(["pumped storage (turbine)"]) - pump).clip(lower=0)
ok = need.notna() & short.notna()
short = short.where(ok, 0)
window = short[::-1].rolling(L + 1, min_periods=1).max()[::-1]          # t .. t+L
window = window.rolling(H, min_periods=1).max()                           # held back to t-(H-1)

def score(x, m):
    x, y, hit = x[m], need[m], need[m] > 0
    s = x > 0
    return dict(corr=round(x.corr(y), 3), corr_day=round(pd.DataFrame({"x": x, "y": y}).resample("D").mean().pipe(lambda d: d.x.corr(d.y)), 3),
                recall=round((s & hit).sum() / hit.sum(), 3), precision=round((s & hit).sum() / max(1, s.sum()), 3),
                volume=round(x.sum() / y.sum(), 3), hours=int(s.sum()), need_hours=int(hit.sum()))
test = ok & (idx >= "2024-07-01")
for name, x in (("single hour (reference)", short), (f"window L={L} h ahead, H={H} h hold", window)):
    print(f"\n{name}, Jul-Dec:", score(x, test))
    print(f"{name}, Jan-Jun:", score(x, ok & (idx < "2024-07-01")))
res = score(window, test)
marks = {"need hours caught >= 70 %": res["recall"] >= 0.7, "hourly corr >= 0.5": res["corr"] >= 0.5,
         "volume 0.5-2x": 0.5 <= res["volume"] <= 2}
for k, v in marks.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("RESULT (step B, window rule, Jul-Dec):", "PASS" if all(marks.values()) else "FAIL")
