"""Pass/fail checks for each redispatch-realism component (RD1–RD11).

Three kinds of check, each printing PASS or FAIL per test and exiting non-zero on any failure:

  logic       no model run: synthetic inputs with known answers (seconds; run any time)
  same A B    "switch off = unchanged": two runs that should be identical (e.g. main vs this
              branch with every new switch off) give the same redispatch, hour by hour
  rdN A B     "switch on does its job": A = the run with the switch off, B = with it on;
              tests what the component must change, and that it breaks nothing else

    python redispatch_realism/check.py logic
    python redispatch_realism/check.py same results/rd2_A results/main_A
    python redispatch_realism/check.py rd2  results/rd2_A results/rd2_B

How far the model is from REE is not a pass/fail question; settle.py --esios reports it.
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import settle  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def solved(run):
    s = pd.read_csv(run / "summary.csv")
    return s[s.status.isin(settle.SOLVED)]


def failures(a, b):
    """B may not fail more hours than A. The AC OPF is solved locally (Ipopt), so a small input
    change can move a failure from one fragile hour to another; the swaps are listed, not failed."""
    sa, sb = pd.read_csv(a / "summary.csv"), pd.read_csv(b / "summary.csv")
    fa = set(map(tuple, sa[~sa.status.isin(settle.SOLVED)][["date", "hour"]].values))
    fb = set(map(tuple, sb[~sb.status.isin(settle.SOLVED)][["date", "hour"]].values))
    fmt = lambda s: ", ".join(f"{d} h{int(h):02d}" for d, h in sorted(s)) or "none"
    check("B fails no more hours than A", len(fb) <= len(fa),
          f"A {len(fa)}, B {len(fb)}; newly failed: {fmt(fb - fa)}; fixed: {fmt(fa - fb)}")


# ── logic: synthetic run folders with known answers ──────────────────────────
def write_run(d, hours, units):
    """hours: list of (date, hour, p_da, load, losses); units: list of (name, fuel, tech, cost, anchor, rd) per hour."""
    pd.DataFrame([dict(date=h[0], hour=h[1], status="LOCALLY_SOLVED", objective_eur_h=0.0,
                       total_gen_mw=h[3] + h[4], total_load_mw=h[3], load_shed_mw=0.0, mismatch_mw=h[4])
                  for h in hours]).to_csv(d / "summary.csv", index=False)
    pd.DataFrame([dict(date=h[0], hour=h[1], stage=st, price_eur_mwh=h[2] if st == "DA" else 0.0)
                  for h in hours for st in ("DA", "BAL")]).to_csv(d / "market_prices.csv", index=False)
    bal, gen = [], []
    for h, us in zip(hours, units):
        for (n, f, t, c, a, r) in us:
            bal.append(dict(date=h[0], hour=h[1], gen_id=n, fuel=f, technology=t, dispatch_mw=a))
            gen.append(dict(date=h[0], hour=h[1], gen_id=0, unit_name=n, fuel=f, technology=t, bus_i=1,
                            capacity_mw=500.0, dispatch_mw=r, dispatch_mvar=0.0, utilization_pct=0.0,
                            cost_eur_per_mwh=c))
    pd.DataFrame(bal).to_csv(d / "bal_dispatch.csv", index=False)
    pd.DataFrame(gen).to_csv(d / "gen_dispatch.csv", index=False)


def logic():
    print("\nRD1 settle.py — synthetic run, two hours")
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        hours = [("2024-12-02", 0, 80.0, 1000.0, 10.0), ("2024-12-02", 1, 50.0, 900.0, 0.0)]
        units = [
            # h0: gas +40 (c 100), hydro −30 (c 20), pumped storage 0; net +10 = the losses
            [("GAS1", "Gas", "Combined_cycle", 100.0, 200.0, 240.0),
             ("HYD1", "Hydro", "reservoir", 20.0, 300.0, 270.0),
             ("PS1", "Hydro", "pumped_storage", 0.0, 0.0, 0.0),
             ("XB_FR", "CrossBorder", "Interconnector", 0.0, 100.0, 140.0),   # border: must be ignored
             ("LS_1", "LoadShed", "LoadShed", 1e4, 0.0, 0.0)],                 # pseudo-unit: ignored
            # h1: pumped storage +25 (c 0), gas −25 (c 100); net 0
            [("GAS1", "Gas", "Combined_cycle", 100.0, 200.0, 175.0),
             ("HYD1", "Hydro", "reservoir", 20.0, 300.0, 300.0),
             ("PS1", "Hydro", "pumped_storage", 0.0, 0.0, 25.0)],
        ]
        write_run(d, hours, units)
        hourly, monthly, by_type, hod = settle.settle(d)
        h0, h1 = hourly.iloc[0], hourly.iloc[1]
        check("up/down per hour", np.allclose([h0.up_mwh, h0.down_mwh, h1.up_mwh, h1.down_mwh], [40, 30, 25, 25]),
              f"h0 {h0.up_mwh:.0f}/{h0.down_mwh:.0f}, h1 {h1.up_mwh:.0f}/{h1.down_mwh:.0f}")
        check("border and pseudo-units left out", np.isclose(h0.up_mwh, 40))
        # EC = up·(c − p_DA) + down·(p_DA − c):  h0 40·20 + 30·60 = 2600;  h1 25·(0−50) + 25·(50−100) = −2500
        check("extra cost, down at own bid", np.allclose([h0.extra_cost_eur, h1.extra_cost_eur], [2600, -2500]),
              f"{h0.extra_cost_eur:.0f}, {h1.extra_cost_eur:.0f}")
        check("marginal = extra cost + p_DA·(up − down)",
              np.allclose(hourly.marginal_eur, hourly.extra_cost_eur + hourly.p_da * (hourly.up_mwh - hourly.down_mwh)))
        check("up − down = losses when the borders net out", np.isclose(h0.up_mwh - h0.down_mwh, h0.losses_mw))
        hourly_da, *_ = settle.settle(d, down_refund="da")
        # phase I rule: down refunded at p_DA, so the down term is 0:  h0 40·20 = 800;  h1 25·(0−50) = −1250
        check("extra cost, down refunded at the day-ahead price",
              np.allclose(hourly_da.extra_cost_eur, [800, -1250]), f"{list(hourly_da.extra_cost_eur.round())}")
        bids = d / "bids.csv"
        pd.DataFrame([dict(fuel="Gas", technology="Combined_cycle", up_markup=0.5, down_markup=0.0)]).to_csv(bids, index=False)
        hourly_mk, *_ = settle.settle(d, bids=bids)
        # gas up at 150 instead of 100: h0 +40·50 = +2000
        check("mark-up raises the up price", np.isclose(hourly_mk.extra_cost_eur.iloc[0], 4600),
              f"{hourly_mk.extra_cost_eur.iloc[0]:.0f}")
        check("types grouped like the viewer", set(by_type.index) == {"Gas", "Hydro", "Pumped storage"},
              ", ".join(by_type.index))


# ── same: two runs that must give the same redispatch ────────────────────────
def same(a, b, tol_mw=0.5):
    print(f"\nSame redispatch: {a} vs {b}")
    sa, sb = solved(a), solved(b)
    keys = sa.merge(sb, on=["date", "hour"])[["date", "hour"]]
    check("same solved hours", len(keys) == len(sa) == len(sb), f"{len(sa)} vs {len(sb)}, {len(keys)} shared")
    ga = pd.read_csv(a / "gen_dispatch.csv", usecols=["date", "hour", "unit_name", "dispatch_mw"]).merge(keys)
    gb = pd.read_csv(b / "gen_dispatch.csv", usecols=["date", "hour", "unit_name", "dispatch_mw"]).merge(keys)
    m = ga.merge(gb, on=["date", "hour", "unit_name"], suffixes=("_a", "_b"), how="outer")
    check("same units in every hour", m.isna().sum().sum() == 0)
    dmax = (m.dispatch_mw_a - m.dispatch_mw_b).abs().max()
    check(f"dispatch within {tol_mw} MW per unit", dmax <= tol_mw, f"largest difference {dmax:.3f} MW")


# ── rd2: loss_share takes the losses out of the redispatch load ──────────────
def rd2(a, b):
    print(f"\nRD2 loss_share: A = {a} (off), B = {b} (on)")
    sa, sb = solved(a), solved(b)
    failures(a, b)
    m = sa.merge(sb, on=["date", "hour"], suffixes=("_a", "_b"))
    ratio = (m.total_load_mw_b / m.total_load_mw_a)
    share = 1 - ratio.median()
    check("B's load is A's scaled by one constant", (ratio - ratio.median()).abs().max() < 1e-3,
          f"loss_share seen = {share:.4f}")
    ha, *_ = settle.settle(a)
    hb, *_ = settle.settle(b)
    keys = m[["date", "hour"]]
    ha, hb = ha.merge(keys), hb.merge(keys)
    na, nb = (ha.up_mwh - ha.down_mwh).sum(), (hb.up_mwh - hb.down_mwh).sum()
    check("net energy turned up falls to near zero", abs(nb) < 0.25 * abs(na),
          f"A {na / 1e3:.1f} GWh, B {nb / 1e3:.1f} GWh")
    check("less energy turned up", hb.up_mwh.sum() < ha.up_mwh.sum(),
          f"A {ha.up_mwh.sum() / 1e3:.1f}, B {hb.up_mwh.sum() / 1e3:.1f} GWh")
    check("AC losses themselves about unchanged", abs(hb.losses_mw.sum() / ha.losses_mw.sum() - 1) < 0.10,
          f"A {ha.losses_mw.sum() / 1e3:.1f}, B {hb.losses_mw.sum() / 1e3:.1f} GWh")


# ── rd3 / rd4: reactive power only from running equipment ───────────────────
def q_table(run, keys):
    g = pd.read_csv(run / "gen_dispatch.csv",
                    usecols=["date", "hour", "unit_name", "fuel", "capacity_mw", "dispatch_mw", "dispatch_mvar"]).merge(keys)
    a = pd.read_csv(run / "bal_dispatch.csv", usecols=["date", "hour", "gen_id", "dispatch_mw"])
    a = a.rename(columns={"gen_id": "unit_name", "dispatch_mw": "anchor_mw"})
    g = g.merge(a, on=["date", "hour", "unit_name"], how="left")
    g["kind"] = np.select([g.unit_name.str.startswith("LS_"), g.unit_name.str.startswith("SLACK"),
                           g.unit_name.str.startswith("XB_"), g.fuel.isin(["Wind", "Solar"])],
                          ["Load shedding", "Slack", "Border", "Wind and solar"], "Synchronous")
    g["idle"] = (g.kind == "Synchronous") & (g.anchor_mw.fillna(0).abs() < 0.01 * g.capacity_mw)
    return g


def q_mix(g, hours):
    t = g.assign(absq=g.dispatch_mvar.abs()).groupby(np.where(g.idle, "Synchronous, scheduled off", g.kind)).absq.sum()
    return (t / hours).round(0)


def rd3(a, b, load_pf=0.98, tol=1.0):
    print(f"\nRD3 q_requires_online: A = {a} (off), B = {b} (on)")
    sa, sb = solved(a), solved(b)
    failures(a, b)
    keys = sa.merge(sb, on=["date", "hour"])[["date", "hour"]]
    ga, gb = q_table(a, keys), q_table(b, keys)
    idle = gb[gb.idle]
    worst = idle.dispatch_mvar.abs().max() if len(idle) else 0.0
    check(f"units scheduled off give no reactive power (|Q| ≤ {tol} Mvar)", worst <= tol,
          f"largest {worst:.2f} Mvar over {idle.unit_name.nunique()} idle units")
    k = np.tan(np.arccos(load_pf))
    ls = gb[gb.kind == "Load shedding"]
    over = (ls.dispatch_mvar.abs() - k * ls.dispatch_mw.clip(lower=0) - tol).max()
    check("load shedding gives reactive power only in proportion to shed load", over <= 0,
          f"worst excess {max(over, 0):.2f} Mvar")
    n = len(keys)
    print("\n  reactive power, average |Mvar| per hour (A → B):")
    ma, mb = q_mix(ga, n), q_mix(gb, n)
    for kname in sorted(set(ma.index) | set(mb.index)):
        print(f"    {kname:28s} {ma.get(kname, 0):8.0f} → {mb.get(kname, 0):8.0f}")
    ha, *_ = settle.settle(a)
    hb, *_ = settle.settle(b)
    ha, hb = ha.merge(keys), hb.merge(keys)
    print("\n  effect (A → B):")
    print(f"    turned up            {ha.up_mwh.sum() / 1e3:8.1f} → {hb.up_mwh.sum() / 1e3:8.1f} GWh")
    print(f"    extra cost           {ha.extra_cost_eur.sum() / 1e6:8.2f} → {hb.extra_cost_eur.sum() / 1e6:8.2f} M€")
    shed_a = ga[ga.kind == "Load shedding"].dispatch_mw.sum()
    shed_b = gb[gb.kind == "Load shedding"].dispatch_mw.sum()
    print(f"    load shed            {shed_a:8.1f} → {shed_b:8.1f} MWh")
    sync_on = lambda g: g[(g.kind == "Synchronous") & ~g.idle]
    print(f"    synchronous units running per hour   {sync_on(ga).groupby(['date', 'hour']).size().mean():6.1f} → "
          f"{sync_on(gb).groupby(['date', 'hour']).size().mean():6.1f}  (by the anchor schedule; starting units is RD9)")


def rd4(a, b, pf=1.0, tol=1.0):
    print(f"\nRD4 renewable_power_factor = {pf}: A = {a}, B = {b}")
    keys = solved(a).merge(solved(b), on=["date", "hour"])[["date", "hour"]]
    gb = q_table(b, keys)
    res = gb[gb.kind == "Wind and solar"]
    k = np.tan(np.arccos(pf))
    over = (res.dispatch_mvar.abs() - k * res.dispatch_mw.clip(lower=0) - tol).max()
    check(f"wind and solar |Q| ≤ tan(acos({pf}))·P", over <= 0, f"worst excess {max(over, 0):.2f} Mvar")
    ga = q_table(a, keys)
    print(f"  wind and solar reactive power, average |Mvar| per hour: "
          f"{ga[ga.kind == 'Wind and solar'].dispatch_mvar.abs().sum() / len(keys):.0f} → {res.dispatch_mvar.abs().sum() / len(keys):.0f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("what", choices=["logic", "same", "rd2", "rd3", "rd4"])
    ap.add_argument("runs", nargs="*", type=Path)
    ap.add_argument("--pf", type=float, default=1.0, help="rd4: renewable_power_factor of run B")
    a = ap.parse_args()
    if a.what == "logic":
        logic()
    else:
        if len(a.runs) != 2:
            ap.error(f"{a.what} needs two run folders: A B")
        if a.what == "rd4":
            rd4(*a.runs, pf=a.pf)
        else:
            {"same": same, "rd2": rd2, "rd3": rd3}[a.what](*a.runs)
    n_fail = RESULTS.count(False)
    print(f"\n{len(RESULTS) - n_fail} passed, {n_fail} failed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
