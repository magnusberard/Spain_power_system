"""A demand-driven rule for phase I's voltage-zone needs (step E: 2035 has no I90 data).

Basis. Davi-Arderius & Schittekatte (2023): at low demand the lines' surplus reactive power raises voltages and REE
starts synchronous units to absorb it. REE's 2024 data shows the same: units raised for voltage per hour (I90, causes
SOT/COT, voltage_zone_requirement.csv) against the national load (OMIE physical generation, real_hourly_2024): r = -0.80
in Jan-Jun, -0.65 in Jul-Dec; 11.3 units/h in the lowest load fifth vs 2.1 in the highest (Jan-Jun).

Rule, per zone and national-load bin (bin edges = load quantiles of the fit period, in MW, so they apply to any year):
    p_need(zone, bin)   share of the bin's hours in which REE had a voltage need in the zone
    n_online(zone, bin) median number of units REE had online in the zone in those hours (RD5's requirement)
    need(zone, hour)    n_online(zone, bin(load)) if p_need >= --p-min, else no need
Fitted on --fit (default Jan-Jun 2024), tested on --test (default Jul-Dec 2024) against REE's actual zone needs.

    python redispatch_realism/build_zone_need_rule.py --real ../spain-model-runs/reference/real_hourly_2024.csv.gz
Writes redispatch_realism/data/zone_need_rule.csv (zone, bin, load_lo_mw, load_hi_mw, p_need, n_online) and prints
the test. Applying it to a year writes date, hour, zone, n_online, n_raised like voltage_zone_requirement.csv
(--apply <csv with date, hour, load_mw> --apply-out <file>).
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def national_load(real):
    r = pd.read_csv(real)
    ph = [c for c in r.columns if c.startswith("phys_")]
    return r.assign(load_mw=r[ph].sum(axis=1))[["date", "hour", "load_mw"]]


def apply_rule(rule, load, p_min):
    edges = sorted(set(rule.load_lo_mw) | set(rule.load_hi_mw))
    load = load.assign(bin=np.clip(np.searchsorted(edges, load.load_mw, side="right") - 1, 0, len(edges) - 2))
    m = load.merge(rule, on="bin")
    m = m[m.p_need >= p_min]
    return m.assign(n_raised=1)[["date", "hour", "zone", "n_online", "n_raised"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--real", type=Path, default=REPO.parent / "spain-model-runs" / "reference" / "real_hourly_2024.csv.gz")
    ap.add_argument("--fit", nargs=2, default=["2024-01-01", "2024-06-30"])
    ap.add_argument("--test", nargs=2, default=["2024-07-01", "2024-12-31"])
    ap.add_argument("--bins", type=int, default=10)
    # chosen on the fit half only (Jan-Jun): 0.4 gives the best balance of precision and recall there (F1 0.744,
    # vs 0.739 at 0.3 and 0.733 at 0.5)
    ap.add_argument("--p-min", type=float, default=0.4)
    ap.add_argument("--out", type=Path, default=HERE / "data" / "zone_need_rule.csv")
    ap.add_argument("--apply", type=Path, help="CSV with date, hour, load_mw (e.g. a 2035 load profile)")
    ap.add_argument("--apply-out", type=Path)
    a = ap.parse_args()
    zr = pd.read_csv(HERE / "data" / "voltage_zone_requirement.csv")
    load = national_load(a.real)
    zones = sorted(zr.zone.unique())
    fit = load[(load.date >= a.fit[0]) & (load.date <= a.fit[1])]
    edges = np.quantile(fit.load_mw, np.linspace(0, 1, a.bins + 1))
    edges[0], edges[-1] = 0.0, 1e6                                   # open ends, so any year's load falls in a bin
    lab = lambda d: np.clip(np.searchsorted(edges, d.load_mw, side="right") - 1, 0, a.bins - 1)
    fit = fit.assign(bin=lab(fit))
    grid = fit.merge(pd.DataFrame({"zone": zones}), how="cross")
    need = zr[["date", "hour", "zone", "n_online"]]
    g = grid.merge(need, on=["date", "hour", "zone"], how="left")
    rule = g.groupby(["zone", "bin"]).agg(p_need=("n_online", lambda s: s.notna().mean()),
                                         n_online=("n_online", lambda s: float(np.nanmedian(s)) if s.notna().any() else 0.0)).reset_index()
    rule["n_online"] = rule.n_online.round().astype(int)
    rule["load_lo_mw"] = edges[rule.bin]; rule["load_hi_mw"] = edges[rule.bin + 1]
    a.out.parent.mkdir(parents=True, exist_ok=True)
    rule.to_csv(a.out, index=False)
    print(f"rule: {len(zones)} zones x {a.bins} load bins (edges {np.round(edges[1:-1]).astype(int).tolist()} MW), "
          f"fitted {a.fit[0]}..{a.fit[1]} -> {a.out}")

    # test: predicted vs REE's actual zone needs, per hour, out of sample
    for lab_, (d0, d1) in (("fit", a.fit), ("test", a.test)):
        L = load[(load.date >= d0) & (load.date <= d1)]
        pred = apply_rule(rule, L, a.p_min)
        act = zr[(zr.date >= d0) & (zr.date <= d1)]
        hp = pred.groupby(["date", "hour"]).n_online.sum().reindex(pd.MultiIndex.from_frame(L[["date", "hour"]]), fill_value=0)
        ha = act.groupby(["date", "hour"]).n_online.sum().reindex(hp.index, fill_value=0)
        zp = set(zip(pred.date, pred.hour, pred.zone)); za = set(zip(act.date, act.hour, act.zone))
        hit = len(zp & za); prec = hit / max(len(zp), 1); rec = hit / max(len(za), 1)
        print(f"{lab_:4s} {d0}..{d1}: units required per hour, rule {hp.mean():.1f} vs REE {ha.mean():.1f} "
              f"(hourly r = {np.corrcoef(hp, ha)[0, 1]:.2f}); zone-hours with a need: rule {len(zp):,}, REE {len(za):,}, "
              f"both {hit:,} (precision {prec:.0%}, recall {rec:.0%})")
    if a.apply is not None:
        L = pd.read_csv(a.apply)
        out = apply_rule(rule, L, a.p_min)
        out.to_csv(a.apply_out or (HERE / "data" / "voltage_zone_requirement_rule.csv"), index=False)
        print(f"applied to {a.apply}: {len(out):,} zone-hours")


if __name__ == "__main__":
    main()
