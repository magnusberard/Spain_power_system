"""Day-ahead price of a hydro-state run vs the published baseline run and OMIE, per month.

    python hydro_state/compare_prices.py <run folder> <spain-model-runs>/runs/2024-01-01_2024-offered

<run folder> holds part_*/market_prices.csv from hydro_state/run_da_parallel.sh. The baseline
and the real (OMIE) price are read from the published run's data.js, over the same hours.
Error (MAE) and correlation are given per month and for January–June and July–December
separately, so a setting chosen on one half can be judged on the other.
"""
import glob
import json
import os
import sys

import pandas as pd


def published(run_dir: str) -> pd.DataFrame:
    s = open(os.path.join(run_dir, "data.js"), encoding="utf8").read()
    d = json.loads(s[s.index("(") + 1:s.rindex(")")])
    idx = pd.MultiIndex.from_tuples([(day, h) for day in d["days"] for h in range(24)],
                                    names=["date", "hour"])
    n = len(idx)
    return pd.DataFrame({"base": d["price"]["DA"][:n], "real": d["real_price"][:n]}, index=idx)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    run, pub = sys.argv[1], sys.argv[2]
    parts = sorted(glob.glob(os.path.join(run, "part_*", "market_prices.csv")))
    if not parts:
        sys.exit(f"no part_*/market_prices.csv under {run}")
    new = pd.concat(pd.read_csv(p) for p in parts)
    new = new[new.stage == "DA"].set_index(["date", "hour"]).price_eur_mwh.rename("new")
    df = published(pub).join(new, how="inner").dropna()
    df["month"] = df.index.get_level_values("date").str[:7]

    def stats(g: pd.DataFrame) -> pd.Series:
        return pd.Series({
            "real": g.real.mean(), "base": g.base.mean(), "new": g.new.mean(),
            "MAE_base": (g.base - g.real).abs().mean(), "MAE_new": (g.new - g.real).abs().mean(),
            "corr_base": g.base.corr(g.real), "corr_new": g.new.corr(g.real), "hours": len(g)})

    monthly = df.groupby("month").apply(stats)
    df["half"] = df.month.str[5:7].astype(int).map(lambda m: "Jan-Jun" if m <= 6 else "Jul-Dec")
    halves = df.groupby("half").apply(stats)
    year = stats(df).to_frame("Year").T
    pd.set_option("display.width", 160)
    print(pd.concat([monthly, halves, year]).round(2).to_string())
    dest = os.path.join(run, "compare_prices.csv")
    pd.concat([monthly, halves, year]).to_csv(dest, float_format="%.3f")
    print(f"\nWrote {dest}")


if __name__ == "__main__":
    main()
