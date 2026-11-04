"""E2, third test: headroom from the per-unit programme after intraday (I90DIA36, PHFC), with and without hydro.

Variants fixed before the data were seen (4 Nov):
  T      running CCGT + coal: capacity - PHFC output
  T+H    + running reservoir hydro (P.O. 1.5 §3.3: tertiary reserve is what all units providing it can deliver)
  T+H+P  + pumped storage: turbine headroom of running turbines, and pumping that can be stopped
Requirement: REE's mFRR requirement (1788) + P.O. 1.5 §4.4 gaps of the PHFC programme against REE's forecasts
(D+1 and H+3), with and without the assigned aFRR band (632). Judged against REE's identified real-time need (1880)
on the marks set before the tests: >= 70 % of the need hours, hourly correlation >= 0.5, volume 0.5-2x.

    python redispatch_realism/e2_analysis_hydro.py
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
st_fc = esios(FC, 543).fillna(0)
ph_dem, ph_wind = esios(PH, 10279), esios(PH, 10281)
ph_sol = esios(PH, 1413).fillna(0) + esios(PH, 1414).fillna(0)
fc = {"H3": (esios(FC, 1776), esios(FC, 1778), esios(FC, 1780)), "D1": (esios(FC, 1775), esios(FC, 1777), esios(FC, 1779))}

u = pd.read_csv(D / "i90" / "i90_phfc.csv.gz", encoding="utf-8", encoding_errors="replace")
u = u.iloc[:, [0, 1, 3, 4]]                      # date, unit, hour, mwh (DST days add "02-03a/b" columns)
u.columns = ["date", "unit", "hour", "mwh"]
u = u.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
t = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
t["ree_max_mw"] = pd.to_numeric(t.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
u = u.merge(t[["ree_unit", "group", "ree_max_mw"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")
print("PHFC unit-hours", len(u), "| days", u.date.nunique(), "| units by group:", u.groupby("group").unit.nunique().to_dict())

def headroom(groups, pumping=False):
    run = u[u.group.isin(groups) & (u.mwh > 1)]
    h = (run.ree_max_mw - run.mwh).clip(lower=0).groupby(run.t).sum()
    if pumping:                                            # pumping in the programme (negative) can be stopped
        h = h.add(-u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum(), fill_value=0)
    return h.reindex(idx).fillna(0)

TH = ["CCGT", "coal"]
H = {"T": headroom(TH), "T+H": headroom(TH + ["hydro"]),
     "T+H+P": headroom(TH + ["hydro", "pumped storage (turbine)"], pumping=True)}

ok = need.notna() & ph_dem.notna() & ph_wind.notna() & (u.groupby("t").size().reindex(idx).fillna(0) > 0)
hit = need > 0
def judge(name, x):
    x, y, h = x[ok], need[ok], hit[ok]
    s = x > 0
    d = pd.DataFrame({"x": x, "y": y}).resample("D").mean()
    rec, prec, vol = (s & h).sum() / h.sum(), (s & h).sum() / max(1, s.sum()), x.sum() / y.sum()
    marks = "PASS" if rec >= 0.7 and x.corr(y) >= 0.5 and 0.5 <= vol <= 2 else "fail"
    return dict(signal=name, corr_h=x.corr(y), corr_day=d.x.corr(d.y), hours=int(s.sum()), recall=rec, precision=prec,
                volume=vol, marks=marks)

rows = []
for tag, (fd, fw, fs) in fc.items():
    supp = (fd - ph_dem).clip(lower=0) + (ph_wind - fw).clip(lower=0) + (ph_sol - (fs + st_fc)).clip(lower=0)
    for hn, hv in H.items():
        rows.append(judge(f"{tag} | headroom {hn} | mFRR + aFRR + §4.4", (tert + sec + supp - hv).clip(lower=0)))
        rows.append(judge(f"{tag} | headroom {hn} | mFRR + §4.4", (tert + supp - hv).clip(lower=0)))
r = pd.DataFrame(rows).set_index("signal")
print(r.round(2).to_string())
print("\nhours used", int(ok.sum()), "| mean headroom MW:", {k: round(v[ok].mean()) for k, v in H.items()},
      "| mean need MW", round(need[ok].mean()))
