"""Add the model's redispatch by phase (rd_phases.py) to a package already on the results website, without
republishing it: runs/<id>/data.js gets redispatch.phases; every other byte stays as it was.

    python redispatch_realism/add_rd_phases.py <run folder, or a year run's parent of weekly folders> \
        <spain-model-runs>/runs/<id>/data.js [--check]

--check: build and compare, write nothing.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
from rd_phases import phase_frames, phase_series          # noqa: E402
from publish_run import Hours                              # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("data_js", type=Path)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    text = a.data_js.read_text(encoding="utf-8")
    head, tail = "VIEWER.addRun(", ");\n"
    assert text.startswith(head) and text.endswith(tail), "not a package data.js"
    raw = text[len(head):-len(tail)]
    pkg = json.loads(raw)
    assert json.dumps(pkg, ensure_ascii=False, separators=(",", ":")) == raw, "package does not round-trip exactly"
    hours = Hours(pkg["days"])

    folders = [a.run] if (a.run / "summary.csv").exists() else sorted(p for p in a.run.iterdir() if (p / "summary.csv").exists())
    p1s, rts = [], []
    for f in folders:
        p1, rt = phase_frames(f)
        p1s.append(p1); rts.append(rt)
        print(f"  {f.name}: phase I {0 if p1 is None else len(p1)} h, real time {0 if rt is None else len(rt)} h")
    cat = lambda xs: None if all(x is None for x in xs) else pd.concat([x for x in xs if x is not None]).drop_duplicates(["date", "hour"])
    phases = phase_series(cat(p1s), cat(rts), hours)

    # the pooled series the package already has: the phases should add up to about it (losses and the AC check aside)
    tot = lambda v: sum(x for x in v if x is not None) / 1e3
    rd = pkg["redispatch"]
    print(f"package pooled: up {tot(rd['up']):,.0f} GWh, down {tot(rd['down']):,.0f} GWh")
    for k, b in phases.items():
        print(f"{k}: up {tot(b['up']):,.0f} GWh, down {tot(b['down']):,.0f} GWh, extra cost {tot(b['cost']) / 1e3:,.1f} M€, "
              f"{sum(x is not None for x in b['up'])} hours")
    if a.check:
        return
    rd["phases"] = phases
    a.data_js.write_text(head + json.dumps(pkg, ensure_ascii=False, separators=(",", ":")) + tail, encoding="utf-8")
    new = a.data_js.read_text(encoding="utf-8")
    del json.loads(new[len(head):-len(tail)])["redispatch"]["phases"]          # sanity: it parses
    print(f"wrote {a.data_js} ({len(text) / 1e6:.2f} → {len(new) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
