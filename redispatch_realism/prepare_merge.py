"""Make a redispatch-realism run's day folders safe to join with scripts/merge_runs.py.

run_days.sh links each day folder's market files (bal_dispatch.csv, da_dispatch.csv,
market_prices.csv) to the source run's weekly chunk, so every day folder holds the whole
week. merge_runs.py concatenates every CSV, which would repeat each week seven times.
This replaces each such file (a link or not) by the rows of that folder's own day.

    python redispatch_realism/prepare_merge.py <run folder>        # e.g. results/y24_base
    python scripts/merge_runs.py <merged folder> <run folder>

Only day folders with summary.csv are touched; running it twice changes nothing.
"""
import os
import sys
from pathlib import Path

import pandas as pd

FILES = ("bal_dispatch.csv", "da_dispatch.csv", "market_prices.csv")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run = Path(sys.argv[1])
    days = sorted(p for p in run.iterdir() if p.is_dir() and (p / "summary.csv").exists())
    if not days:
        sys.exit(f"no finished day folders in {run}")
    changed = 0
    for d in days:
        for name in FILES:
            f = d / name
            if not f.exists():
                continue
            df = pd.read_csv(f)
            own = df[df.date.astype(str) == d.name]
            if len(own) == len(df) and not f.is_symlink():
                continue
            if f.is_symlink():
                f.unlink()                       # do not write through the link into the source run
            own.to_csv(f, index=False)
            changed += 1
    print(f"{len(days)} day folders, {changed} market files cut to their own day")


if __name__ == "__main__":
    main()
