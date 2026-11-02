"""Step 7 (c): a result-blind check of every bus whose connected generation exceeds the capacity of its branches.

Data rule of 2 Nov 2026 (vault decisions, "fixed by whole data class"): input data are checked by whole class, set
before looking at results. This check reads only input data, never a run: for every bus, the installed generation
connected to it (Data/generations.csv, with [redispatch].unit_bus_override applied, as in the redispatch networks)
against the summed rating of its branches, computed as data_preparation.jl does:

  lines         √3 · V · Imax · circuits · line_rating_factor, a/b duplicate rows counted once (dedup_ab_lines)
  transformers  installed_MVA · line_rating_factor; label junctions (sides ≤ 5 % apart) at junction_rating_mw

A flagged bus is not an error by itself (not all plants run at once, and REE grants access under N-1 rules); it is
the list to check against OpenStreetMap and REE, every flagged bus the same way, whichever way a correction moves
the results.

    python redispatch_realism/sweep_bus_capacity.py [--factor 0.8] [--junction-mw 2000] [--min-mw 100]

Writes redispatch_realism/data/sweep_c_bus_capacity.csv (all buses with generation) and prints the flagged ones.
"""
import argparse
import math
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
D = REPO / "Data"


def ab_duplicates(lines):
    cols = ["bus0", "bus1", "voltage", "circuits", "length", "r_per_length", "x_per_length", "c_per_length", "Imax"]
    by = lines.set_index("line_id")
    out = set()
    for lid in by.index:
        m = re.fullmatch(r"(.*)([ab])", lid)
        if not m:
            continue
        twin = m.group(1) + ("b" if m.group(2) == "a" else "a")
        if twin in by.index and all(by.at[lid, c] == by.at[twin, c] for c in cols):
            out.add(lid)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--factor", type=float, default=0.8, help="line_rating_factor (the runs' setting)")
    ap.add_argument("--junction-mw", type=float, default=2000.0)
    ap.add_argument("--min-mw", type=float, default=100.0, help="report buses with at least this much generation")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "sweep_c_bus_capacity.csv")
    a = ap.parse_args()

    buses = pd.read_csv(D / "Bus_Data.csv", encoding="utf-8-sig").set_index("bus_id")
    lines = pd.read_csv(D / "lines.csv")
    lines = lines[lines.dc.astype(str) != "t"]
    dup = ab_duplicates(lines)
    nc = lines.circuits.clip(lower=1) / lines.line_id.isin(dup).map({True: 2.0, False: 1.0})
    lines = lines.assign(mw=math.sqrt(3) * lines.voltage * lines.Imax * nc * a.factor)
    tr = pd.read_csv(D / "transformers_reactance.csv")
    junction = (tr[["voltage_bus0", "voltage_bus1"]].max(axis=1) / tr[["voltage_bus0", "voltage_bus1"]].min(axis=1)) <= 1.05
    tr = tr.assign(mw=(tr.installed_MVA * a.factor).where(~junction, a.junction_mw))

    br = pd.concat([lines[["line_id", "bus0", "bus1", "voltage", "mw"]].rename(columns={"line_id": "branch"}),
                    tr[["transformer_id", "bus0", "bus1", "mw"]].rename(columns={"transformer_id": "branch"})])
    ends = pd.concat([br.assign(bus=br.bus0), br.assign(bus=br.bus1)])
    out_mw = ends.groupby("bus").mw.sum()
    n_br = ends.groupby("bus").branch.nunique()
    largest = ends.groupby("bus").mw.max()

    gen = pd.read_csv(D / "generations.csv")
    ov = pd.read_csv(HERE / "data" / "unit_bus_override.csv").set_index("unit_id").to_bus
    gen["bus"] = gen.unit_id.map(ov).fillna(gen.bus_id)
    g = gen.groupby("bus").agg(gen_mw=("capacity_mw", "sum"), units=("unit_id", "size"),
                               thermal_mw=("capacity_mw", lambda s: s[gen.loc[s.index, "primary_fuel"].isin(
                                   ["Gas", "Coal", "Nuclear", "Oil", "Fuel"])].sum()),
                               names=("name", lambda s: "; ".join(sorted(set(s.dropna().astype(str))))[:120]))
    t = g.join(out_mw.rename("branch_mw")).join(n_br.rename("branches")).join(largest.rename("largest_branch_mw"))
    t[["branch_mw", "branches", "largest_branch_mw"]] = t[["branch_mw", "branches", "largest_branch_mw"]].fillna(0)
    # N-1 view: without its largest branch (REE plans the transmission grid to N-1, P.O. 1.1 / 13.3 [to check])
    t["branch_mw_n1"] = t.branch_mw - t.largest_branch_mw
    t["ratio"] = (t.gen_mw / t.branch_mw).where(t.branch_mw > 0)
    t["voltage"] = buses.voltage.reindex(t.index)
    t["lat"], t["lon"] = buses.y.reindex(t.index).round(3), buses.x.reindex(t.index).round(3)
    t["flag"] = (t.gen_mw > t.branch_mw).map({True: "gen > branches", False: ""})
    t.loc[(t.flag == "") & (t.gen_mw > t.branch_mw_n1), "flag"] = "gen > branches minus largest (N-1)"
    t = t[t.gen_mw >= a.min_mw].sort_values("ratio", ascending=False)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    t.round({c: 1 for c in ("gen_mw", "thermal_mw", "branch_mw", "largest_branch_mw", "branch_mw_n1", "ratio")}).to_csv(a.out)
    f = t[t.flag != ""]
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
    print(f"{len(t)} buses with >= {a.min_mw:.0f} MW of generation; {(t.flag == 'gen > branches').sum()} with more generation than "
          f"branch capacity, {(t.flag != '').sum() - (t.flag == 'gen > branches').sum()} more under N-1 (factor {a.factor}, "
          f"{len(dup)} a/b duplicate rows counted once)")
    print(f[["voltage", "gen_mw", "thermal_mw", "branch_mw", "branch_mw_n1", "branches", "ratio", "flag", "names"]]
          .round(1).to_string())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
