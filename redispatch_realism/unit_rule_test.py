"""A rule for the named phase I units (fix 2, data/phase1_unit_requirement.csv) so they need no 2024 hours: offline test
(no model run), method and choice fixed before any result is seen (9 Nov 2026).

Truth: a named unit is "required" in every hour REE raised it in phase I (I90 UPOPVPV, up, any cause), as
build_unit_requirement.py does. The six units of the 2024 file: ABO2, ACE4, BAHIAB, BES5, CTGN1, SROQ2.
Load: REE's D+1 demand forecast (e·sios 1775), both years.
Variants (both fitted on Jan-Jun 2024):
  U1 zone-triggered: required whenever its voltage zone has a need by the zone rule R0 (per zone and load decile,
     p_need >= 0.4, voltage needs SOT/COT, refitted here on the same load source)
  U2 own load pattern: per unit and load decile, required if REE raised the unit in >= 40 % of the bin's hours
Scores (per unit-hour, all six units): precision, recall, size (rule hours / REE hours), hourly correlation of the number
of required units; on Jul-Dec 2024 (primary) and on 2023 (out of year, any-cause raises, so the 2023 code change does not
matter). Choice: the better Jul-Dec 2024 hourly correlation; within 0.02, the size closer to 1; still tied, U1 (simpler).

    python redispatch_realism/unit_rule_test.py
"""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import PATHS, _esios                                    # noqa: E402
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
I90 = {2024: D / "i90", 2023: D / "i90_2023"}
UNITS = ["ABO2", "ACE4", "BAHIAB", "BES5", "CTGN1", "SROQ2"]
P = 0.4


def frame(year, xw, zone_of):
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    h = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "hour": idx.hour, "load": _esios(PATHS[year]["fc"], 1775, idx).values})
    ph = pd.read_csv(I90[year] / "i90_tc_phase.csv.gz")
    up = ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")].copy()
    up["ree"] = up["Unidad de Programación"].str.strip()
    req = set(zip(*[up[up.ree.isin(UNITS)][c] for c in ("ree", "date", "hour")]))
    up["unit"] = up.ree.map(xw)
    up["zone"] = up.unit.map(zone_of)
    vz = up[up["Tipo Restricción"].isin(["SOT", "COT"]) & up.zone.notna()]
    zneed = set(zip(vz.zone, vz.date, vz.hour))
    rows = [dict(unit=u, zone=zone_of.get(xw.get(u)), date=d, hour=hr, load=l)
            for u in UNITS for d, hr, l in zip(h.date, h.hour, h.load)]
    t = pd.DataFrame(rows)
    t["req"] = [(u, d, hr) in req for u, d, hr in zip(t.unit, t.date, t.hour)]
    t["zneed"] = [(z, d, hr) in zneed for z, d, hr in zip(t.zone, t.date, t.hour)]
    return t


def bins(fit, t):
    edges = np.nanquantile(fit.drop_duplicates(["date", "hour"]).load, np.linspace(0, 1, 11)); edges[0], edges[-1] = -np.inf, np.inf
    return np.digitize(t.load, edges[1:-1])


def score(t, pred):
    t = t.assign(pred=pred)
    hit = (t.pred & t.req).sum()
    h = t.groupby(["date", "hour"])[["pred", "req"]].sum()
    return dict(prec=round(hit / max(1, t.pred.sum()), 2), recall=round(hit / max(1, t.req.sum()), 2),
                size=round(t.pred.sum() / max(1, t.req.sum()), 2), corr=round(h.pred.corr(h.req), 3))


def main():
    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv").dropna(subset=["model_unit_id"])
    xw = dict(zip(x.ree_unit.str.strip(), x.model_unit_id))
    zu = pd.read_csv(HERE / "data" / "voltage_zone_units.csv")
    zone_of = dict(zip(zu.unit_id, zu.zone))
    print({u: zone_of.get(xw.get(u)) for u in UNITS})
    t24, t23 = frame(2024, xw, zone_of), frame(2023, xw, zone_of)
    fit = t24[t24.date < "2024-07-01"]
    out = {}
    # U1: zone rule R0 per zone and load decile from Jan-Jun 2024, then the unit follows its zone
    zf = fit.drop_duplicates(["zone", "date", "hour"]).assign(bin=lambda d: bins(fit, d))
    pz = zf.groupby(["zone", "bin"]).zneed.mean()
    u1 = lambda t: pd.Series([pz.get((z, b), 0) >= P for z, b in zip(t.zone, bins(fit, t))], index=t.index)
    # U2: per unit and load decile
    uf = fit.assign(bin=bins(fit, fit))
    pu = uf.groupby(["unit", "bin"]).req.mean()
    u2 = lambda t: pd.Series([pu.get((u, b), 0) >= P for u, b in zip(t.unit, bins(fit, t))], index=t.index)
    test24 = t24[t24.date >= "2024-07-01"]
    for name, f in (("U1 zone-triggered", u1), ("U2 own load pattern", u2)):
        out[name] = {"Jan-Jun 2024 (fit)": score(fit, f(fit)), "Jul-Dec 2024 (test)": score(test24, f(test24)),
                     "2023 (out of year)": score(t23, f(t23))}
    res = pd.DataFrame({(n, p): s for n, v in out.items() for p, s in v.items()}).T
    print(res.to_string())
    for u in UNITS:
        s = {n: score(test24[test24.unit == u], f(test24[test24.unit == u])) for n, f in (("U1", u1), ("U2", u2))}
        print(f"  Jul-Dec 2024 {u:7s} REE hours {int(test24[test24.unit == u].req.sum()):5d}  U1 {s['U1']}  U2 {s['U2']}")
    tt = res.xs("Jul-Dec 2024 (test)", level=1).astype(float)
    best = tt["corr"].max(); c = tt[tt["corr"] >= best - 0.02].assign(gap=lambda d: np.abs(np.log(d["size"]))).sort_values(["gap"])
    print("\nchosen (fixed beforehand):", c.index[0])
    res.to_csv(HERE / "data" / "unit_rule_test.csv")


if __name__ == "__main__":
    main()
