"""E2, second test: P.O. 1.5 §4.4 with the programme after the intraday markets (e·sios PHFC), 2024.

Requirement = REE's mFRR requirement (1788) + aFRR assigned (632) + §4.4 deficits of the PHFC programme against REE's
forecasts (demand, wind, solar; H+3 or D+1). Headroom of running CCGT + coal: the units on in the I90 day-ahead
programme (PDVP) give the capacity online, PHFC gives their output after intraday (variant B), or PDVP gives both
(variant A, as in e2_analysis.py). Judged against REE's identified real-time need (1880) on the pass marks set
before the test: >= 70 % of the need hours, hourly correlation >= 0.5, volume 0.5-2x.

    python redispatch_realism/e2_analysis_phfc.py
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
fc = {"H3": (esios(FC, 1776), esios(FC, 1778), esios(FC, 1780)), "D1": (esios(FC, 1775), esios(FC, 1777), esios(FC, 1779))}
st_fc = esios(FC, 543).fillna(0)
ph_dem, ph_wind = esios(PH, 10279), esios(PH, 10281)
ph_sol = esios(PH, 1413).fillna(0) + esios(PH, 1414).fillna(0)
ph_ccgt, ph_coal = esios(PH, 1408).fillna(0), esios(PH, 10282).fillna(0)

# units on in the day-ahead programme (I90 PDVP), their capacity and output
p = pd.read_csv(D / "i90" / "i90_pdvp.csv.gz", encoding="utf-8", encoding_errors="replace")
p.columns = ["date", "unit", "tof", "hour", "mwh", "a", "b"]
p = p.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
t = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
t["ree_max_mw"] = pd.to_numeric(t.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
p = p.merge(t[["ree_unit", "group", "ree_max_mw"]], left_on=p.unit.str.strip(), right_on="ree_unit", how="left")
p["t"] = pd.to_datetime(p.date) + pd.to_timedelta(p.hour, unit="h")
th = p[p.group.isin(["CCGT", "coal"]) & (p.mwh > 1)]
cap_on = th.groupby("t").ree_max_mw.sum().reindex(idx).fillna(0)
out_pdvp = th.groupby("t").mwh.sum().reindex(idx).fillna(0)
head = {"A (day-ahead)": (cap_on - out_pdvp).clip(lower=0),
        "B (after intraday)": (cap_on - ph_ccgt - ph_coal).clip(lower=0)}

ok = need.notna() & ph_dem.notna() & ph_wind.notna()
hit = need > 0
def judge(name, x):
    x, y, h = x[ok], need[ok], hit[ok]
    s = x > 0
    d = pd.DataFrame({"x": x, "y": y}).resample("D").mean()
    rec, prec = (s & h).sum() / h.sum(), (s & h).sum() / max(1, s.sum())
    vol = x.sum() / y.sum()
    ok_marks = "PASS" if rec >= 0.7 and x.corr(y) >= 0.5 and 0.5 <= vol <= 2 else "fail"
    return dict(signal=name, corr_h=x.corr(y), corr_day=d.x.corr(d.y), hours=int(s.sum()), recall=rec, precision=prec,
                volume=vol, marks=ok_marks)

rows, comp = [], {}
for tag, (fd, fw, fs) in fc.items():
    parts = {"demand": fd - ph_dem, "wind": ph_wind - fw, "solar": ph_sol - (fs + st_fc)}
    supp = sum(v.clip(lower=0) for v in parts.values())
    comp[tag] = {k: v[ok] for k, v in parts.items()} | {"supp": supp[ok]}
    for k, v in parts.items():
        rows.append(judge(f"{tag} {k} gap (signed)", v))
    rows.append(judge(f"{tag} supplementary (§4.4)", supp))
    for hn, hv in head.items():
        rows.append(judge(f"{tag} shortfall, headroom {hn}", (tert + sec + supp - hv).clip(lower=0)))
        rows.append(judge(f"{tag} shortfall w/o aFRR, headroom {hn}", (tert + supp - hv).clip(lower=0)))
r = pd.DataFrame(rows).set_index("signal")
print(r.round(2).to_string())
print("\nmean MW: need (all hours)", round(need.mean()), "| tertiary", round(tert.mean()), "| aFRR", round(sec.mean()),
      "| headroom A", round(head["A (day-ahead)"].mean()), "| B", round(head["B (after intraday)"].mean()),
      "| capacity online", round(cap_on.mean()))
for tag in fc:
    print(f"{tag} gaps, mean of the positive part:", {k: round(v.clip(lower=0).mean()) for k, v in comp[tag].items() if k != "supp"},
          "| supp", round(comp[tag]["supp"].mean()))
best = r[r.index.str.contains("shortfall")].sort_values("corr_h", ascending=False).index[0]
print("\nbest shortfall signal:", best)
