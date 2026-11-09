"""Real-time upward reserve requirement from P.O. 1.5's own terms, for runs without REE's published requirement (2035).
Method and pass marks fixed before any result is seen (9 Nov 2026).

P.O. 1.5 (BOE-A-2024-11535) and what each part becomes:
  §4.3 mFRR up  = the largest loss of production by a single failure + 2 % of the forecast demand
                  -> largest scheduled nuclear / CCGT / coal unit (a physical generator; REE's I90 programme units
                     bundle several hydro plants, COF1, DUER) + 0.02 x demand
  §4.2 aFRR up  = set by REE per period from expected demand changes and likely failures, at least 500 MW (no formula)
                  -> REE's 2024 band (e·sios 632) by hour of day, fitted Jan-Jun 2024, floored at 500 MW
  §4.4 extra    = REE's forecasts against the programmes: demand above, wind and solar below
                  -> g_d x demand + g_w x wind + g_s x solar, the 2024 ratios sum(positive gap) / sum(quantity),
                     fitted Jan-Jun 2024 (the gaps as built in build_rt_reserve_requirement.py)
Assumption to state: 2035's forecast errors per MW of demand, wind and solar, and REE's aFRR band, are 2024's.

Tests on Jul-Dec 2024 against the published requirement (rt_reserve_requirement_2024.csv, requirement_mw):
  (a) REE's inputs: D+1 demand (1775), wind (1777), solar (1779 + 543); largest unit from REE's PHFC (I90DIA36)
  (b) the model's own inputs (--model-run <year-run folder>): DA demand, wind, solar (da_profiles.csv); largest
      nuclear/CCGT/coal unit in its BAL schedule (bal_dispatch.csv)
Pass marks, each of (a) and (b): mean within 0.90-1.10 of the published requirement, hourly r >= 0.50.
Writes data/rt_reserve_formula.csv (part, hour, value) for [redispatch.reserve] e2_requirement = "po15".

    python redispatch_realism/build_rt_reserve_formula.py --model-run ../solstorm_results/y24rtact
"""
import argparse, glob, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import PATHS, _esios                                    # noqa: E402
SHARE, FLOOR, BIG = 0.02, 500.0, ("Nuclear", "Combined_cycle", "Coal")
FIT = ("2024-01-01", "2024-06-30"); TEST = ("2024-07-01", "2024-12-31")


def ree_inputs(idx):
    p = PATHS[2024]
    tech = pd.read_csv(HERE / "data" / "ree_unit_technology.csv")
    u = pd.read_csv(p["i90"], encoding="utf-8", encoding_errors="replace").iloc[:, [0, 1, 3, 4]]
    u.columns = ["date", "unit", "hour", "mwh"]
    u = u.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
    u = u.merge(tech[["ree_unit", "group"]], left_on=u.unit.str.strip(), right_on="ree_unit", how="left")
    u["t"] = pd.to_datetime(u.date) + pd.to_timedelta(u.hour, unit="h")
    big = u[u.group.isin(["nuclear", "CCGT", "coal"]) & (u.mwh > 1)].groupby("t").mwh.max().reindex(idx)
    ph = lambda i: _esios(p["phfc"], i, idx)
    dem, wind = _esios(p["fc"], 1775, idx), _esios(p["fc"], 1777, idx)
    sol = _esios(p["fc"], 1779, idx) + _esios(p["fc"], 543, idx).fillna(0)
    gd = (dem - ph(10279)).clip(lower=0); gw = (ph(10281) - wind).clip(lower=0)
    gs = (ph(1413).fillna(0) + ph(1414).fillna(0) - sol).clip(lower=0)
    afrr = _esios(p["afrr"], 632, idx).ffill()
    return pd.DataFrame({"big": big, "dem": dem, "wind": wind, "sol": sol, "gd": gd, "gw": gw, "gs": gs, "afrr": afrr})


