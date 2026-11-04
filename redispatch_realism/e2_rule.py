"""E2 rule shared by the 2024 window choice and the 2023 test (fixed 4 Nov).

shortfall_t = max(0, mFRR requirement + assigned aFRR band + P.O. 1.5 §4.4 gaps
                     - headroom of running CCGT/coal - headroom of running pumped-storage turbines - stoppable pumping)
  mFRR requirement: e·sios 1788; where the year has no 1788, P.O. 1.5 §4.3's own reference instead: the largest
                    unit in the after-intraday programme + 2 % of REE's D+1 demand forecast (decided before 2023 is seen)
  §4.4 gaps: REE's D+1 forecasts against the after-intraday programme (PHFC totals): demand above the programme,
             wind and solar below it
  headroom: per-unit PHFC programme (I90DIA36), capacity from data/ree_unit_technology.csv
REE's identified need: e·sios 1880.
"""
import os
from pathlib import Path
import numpy as np, pandas as pd
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
HERE = Path(__file__).resolve().parent
F = D / "forecasts"
PATHS = {
    2024: dict(fc=F / "esios_forecasts_2024.csv.gz", need=F / "reserve" / "esios_reserve_2024.csv.gz",
               afrr=F / "reserve" / "esios_reserve_2024.csv.gz", phfc=F / "phfc" / "esios_phfc_2024.csv.gz",
               i90=D / "i90" / "i90_phfc.csv.gz"),
    2023: dict(fc=F / "esios_forecasts_2023.csv.gz", need=F / "reserve2023" / "esios_reserve2023_2023.csv.gz",
               afrr=F / "reserve2023b" / "esios_reserve2023b_2023.csv.gz", phfc=F / "phfc" / "esios_phfc_2023.csv.gz",
               i90=D / "i90_2023" / "i90_phfc.csv.gz"),
}

def _esios(path, ind, idx):
    f = pd.read_csv(path); f = f[f.indicator == ind].copy()
    if f.empty:
        return pd.Series(np.nan, index=idx)
    f["t"] = pd.to_datetime(f.datetime_utc).dt.tz_convert("Europe/Madrid").dt.tz_localize(None)
    s = f.set_index("t").value
    return s[~s.index.duplicated()].resample("h").mean().reindex(idx)

def need_series(year, idx):
    return _esios(PATHS[year]["need"], 1880, idx).fillna(0)

def shortfall(year, idx):
    p = PATHS[year]
    tech = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
    tech["ree_max_mw"] = pd.to_numeric(tech.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
    u = pd.read_csv(p["i90"], encoding="utf-8", encoding_errors="replace").iloc[:, [0, 1, 3, 4]]
    u.columns = ["date", "unit", "hour", "mwh"]
    u = u.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
    u = u.merge(tech[["ree_unit", "group", "ree_max_mw"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
    u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")
    def headroom(groups):
        run = u[u.group.isin(groups) & (u.mwh > 1)]
        return (run.ree_max_mw - run.mwh).clip(lower=0).groupby(run.t).sum().reindex(idx).fillna(0)
    pump = -u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum().reindex(idx).fillna(0)
    dem_d1 = _esios(p["fc"], 1775, idx)
    tert = _esios(p["fc"], 1788, idx).ffill()
    if tert.isna().mean() > 0.5:                        # no 1788 for this year: P.O. 1.5 §4.3's reference
        big = u[u.mwh > 1].groupby("t").mwh.max().reindex(idx).ffill()
        tert = big + 0.02 * dem_d1
        print(f"  {sorted(set(idx.year))}: no e·sios 1788, mFRR requirement = largest unit + 2 % of demand "
              f"(mean {tert.mean():.0f} MW)")
    sec = _esios(p["afrr"], 632, idx).ffill()
    ph = lambda i: _esios(p["phfc"], i, idx)
    supp = ((dem_d1 - ph(10279)).clip(lower=0)
            + (ph(10281) - _esios(p["fc"], 1777, idx)).clip(lower=0)
            + (ph(1413).fillna(0) + ph(1414).fillna(0) - _esios(p["fc"], 1779, idx)
               - _esios(p["fc"], 543, idx).fillna(0)).clip(lower=0))
    short = (tert + sec + supp - headroom(["CCGT", "coal"]) - headroom(["pumped storage (turbine)"]) - pump).clip(lower=0)
    ok = short.notna() & (u.groupby("t").size().reindex(idx).fillna(0) > 0)
    return short.where(ok, 0), ok

def window_need(short, A, B, amount):
    """Flag t if the shortfall is positive in [t - B, t + A]; amount 'own' (the hour's own shortfall, else the
    window's mean positive shortfall) or 'max' (the window's largest)."""
    pos = short.where(short > 0)
    fwd = lambda s, f: getattr(s[::-1].rolling(A + 1, min_periods=1), f)()[::-1]
    wmax = fwd(short, "max").rolling(B + 1, min_periods=1).max()
    if amount == "max":
        return wmax
    wsum = fwd(pos.fillna(0), "sum").rolling(B + 1, min_periods=1).sum()
    wcnt = fwd(pos.notna().astype(float), "sum").rolling(B + 1, min_periods=1).sum()
    mean = (wsum / wcnt.replace(0, np.nan)).fillna(0)
    return short.where(short > 0, mean)

def score(x, need, m):
    x, y, hit = x[m], need[m], need[m] > 0
    s = x > 0
    return dict(corr=round(float(x.corr(y)), 3),
                corr_day=round(float(pd.DataFrame({"x": x, "y": y}).resample("D").mean().pipe(lambda d: d.x.corr(d.y))), 3),
                recall=round(float((s & hit).sum() / hit.sum()), 3), precision=round(float((s & hit).sum() / max(1, s.sum())), 3),
                volume=round(float(x.sum() / y.sum()), 3), hours=int(s.sum()), need_hours=int(hit.sum()))
