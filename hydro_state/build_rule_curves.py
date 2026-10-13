"""Seasonal operating envelope (rule curves) for the Spanish reservoir, from REE 2014–2023.

Reservoir operation keeps the stored volume within seasonal guide curves: an upper curve
(flood-control margins, the Spanish "resguardos") and a lower one (minimum reserves for supply).
The pooled reservoir in the mid-term SDDP has no such limits. It therefore holds a wet spring into
autumn (87 % in May, 72 % in Sep–Oct for the aligned policy started from REE's level) or runs
nearly dry in winter (12 % in December when started at 30 %). REE's own fill never left
[25 %, 77 %] in any month of 2014–2023.

The envelope is the per-calendar-month minimum and maximum of REE's total fill over the
CALIBRATION years only (default 2014–2023), so the 2024 test year is not used. REE's monthly
value is the level at the end of the month (the same reading as hydro_state W2). The month-end
values are interpolated linearly to the end of each SDDP stage (weekly from [bellman].bgn_date).
Stages in 2025 use the same calendar months.

    python hydro_state/build_rule_curves.py                        # 2014..2023
    python hydro_state/build_rule_curves.py --from 2014 --to 2023

Writes Data/hydro_state/es_rule_curves_<from>_<to>.csv:
    stage, week_end, lower_fill, upper_fill     (fractions of the reservoir size)
read by midterm_sddp4.jl through [midterm4].es_rule_curve_file.
"""
import argparse
import os
import tomllib

import numpy as np
import pandas as pd

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="y0", type=int, default=2014)
    ap.add_argument("--to", dest="y1", type=int, default=2023)
    ap.add_argument("--config", default=os.environ.get("SPAIN_CONFIG", os.path.join(ROOT, "config.toml")))
    args = ap.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    bgn = pd.Timestamp(cfg["bellman"]["bgn_date"])
    n_stages = int(cfg["midterm4"]["n_stages"])

    ree = pd.read_csv(os.path.join(ROOT, "Data", "hydro_state", "ree_hydro_monthly.csv"))
    year = ree.month.str[:4].astype(int)
    cal = ree[(year >= args.y0) & (year <= args.y1)].copy()
    if cal.empty:
        raise SystemExit(f"no REE months in {args.y0}..{args.y1}")
    cal["m"] = cal.month.str[5:7].astype(int)
    env = cal.groupby("m").fill_total.agg(["min", "max"])
    if len(env) != 12:
        raise SystemExit("calibration years do not cover all 12 months")

    # month-end anchor points spanning the horizon, then linear interpolation to stage ends
    first = (bgn - pd.offsets.MonthEnd(1)).normalize()
    last = bgn + pd.Timedelta(days=7 * n_stages) + pd.offsets.MonthEnd(1)
    anchors = pd.date_range(first, last, freq="ME")
    ax = anchors.view("int64").astype(float)
    lo = np.array([env.loc[d.month, "min"] for d in anchors])
    hi = np.array([env.loc[d.month, "max"] for d in anchors])
    ends = pd.DatetimeIndex([bgn + pd.Timedelta(days=7 * t) for t in range(1, n_stages + 1)])
    ex = ends.view("int64").astype(float)
    out = pd.DataFrame({"stage": range(1, n_stages + 1), "week_end": ends.date,
                        "lower_fill": np.interp(ex, ax, lo), "upper_fill": np.interp(ex, ax, hi)})

    dest = os.path.join(ROOT, "Data", "hydro_state", f"es_rule_curves_{args.y0}_{args.y1}.csv")
    out.to_csv(dest, index=False, float_format="%.4f")
    print(f"Calibration {args.y0}-{args.y1}: monthly fill envelope (%)")
    print((env * 100).round(1).T.to_string())
    print(f"Wrote {n_stages} stages -> {os.path.relpath(dest, ROOT)}")


if __name__ == "__main__":
    main()
