"""E2 step A (diagnostic, nothing fitted): is REE's upward-reserve need (e·sios 1880) a multi-hour decision?

Uses the best single-hour rule (e2_test_ccgt_pumped.py: mFRR + aFRR + §4.4 gaps against PHFC − CCGT/coal and
pumped-storage headroom) and compares its timing with REE's need:
  1. lead / lag: corr(need_t, shortfall_{t+k}) for k = -6..+6 (k > 0: REE's need comes before the rule's shortfall)
  2. blocks: lengths of REE's need periods and of the rule's shortfall periods, how many of REE's blocks contain a
     shortfall hour, and where in REE's blocks the shortfall hours sit (start / middle / end)

    python redispatch_realism/e2_diag_multihour.py
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
pump = -u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum().reindex(idx).fillna(0)
short = (tert + sec + supp - headroom(["CCGT", "coal"]) - headroom(["pumped storage (turbine)"]) - pump).clip(lower=0)
ok = need.notna() & short.notna()
need, short = need.where(ok, 0), short.where(ok, 0)

def blocks(on):
    """(start, length) of runs of True."""
    out, start = [], None
    for i, v in enumerate(on.values):
        if v and start is None: start = i
        if not v and start is not None: out.append((start, i - start)); start = None
    if start is not None: out.append((start, len(on) - start))
    return out

for label, m in (("full year", idx >= "2024-01-01"), ("Jul-Dec", idx >= "2024-07-01")):
    n, s = need[m], short[m]
    print(f"\n=== {label} ===")
    print("1. lead/lag  corr(need_t, shortfall_t+k)   [k > 0: REE's need comes BEFORE the rule's shortfall]")
    row = {k: round(n.corr(s.shift(-k)), 3) for k in range(-6, 7)}
    print("   ", row)
    hitrow = {k: round(((n > 0) & (s.shift(-k) > 0)).sum() / max(1, (s.shift(-k) > 0).sum()), 2) for k in range(-6, 7)}
    print("    share of shortfall hours (shifted by k) that fall in a REE need hour:", hitrow)
    nb, sb = blocks(n > 0), blocks(s > 0)
    nl, sl = np.array([b[1] for b in nb]), np.array([b[1] for b in sb])
    print(f"2. block lengths (h): REE need  n={len(nl)}, median {np.median(nl):.0f}, mean {nl.mean():.1f}, "
          f"share >= 4 h {np.mean(nl >= 4):.2f}, >= 8 h {np.mean(nl >= 8):.2f}")
    print(f"                     rule short n={len(sl)}, median {np.median(sl):.0f}, mean {sl.mean():.1f}, "
          f"share >= 4 h {np.mean(sl >= 4):.2f}, >= 8 h {np.mean(sl >= 8):.2f}")
    sv = (s > 0).values
    with_short = [b for b in nb if sv[b[0]:b[0] + b[1]].any()]
    print(f"   REE blocks containing >= 1 shortfall hour: {len(with_short)} of {len(nb)} ({len(with_short) / len(nb):.0%}); "
          f"they hold {sum(b[1] for b in with_short) / max(1, nl.sum()):.0%} of REE's need hours")
    pos = []
    for b0, L in nb:
        if L < 3: continue
        for j in range(L):
            if sv[b0 + j]: pos.append(j / (L - 1))
    pos = np.array(pos)
    if len(pos):
        print(f"   where the shortfall hours sit inside REE blocks of >= 3 h: first third {np.mean(pos < 1/3):.0%}, "
              f"middle {np.mean((pos >= 1/3) & (pos <= 2/3)):.0%}, last third {np.mean(pos > 2/3):.0%}  (n={len(pos)})")
    # shortfall hours just outside REE blocks: before (REE ended early) or after (REE started late)
    nv = (n > 0).values
    before = sum(1 for i in range(len(sv) - 3) if sv[i] and not nv[i] and nv[i + 1:i + 4].any())
    after = sum(1 for i in range(3, len(sv)) if sv[i] and not nv[i] and nv[i - 3:i].any())
    print(f"   shortfall hours outside REE blocks: {int((sv & ~nv).sum())}; of which <= 3 h before a REE block {before}, "
          f"<= 3 h after one {after}")
    print(f"   hour of day where REE need blocks START (top 5): "
          f"{pd.Series([n.index[b[0]].hour for b in nb]).value_counts().head(5).to_dict()}")
    print(f"   hour of day where rule shortfall blocks START (top 5): "
          f"{pd.Series([s.index[b[0]].hour for b in sb]).value_counts().head(5).to_dict()}")
