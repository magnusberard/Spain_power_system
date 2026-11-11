"""Recompute the traded volume per intraday stage (data.js "traded") of a published run from its week folders,
with publish_run.traded_volume(), and replace only that field in the run's package in spain-model-runs.

Why (11 Nov 2026): runs with phase I inside the market chain counted phase I/II's changes as ID2 trading (ID2
started from DA + phase I, the traded volume measured from da_dispatch.csv), and CID's hours 0-11 were measured
from ID3's unblended forecast instead of ID2's. traded_volume() now measures ID2 from DA + phase I and lets ID3
carry ID2's positions in hours 0-11. A full republish would rebuild every other field from code that has moved
on since the run was published; this touches "traded" only.

    python scripts/update_traded.py <runs-repo>/runs/<run id> <parent folder of the run's week folders>

The week folders need {da,id2,id3,cid}_{dispatch,profiles}.csv, rd_phase1.csv and config_used*.toml.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("publish_run", HERE / "publish_run.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

HEAD, TAIL = "VIEWER.addRun(", ");\n"


def dump(data):
    return HEAD + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + TAIL


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("package", type=Path, help="the run's folder in spain-model-runs/runs")
    ap.add_argument("parts", type=Path, help="folder holding the run's week folders")
    ap.add_argument("--dry-run", action="store_true", help="print old and new averages, write nothing")
    a = ap.parse_args()

    path = a.package / "data.js"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text[len(HEAD):-len(TAIL)])
    if dump(data) != text:
        sys.exit(f"{path} does not round-trip through json unchanged; not touching it")
    days = data["days"]
    di = {d: i for i, d in enumerate(days)}
    new = {st: np.full(24 * len(days), np.nan) for st in ("ID2", "ID3", "CID")}
    weeks = sorted(p for p in a.parts.iterdir() if p.is_dir() and (p / "da_profiles.csv").exists())
    if not weeks:
        sys.exit(f"no week folders with da_profiles.csv in {a.parts}")
    covered = 0
    for w in weeks:
        wd = [d for d in sorted(pd.read_csv(w / "da_profiles.csv", usecols=["date"]).date.unique()) if d in di]
        if not wd:
            continue
        print(f"{w.name}:", end="")
        t = pr.traded_volume(w, pr.Hours(wd))
        if t is None:
            sys.exit(f"{w}: intraday schedules missing")
        for st, vals in t.items():
            for k, d in enumerate(wd):
                new[st][di[d] * 24:(di[d] + 1) * 24] = [np.nan if v is None else v for v in vals[k * 24:(k + 1) * 24]]
        covered += len(wd)
    if covered != len(days):
        sys.exit(f"the week folders cover {covered} of the run's {len(days)} days; not writing")

    old = data["traded"]
    for st in new:
        o = np.array([np.nan if v is None else v for v in old[st]], dtype=float)
        print(f"  {st}: {np.nansum(o) / len(days) / 1e3:6.2f} -> {np.nansum(new[st]) / len(days) / 1e3:6.2f} GWh/day")
    if a.dry_run:
        return
    data["traded"] = {st: pr.r1(v) for st, v in new.items()}
    path.write_text(dump(data), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