def model_inputs(run, idx):
    prof = pd.concat([pd.read_csv(f) for f in glob.glob(str(Path(run) / "*" / "da_profiles.csv"))]).drop_duplicates(["date", "hour"])
    bal = pd.concat([pd.read_csv(f) for f in glob.glob(str(Path(run) / "*" / "bal_dispatch.csv"))])
    bal = bal[bal.technology.isin(BIG) | bal.fuel.isin(["Nuclear", "Coal"])]
    big = bal.groupby(["date", "hour"]).dispatch_mw.max().rename("big").reset_index()
    m = prof.merge(big, on=["date", "hour"], how="left")
    m.index = pd.to_datetime(m.date) + pd.to_timedelta(m.hour, unit="h")
    return m.rename(columns={"load_mw": "dem", "wind_mw": "wind", "solar_mw": "sol"}).reindex(idx)


def formula(x, f):
    afrr = np.maximum(f["afrr"][x.index.hour], FLOOR)
    return x.big + SHARE * x.dem + afrr + f["g_d"] * x.dem + f["g_w"] * x.wind + f["g_s"] * x.sol


def score(name, req, pub, sel):
    ok = sel & req.notna() & pub.notna()
    r, p = req[ok], pub[ok]
    ratio, corr = r.mean() / p.mean(), r.corr(p)
    passed = 0.90 <= ratio <= 1.10 and corr >= 0.50
    print(f"  {name}: formula {r.mean():,.0f} vs published {p.mean():,.0f} MW (ratio {ratio:.2f}), hourly r {corr:.2f}, "
          f"MAE {(r - p).abs().mean():,.0f} MW over {ok.sum()} h -> {'PASS' if passed else 'FAIL'}")
    return passed


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model-run", type=Path)
    ap.add_argument("--out", type=Path, default=HERE / "data" / "rt_reserve_formula.csv")
    a = ap.parse_args()
    idx = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")
    x = ree_inputs(idx)
    fit = (idx >= FIT[0]) & (idx < pd.Timestamp(FIT[1]) + pd.Timedelta(days=1))
    test = (idx >= TEST[0])
    xf = x[fit]
    f = {"afrr": xf.afrr.groupby(xf.index.hour).mean().reindex(range(24)).values,
         "g_d": xf.gd.sum() / xf.dem.sum(), "g_w": xf.gw.sum() / xf.wind.sum(), "g_s": xf.gs.sum() / xf.sol.sum()}
    print(f"fitted on {FIT[0]}..{FIT[1]}: aFRR {np.round(f['afrr']).astype(int).tolist()} MW by hour; "
          f"gaps {100*f['g_d']:.2f} % of demand, {100*f['g_w']:.2f} % of wind, {100*f['g_s']:.2f} % of solar")
    pub = pd.read_csv(HERE / "data" / "rt_reserve_requirement_2024.csv")
    pub = pd.Series(pub.requirement_mw.values, index=pd.to_datetime(pub.date) + pd.to_timedelta(pub.hour, unit="h")).reindex(idx)
    print("Jul-Dec 2024 (test):")
    ok = [score("(a) REE's inputs", formula(x, f), pub, test)]
    print(f"      parts, mean MW: mFRR {(x.big + SHARE * x.dem)[test].mean():,.0f}, aFRR {np.maximum(f['afrr'][idx.hour], FLOOR)[test].mean():,.0f}, "
          f"gaps {(f['g_d'] * x.dem + f['g_w'] * x.wind + f['g_s'] * x.sol)[test].mean():,.0f}")
    if a.model_run is not None:
        m = model_inputs(a.model_run, idx)
        ok.append(score("(b) the model's inputs", formula(m, f), pub, test))
        print(f"      parts, mean MW: mFRR {(m.big + SHARE * m.dem)[test].mean():,.0f} (largest unit {m.big[test].mean():,.0f}), "
              f"gaps {(f['g_d'] * m.dem + f['g_w'] * m.wind + f['g_s'] * m.sol)[test].mean():,.0f}")
    rows = [("afrr", h, float(max(v, FLOOR))) for h, v in enumerate(f["afrr"])]
    rows += [("demand_share", -1, SHARE), ("gap_demand", -1, f["g_d"]), ("gap_wind", -1, f["g_w"]), ("gap_solar", -1, f["g_s"])]
    pd.DataFrame(rows, columns=["part", "hour", "value"]).to_csv(a.out, index=False)
    print(f"{'ALL PASS' if all(ok) else 'NOT ALL PASS'}; wrote {a.out}")


if __name__ == "__main__":
    main()
