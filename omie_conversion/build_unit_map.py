"""
Merge every parsed OMIE unit-list snapshot in OMIE_data/ into one combined
unit -> (zone, technology) lookup table.

A unit code can be REUSED for a different unit years later (confirmed: mixing
in a snapshot from 2022 corrupted results validated exact without it), so
this isn't a blind union. Snapshots close to the target period (2024-2025)
are merged first, oldest-of-those wins ties -- validated exact this way
against both reference days. Any snapshot older than FALLBACK_CUTOFF is only
used to fill in codes the close snapshots don't have at all, never to
override them, since a stale classification is worse than no classification
for a genuinely close (correct) match.

Usage:
    python3 build_unit_map.py

Reads every unit_technology_map_*.csv already produced by parse_unit_list.py
out of ../../OMIE_data/, and writes the merged result to
../../OMIE_data/unit_technology_map_merged.csv.
"""
import csv
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# Normally OMIE_data/ sits next to Spain_power_system/ (two levels up from
# this file). OMIE_DATA_DIR overrides this — needed when running from inside
# a nested git worktree, where the relative path doesn't line up.
OMIE_DATA = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")
OUT = os.path.join(OMIE_DATA, "unit_technology_map_merged.csv")

FALLBACK_CUTOFF = "unit_technology_map_20230101.csv"  # snapshots dated before this are "distant"


def load_snapshot(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["code"]] = {"zone": row["zone"], "technology": row["technology"].replace("\n", " ")}
    return rows


def main():
    all_files = sorted(glob.glob(os.path.join(OMIE_DATA, "unit_technology_map_*.csv")))
    all_files = [f for f in all_files if not f.endswith("_merged.csv")]
    if not all_files:
        raise SystemExit(f"No unit_technology_map_*.csv snapshots found in {OMIE_DATA}")

    primary_files = [f for f in all_files if os.path.basename(f) >= FALLBACK_CUTOFF]
    fallback_files = [f for f in all_files if os.path.basename(f) < FALLBACK_CUTOFF]

    merged = {}
    per_file_new = {}
    for path in primary_files:  # ascending date order: oldest of the close snapshots wins ties
        new_count = 0
        for code, info in load_snapshot(path).items():
            if code not in merged:
                merged[code] = info
                new_count += 1
        per_file_new[os.path.basename(path)] = new_count
    for path in fallback_files:  # gap-filling only -- never overrides a primary-snapshot code
        new_count = 0
        for code, info in load_snapshot(path).items():
            if code not in merged:
                merged[code] = info
                new_count += 1
        per_file_new[os.path.basename(path) + " (fallback, gap-fill only)"] = new_count

    print(f"Merged {len(all_files)} snapshots ({len(primary_files)} primary, {len(fallback_files)} fallback) "
          f"-> {len(merged)} unique unit codes")
    for name, n in per_file_new.items():
        print(f"  {name:55s} contributed {n:5d} new codes")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "zone", "technology"])
        writer.writeheader()
        for code, info in sorted(merged.items()):
            writer.writerow({"code": code, **info})
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
