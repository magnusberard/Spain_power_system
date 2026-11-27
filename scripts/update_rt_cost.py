"""Take the AC check's start-ups out of the real-time cost (data.js "redispatch.phases.rt.cost") of a published run,
and replace only that series in the run's package in spain-model-runs.

Why (27 Nov 2026): phase1_ac_check_day! adds the start-up cost of the units it starts to rd_phase1_summary.csv
(phase I/II cost) and also writes them to rd_startups.csv (zone "phase I AC: ..."), which settle.py added to real
time, so they were counted twice. settle.py now skips them. A full republish would rebuild every other field from
code that has moved on since the run was published (cf. update_traded.py); this touches the real-time cost only,
by subtracting each hour's AC-check start-up cost, i.e. exactly what the fixed settle.py no longer adds.

    python scripts/update_rt_cost.py <runs-repo>/runs/<run id> <parent folder of the run's week folders> [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HEAD, TAIL = "VIEWER.addRun(", ");\n"


def dump(data):
    return HEAD + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + TAIL


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("package", type=Path, help="the run's folder in spain-model-runs/runs")
    ap.add_argument("parts", type=Path, help="folder holding the run's week folders")
    ap.add_argument("--dry-run", action="store_true", help="print old and new totals, write nothing")
    a = ap.parse_args()

    path = a.package / "data.js"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[len(HEAD):-len(TAIL)])
    if dump(data) != text:
        sys.exit(f"{path} does not round-trip through json unchanged; not touching it")
    rt = data["redispatch"]["phases"]["rt"]
    days = data["days"]
    di = {d: i for i, d in enumerate(days)}
    cost = np.array([np.nan if x is None else x for x in rt["cost"]], dtype=float)

    rows = []
    for w in sorted(p for p in a.parts.iterdir() if p.is_dir()):
        f = w / "rd_startups.csv"
        if f.exists() and (w / "rd_phase1_summary.csv").exists():
            su = pd.read_csv(f)
            if "zone" in su.columns:
                rows.append(su[su.zone.astype(str).str.startswith("phase I AC")][["date", "hour", "start_cost_eur"]])
    ac = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "hour", "start_cost_eur"])
    ac = ac[ac.date.isin(di)]
    sub = np.zeros(len(cost))
    for r in ac.groupby(["date", "hour"]).start_cost_eur.sum().reset_index().itertuples(index=False):
        sub[di[r.date] * 24 + int(r.hour)] += r.start_cost_eur
    missing = int(((sub > 0) & np.isnan(cost)).sum())
    new = np.where(np.isnan(cost), np.nan, cost - sub)

    h1 = np.array([d < "2024-07-01" for d in days for _ in range(24)])[:len(cost)]
    tot = lambda x, m: np.nansum(x[m]) / 1e6
    print(f"{a.package.name}: AC-check starts {len(ac)}, {sub.sum() / 1e6:.2f} MEUR"
          f" ({missing} of their hours have no real-time cost)")
    for lab, m in (("H1", h1), ("H2", ~h1), ("year", np.ones_like(h1))):
        print(f"  real-time cost {lab}: {tot(cost, m):.2f} -> {tot(new, m):.2f} MEUR")
    if a.dry_run:
        return
    rt["cost"] = [None if np.isnan(x) else round(float(x), 1) for x in new]
    path.write_text(dump(data), encoding="utf-8")
    print(f"  wrote {path}")


if __name__ == "__main__":
    main()
