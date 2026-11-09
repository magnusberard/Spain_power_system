"""Judge the 2035 test week (w35tri, 8-14 Jan, Trinity) before the 2035 year runs. Marks fixed and committed before any
result of that week is seen (9 Nov 2026); the reference is the same week of the 2024 year run (y24rtact).

Marks (all must hold for the 2035 year runs to start with this setup):
  M1 solved     every stage ran: summary.csv exists; real time solved >= 166 of 168 hours (the 2024 setup had one Ipopt
                stop in 504 test hours); no load shed above 1 MWh in the week
  M2 storage    battery + pumped-storage moves are not round trips: their phase I up and down each <= 25 % of phase I's
                total up, and their net per hour, summed, >= 50 % of their gross movement, up + down (moves that cancel
                within the hour are not redispatch)
  M3 reserve    the P.O. 1.5 requirement averages 3,000-5,500 MW (2024's published: 3,683 MW) and the rule starts units
                in at most 80 % of the hours
Reported, no mark (2035 is expected to differ, the figures go to the decision on the grid):
  phase I up and down vs 2024's week, by technology; binding branch-hours in phase I; solar turned down;
  real-time reserve energy and starts; zone-rule units per hour.

    python redispatch_realism/judge_week_2035.py <w35tri week folder> <y24rtact same-week folder>
"""
import sys
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")


def phase1(d):
    p = pd.read_csv(d / "rd_phase1.csv")
    p["d"] = p.phase1_mw - p.da_mw
    p["tech"] = p.fuel.astype(str) + ":" + p.technology.astype(str)
    return p


def main(w, ref):
    w, ref = Path(w), Path(ref)
    ok = {}
    s = pd.read_csv(w / "summary.csv") if (w / "summary.csv").exists() else None
    solved = 0 if s is None else int(s.status.astype(str).str.contains("SOLVED").sum())
    shed = 0.0 if s is None else float(s.load_shed_mw.clip(lower=0).sum())
    ok["M1 solved"] = s is not None and solved >= 166 and shed <= 1.0
    print(f"M1: summary {'yes' if s is not None else 'NO'}, real time solved {solved} / {0 if s is None else len(s)} h, load shed {shed:.1f} MWh")

    p = phase1(w)
    up_tot = p.d.clip(lower=0).sum()
    st = p[p.tech.isin(["Battery:Li-Ion", "Hydro:pumped_storage"])]
    st_up, st_dn = st.d.clip(lower=0).sum(), (-st.d).clip(lower=0).sum()
    net = st.groupby(["date", "hour"]).d.sum().abs().sum()
    ok["M2 storage"] = st_up <= 0.25 * up_tot and st_dn <= 0.25 * up_tot and (st_up + st_dn == 0 or net >= 0.5 * (st_up + st_dn))
    print(f"M2: storage up {st_up/1e3:.1f} / down {st_dn/1e3:.1f} GWh of phase I up {up_tot/1e3:.1f} GWh "
          f"({100*st_up/max(up_tot,1):.0f} % / {100*st_dn/max(up_tot,1):.0f} %); hourly net {net/1e3:.1f} GWh ({100*net/max(st_up + st_dn,1):.0f} % of gross up + down)")

    r = pd.read_csv(w / "rd_reserve.csv")
    req, fired = r.requirement_mw.mean(), (r.started > 0).mean()
    ok["M3 reserve"] = 3000 <= req <= 5500 and fired <= 0.80
    print(f"M3: P.O. 1.5 requirement mean {req:,.0f} MW; units started in {100*fired:.0f} % of hours")

    q = phase1(ref)
    print("\nphase I by technology, GWh (2035 week vs 2024 week): up / down")
    a = p.groupby("tech").d.agg(up=lambda x: x.clip(lower=0).sum() / 1e3, dn=lambda x: (-x).clip(lower=0).sum() / 1e3)
    b = q.groupby("tech").d.agg(up=lambda x: x.clip(lower=0).sum() / 1e3, dn=lambda x: (-x).clip(lower=0).sum() / 1e3)
    t = a.join(b, lsuffix="_2035", rsuffix="_2024", how="outer").fillna(0).round(1).sort_values("up_2035", ascending=False)
    print(t.head(10).to_string())
    print(f"total up {a.up.sum():.1f} vs {b.up.sum():.1f} GWh ({a.up.sum()/max(b.up.sum(),1e-9):.1f}x)")
    for d, lab in ((w, "2035"), (ref, "2024")):
        bb = pd.read_csv(d / "rd_phase1_binding.csv")
        su = pd.read_csv(d / "rd_startups.csv")
        res = su[su.zone.astype(str).str.startswith("reserve")] if "zone" in su else su.iloc[0:0]
        print(f"{lab}: binding branch-hours {len(bb)} ({bb.branch.nunique()} branches); real-time reserve rows {len(res)}")
    print("\n" + ("ALL MARKS PASS" if all(ok.values()) else "NOT ALL PASS: " + ", ".join(k for k, v in ok.items() if not v)))


if __name__ == "__main__":
    main(*sys.argv[1:3])
