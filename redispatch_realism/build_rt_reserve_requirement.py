"""Hourly upward reserve requirement for the real-time stage's best-effort rule ([redispatch.reserve].rule = "e2").

The requirement is the one the E2 tests used (e2_rule.py, fixed 4 Nov; decided for the model 5 Nov):
    requirement = mFRR requirement (e·sios 1788)               P.O. 1.5 §4.3
                + assigned aFRR upward band (e·sios 632)       P.O. 1.5 §4.2
                + §4.4 gaps: REE's D+1 forecasts against the after-intraday programme (PHFC totals):
                  demand above the programme, wind and solar below it
The model compares it with the headroom of ITS OWN schedule (running CCGT/coal, pumped-storage turbine headroom,
stoppable pumping; redispatch_reserve.jl), not with REE's.  REE's headroom (per-unit PHFC, I90DIA36) and the
shortfall the E2 tests scored are written alongside as a reference; the script checks that this file reproduces
e2_rule.shortfall exactly.  Hours where a part is missing get no row (no requirement in the model).

    python redispatch_realism/build_rt_reserve_requirement.py [--year 2024]
Writes redispatch_realism/data/rt_reserve_requirement_<year>.csv:
    date, hour, mfrr_mw, afrr_mw, gaps_mw, requirement_mw, ree_headroom_mw, ree_shortfall_mw, ree_need_mw
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import PATHS, _esios, need_series, shortfall   # noqa: E402


def parts(year, idx):
    """The requirement's parts, as in e2_rule.shortfall (same series, same fill rules)."""
    p = PATHS[year]
    dem_d1 = _esios(p["fc"], 1775, idx)
    mfrr = _esios(p["fc"], 1788, idx).ffill()
    if mfrr.isna().mean() > 0.5:
        raise SystemExit(f"{year}: no e·sios 1788; e2_rule then uses largest unit + 2 % of demand from REE's "
                         "programme, which is not a model input; not built")
    afrr = _esios(p["afrr"], 632, idx).ffill()
    ph = lambda i: _esios(p["phfc"], i, idx)
    gaps = ((dem_d1 - ph(10279)).clip(lower=0)
            + (ph(10281) - _esios(p["fc"], 1777, idx)).clip(lower=0)
            + (ph(1413).fillna(0) + ph(1414).fillna(0) - _esios(p["fc"], 1779, idx)
               - _esios(p["fc"], 543, idx).fillna(0)).clip(lower=0))
    return mfrr, afrr, gaps


def ree_headroom(year, idx):
    """REE's available reserve in the E2 sense (per-unit PHFC programme), as in e2_rule.shortfall."""
    p = PATHS[year]
    tech = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
    tech["ree_max_mw"] = pd.to_numeric(tech.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
    u = pd.read_csv(p["i90"], encoding="utf-8", encoding_errors="replace").iloc[:, [0, 1, 3, 4]]
    u.columns = ["date", "unit", "hour", "mwh"]
    u = u.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
    u = u.merge(tech[["ree_unit", "group", "ree_max_mw"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
    u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")

    def head(groups):
        run = u[u.group.isin(groups) & (u.mwh > 1)]
        return (run.ree_max_mw - run.mwh).clip(lower=0).groupby(run.t).sum().reindex(idx).fillna(0)
    pump = -u[(u.group == "pumped storage (pump)") & (u.mwh < -1)].groupby("t").mwh.sum().reindex(idx).fillna(0)
    return head(["CCGT", "coal"]) + head(["pumped storage (turbine)"]) + pump


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--year", type=int, default=2024, choices=sorted(PATHS))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    out = a.out or HERE / "data" / f"rt_reserve_requirement_{a.year}.csv"
    idx = pd.date_range(f"{a.year}-01-01", f"{a.year}-12-31 23:00", freq="h")

    mfrr, afrr, gaps = parts(a.year, idx)
    req = mfrr + afrr + gaps
    head = ree_headroom(a.year, idx)
    short, ok = shortfall(a.year, idx)
    mine = (req - head).clip(lower=0).where(ok, 0)
    diff = float((mine - short).abs().max())
    if not np.isfinite(diff) or diff > 1e-6:
        raise SystemExit(f"requirement does not reproduce e2_rule.shortfall (max difference {diff})")
    print(f"check: requirement − REE headroom reproduces e2_rule.shortfall (max difference {diff:.1e} MW)")

    keep = ok & req.notna()
    t = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "hour": idx.hour,
                      "mfrr_mw": mfrr, "afrr_mw": afrr, "gaps_mw": gaps, "requirement_mw": req,
                      "ree_headroom_mw": head, "ree_shortfall_mw": short,
                      "ree_need_mw": need_series(a.year, idx)}, index=idx)[keep]
    out.parent.mkdir(parents=True, exist_ok=True)
    t.round(1).to_csv(out, index=False)
    print(f"{out}: {len(t)} of {len(idx)} hours (missing: {len(idx) - len(t)})")
    print(f"mean MW: mFRR {t.mfrr_mw.mean():.0f} + aFRR {t.afrr_mw.mean():.0f} + §4.4 gaps {t.gaps_mw.mean():.0f} "
          f"= {t.requirement_mw.mean():.0f}; REE headroom {t.ree_headroom_mw.mean():.0f}; "
          f"shortfall > 0 in {(t.ree_shortfall_mw > 0).mean():.0%} of hours")
    m = t.assign(month=t.date.str[:7]).groupby("month")[["requirement_mw", "ree_headroom_mw", "ree_shortfall_mw",
                                                         "ree_need_mw"]].mean().round(0)
    print(m.to_string())


if __name__ == "__main__":
    main()
