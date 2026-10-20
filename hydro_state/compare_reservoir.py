"""Compare the mid-term hydro path with REE (and OMIE), baseline vs hydro-state variant.

The reservoir level is the first test of the hydro-state fix: it is a physical quantity that
no part of the fix is fitted to (only its value on the start date is an input), so if the
simulated path tracks REE through the year, the fix works for the right reason. Monthly hydro
release against OMIE comes second, price third (from the market-chain runs, not here).

Errors are reported separately for January–June and July–December, so a setting chosen while
looking at one half can be judged on the other.

Usage:
    python hydro_state/compare_reservoir.py                         # label "observed"
    python hydro_state/compare_reservoir.py --label observed \
        --omie ../spain-model-runs/reference/real_hourly_2024.csv.gz

Reads  results/hydro_state/baseline_{Volume,TurbineSchedule}.csv   (baseline path, written by
       Data/hydro_state/{Volume,TurbineSchedule}_<label>.csv       midterm_observed.jl)
       Data/hydro_state/ree_hydro_monthly.csv
       Data/smspp_in/SS_SeasonalStorage.csv                        (ES reservoir size)
Writes results/hydro_state/compare_<label>.csv
"""
import argparse
import os

import pandas as pd

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BGN = pd.Timestamp("2024-01-01")
YEAR = "2024"


def p(*parts: str) -> str:
    return os.path.join(ROOT, *parts)


def es_vmax() -> float:
    ss = pd.read_csv(p("Data", "smspp_in", "SS_SeasonalStorage.csv"), sep=";")
    return float(ss.loc[ss.Zone == "ES", "MaxVolume"].iloc[0])


def monthly_path(volume_csv: str, turbine_csv: str, vmax: float) -> pd.DataFrame:
    """End-of-month ES fill and monthly ES reservoir release [GWh] from hourly files."""
    vol = pd.read_csv(volume_csv)
    tur = pd.read_csv(turbine_csv)
    t = BGN + pd.to_timedelta(vol.Timestep, unit="h")
    v = pd.Series(vol["Hydro|Reservoir_ES_0"].values, index=t)
    # level at 00:00 on the 1st of the next month = end of this month
    month_starts = pd.date_range(BGN, periods=13, freq="MS")
    fill = {(m - pd.Timedelta(hours=1)).strftime("%Y-%m"): v.get(m, float("nan")) / vmax
            for m in month_starts[1:]}
    rel = pd.Series(tur.Turbine_ES_MW.values, index=BGN + pd.to_timedelta(tur.Timestep, unit="h"))
    rel = rel[rel.index < month_starts[-1]].groupby(rel.index[rel.index < month_starts[-1]]
                                                    .strftime("%Y-%m")).sum() / 1e3
    return pd.DataFrame({"fill": pd.Series(fill), "release_gwh": rel})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--label", default="observed")
    ap.add_argument("--omie", default=None,
                    help="real_hourly_2024.csv.gz from spain-model-runs/reference (optional)")
    args = ap.parse_args()

    vmax = es_vmax()
    # The baseline path of the 2026-10-13 runs (written to results/ by the first run, committed as
    # Data/hydro_state/reference_baseline_*.csv so comparisons stay reproducible on a fresh clone).
    def base_file(stem: str) -> str:
        r = p("results", "hydro_state", f"baseline_{stem}.csv")
        return r if os.path.exists(r) else p("Data", "hydro_state", f"reference_baseline_{stem}.csv")
    base = monthly_path(base_file("Volume"), base_file("TurbineSchedule"), vmax)
    var = monthly_path(p("Data", "hydro_state", f"Volume_{args.label}.csv"),
                       p("Data", "hydro_state", f"TurbineSchedule_{args.label}.csv"), vmax)
    ree = pd.read_csv(p("Data", "hydro_state", "ree_hydro_monthly.csv"), index_col="month")
    ree = ree.loc[ree.index.str.startswith(YEAR)]

    out = pd.DataFrame({
        "ree_fill": ree.fill_total,
        "base_fill": base.fill,
        f"{args.label}_fill": var.fill,
        "ree_producible_gwh": ree.producible_gwh,
        "base_release_gwh": base.release_gwh,
        f"{args.label}_release_gwh": var.release_gwh,
    })
    if args.omie:
        om = pd.read_csv(args.omie)
        out["omie_hydro_gwh"] = om.groupby(om.date.str[:7]).omie_Hydro.sum() / 1e3

    out = out.loc[out.index.str.startswith(YEAR)]
    os.makedirs(p("results", "hydro_state"), exist_ok=True)
    dest = p("results", "hydro_state", f"compare_{args.label}.csv")
    out.to_csv(dest, float_format="%.4f")

    pd.set_option("display.width", 160)
    show = out.copy()
    for c in show.columns:
        if c.endswith("_fill"):
            show[c] = (100 * show[c]).round(1)
    print(show.round(0).to_string())

    print("\nReservoir fill, mean absolute error vs REE (percentage points):")
    for half, months in (("Jan-Jun", [f"{YEAR}-{m:02d}" for m in range(1, 7)]),
                         ("Jul-Dec", [f"{YEAR}-{m:02d}" for m in range(7, 13)])):
        sub = out.loc[out.index.isin(months)]
        e_b = (sub.base_fill - sub.ree_fill).abs().mean() * 100
        e_v = (sub[f"{args.label}_fill"] - sub.ree_fill).abs().mean() * 100
        print(f"  {half}: baseline {e_b:5.1f}   {args.label} {e_v:5.1f}")
    if args.omie:
        print("\nMonthly release vs OMIE hydro (OMIE includes run-of-river and pumped output,")
        print("so compare the seasonal shape, not the level): correlation")
        for c in ("base_release_gwh", f"{args.label}_release_gwh"):
            print(f"  {c}: {out[c].corr(out.omie_hydro_gwh):.2f}")
    print(f"\nWrote {os.path.relpath(dest, ROOT)}")


if __name__ == "__main__":
    main()
