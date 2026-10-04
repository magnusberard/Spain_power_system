"""Run the Spanish forecast-update pipeline and write Data/ES-format factor files.

This is the repo's entry point to the vendored entsoe-forecasting code (see
UPSTREAM.md; Spanish model paper, section 3.5). It replaces upstream's
scripts/spain/{make_fc,process,omie_post_process}.py, which are hard-coded
to one date range and to debugging plots, with four steps that take their
dates on the command line. The forecasting logic itself is upstream's,
called unchanged.

Steps, run in order (each reads what the previous one wrote):

    download   ENTSO-E actual + day-ahead-forecast load, onshore wind and
               solar for Spain, per calendar year           [needs ENTSOE_TOKEN]
    train      fit the LINEAR model of configs/spain.yaml and predict every
               lead time 1..max_lead_time over the test part of the years
    gates      pick each market gate's forecast (DA, ID2, ID3, CID; BE =
               actual) for each day --from..--to            (upstream main.main)
    normalize  shift solar so its DA equals OMIE's cleared solar, zero tiny
               values, divide every gate by DA -> one CSV per day and resource,
               the Data/ES layout                (upstream omie_post_process)

Usage (PowerShell, from the repo root):

    $env:ENTSOE_TOKEN = "..."            # never in a file
    python forecast_updates/run_spain.py download --years 2022 2023 2024
    python forecast_updates/run_spain.py train
    python forecast_updates/run_spain.py gates --from 2024-01-01 --to 2024-12-30
    python forecast_updates/run_spain.py normalize --from 2024-01-01 --to 2024-12-30

Folders (all outside the repo):

    FORECAST_DATA_DIR   work folder for downloads, forecasts and outputs
                        (default: forecast_data/ next to the repo)
    OMIE_TECH_DIR       OMIE technology reports, as cached by
                        omie_conversion/fetch_omie_technology.py
                        (default: OMIE_data/tecnologias/ next to the repo)
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUTSIDE = os.path.dirname(REPO)          # the folder that holds the repo
ZONE = "ES"
RESOURCES = ["Wind Onshore", "Solar", "load"]
CONFIG = "spain.yaml"


def _setup():
    """Import path for the vendored code, work folder as the current
    directory (upstream reads and writes everything relative to it), and a
    non-interactive plotting backend."""
    sys.path.insert(0, HERE)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("OMIE_TECH_DIR", os.path.join(OUTSIDE, "OMIE_data", "tecnologias"))
    work = os.environ.get("FORECAST_DATA_DIR") or os.path.join(OUTSIDE, "forecast_data")
    os.makedirs(work, exist_ok=True)
    os.chdir(work)
    print(f"work folder: {work}")
    return work


def _config(run_id, years=None):
    from src.load_config import Config
    config = Config(CONFIG)
    config.run_id = run_id
    config.forecasting_model = "LINEAR"          # as upstream's scripts/spain/make_fc.py
    if years:
        config.years = list(years)
    return config


def cmd_download(args):
    from entsoe import EntsoePandasClient
    from src.utils import get_api_key
    from src.entsoe_data_imports import (
        get_capacities, get_generation, get_load_and_forecast, get_wind_solar_forecast)

    key = get_api_key()
    if not key:
        sys.exit('Set the token first, in this terminal only:  $env:ENTSOE_TOKEN = "..."')
    client = EntsoePandasClient(api_key=key)
    years, zones = args.years, [ZONE]
    generation = [r for r in RESOURCES if r != "load"]
    get_load_and_forecast(client, zones, years)
    get_generation(client, zones, years)
    get_wind_solar_forecast(client, zones, years, carriers=generation)
    for carrier in generation:
        get_capacities(client, zones, years, carrier=carrier)

    # Upstream's download helpers print and carry on when a query fails, so
    # check that every file the training step reads actually exists.
    need = [f"data/input_entsoe/load_and_forecasts/{ZONE}/{y}.csv" for y in years]
    need += [f"data/input_entsoe/generation/{ZONE}/{y}.csv" for y in years]
    need += [f"data/input_entsoe/generation_forecasts/{c}/{ZONE}/{y}.csv" for c in generation for y in years]
    need += [f"data/input_entsoe/mean_capacities/{c.replace(' ', '_')}/{ZONE}.csv" for c in generation]
    missing = [p for p in need if not os.path.isfile(p)]
    if missing:
        sys.exit("download incomplete, missing:\n  " + "\n  ".join(missing))
    print(f"download complete: {len(need)} files for {years}")


def cmd_train(args):
    from make_forecasts import make_forecast_loop
    config = _config(args.run_id, args.years)
    print(f"training run '{config.run_id}' on {config.years}, model {config.forecasting_model}")
    make_forecast_loop(config, use_observed_values=True)


def cmd_gates(args):
    import pandas as pd
    from main import main
    config = _config(args.run_id, args.years)
    dates = pd.date_range(start=args.date_from, end=args.date_to, freq="D", tz=args.tz)
    # Lead times 1..12 h for every resource, as upstream's scripts/spain/process.py.
    lead_times = {r: range(1, 13) for r in RESOURCES}
    main(config=config, dates=dates, plotting_flag=args.plots, lead_times_dict=lead_times)


def _to_24_rows(df):
    """The model's 24-row day, by the same rule as
    omie_conversion/convert_omie_to_model_data.py (to_24): a 23-hour day
    repeats its last hour, a 25-hour day drops its first 02:00."""
    import pandas as pd
    n = len(df)
    if n == 24:
        return df
    if n == 23:
        return pd.concat([df, df.iloc[[-1]]])
    if n == 25:
        return pd.concat([df.iloc[:2], df.iloc[3:]])
    raise ValueError(f"unexpected {n} hours in a day")


def _entsoe_da_forecast(run_id, resource):
    """ENTSO-E's published day-ahead forecast, hourly, as saved by `train`."""
    import pandas as pd
    from src.paths import Paths
    s = pd.read_csv(Paths(run_id, resource, ZONE).raw_forecasts / "forecast_series.csv", index_col=0).iloc[:, 0]
    s.index = pd.to_datetime(s.index, utc=True)
    return s


def _capacity_mw(resource, year):
    """ENTSO-E installed capacity of `year` as downloaded; 0 for load."""
    import pandas as pd
    if resource == "load":
        return 0.0
    p = os.path.join("data", "input_entsoe", "capacities", resource.replace(" ", "_"), f"{ZONE}.csv")
    return float(pd.read_csv(p, index_col=0).loc[ZONE, str(year)])


def cmd_normalize(args):
    import pandas as pd
    from src.paths import Paths
    from src.post_process import load_omie_data, normalize_to_day_ahead

    out_root = args.out or os.path.join("normalized_forecasts", args.run_id, ZONE)
    entsoe_da = ({r: _entsoe_da_forecast(args.run_id, r) for r in RESOURCES}
                 if args.method == "entsoe" else {})
    written, failed = 0, []
    for date in pd.date_range(start=args.date_from, end=args.date_to, freq="D"):
        day, month, year = date.day, date.month, date.year
        name = f"{day}_{month}_{year}.csv"
        for resource in RESOURCES:
            src_path = Paths(args.run_id, resource, ZONE).market_forecasts / name
            try:
                gates = pd.read_csv(src_path, index_col=0)
                # Same steps as upstream's scripts/spain/omie_post_process.py:
                if resource == "Solar":
                    omie = load_omie_data(resource, day, month, year)
                    diff_with_omie = gates["DA"] - omie.values
                    gates = gates.subtract(diff_with_omie.values, axis=0)
                gates[gates < 1e-5] = 0.0
                if args.method == "ratio":
                    # upstream: every gate divided by the model's own DA-gate forecast
                    norm = normalize_to_day_ahead(gates)
                else:
                    # Each gate's change from the DA-gate forecast, in MW, divided
                    # by a reference that cannot be near zero: the DA forecast
                    # floored at a share of installed capacity ("floor"), or
                    # ENTSO-E's published day-ahead forecast ("entsoe").
                    da = gates["DA"]
                    if args.method == "floor":
                        ref = da.clip(lower=args.floor_frac * _capacity_mw(resource, year))
                    else:
                        utc = pd.to_datetime(gates.index, utc=True)
                        ref = pd.Series(entsoe_da[resource].reindex(utc).values, index=gates.index)
                    ref = ref.where(ref > 0)                     # 0 or missing -> no update
                    norm = (1 + gates.sub(da, axis=0).div(ref, axis=0)).fillna(1.0).clip(lower=0.0)
                norm = _to_24_rows(norm)
            except Exception as e:                       # report, keep going
                failed.append(f"{date.date()} {resource}: {type(e).__name__}: {e}")
                continue
            out_dir = os.path.join(out_root, resource)
            os.makedirs(out_dir, exist_ok=True)
            norm.to_csv(os.path.join(out_dir, name))
            written += 1
    print(f"wrote {written} files to {os.path.abspath(out_root)}")
    if failed:
        print(f"{len(failed)} failed:")
        for f in failed:
            print("  " + f)


def main_cli():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="step", required=True)

    d = sub.add_parser("download", help="ENTSO-E data for --years (needs ENTSOE_TOKEN)")
    d.add_argument("--years", type=int, nargs="+", required=True)
    d.set_defaults(func=cmd_download)

    for name, func, helptext in (("train", cmd_train, "fit and predict"),
                                 ("gates", cmd_gates, "per-gate forecasts per day")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--run-id", default="spain_linear")
        s.add_argument("--years", type=int, nargs="+",
                       help="override configs/spain.yaml years (training data)")
        s.set_defaults(func=func)
        if name == "gates":
            s.add_argument("--from", dest="date_from", required=True)
            s.add_argument("--to", dest="date_to", required=True)
            s.add_argument("--tz", default="Europe/Madrid",
                           help="day boundaries; the model's days are Spanish local days")
            s.add_argument("--plots", action="store_true", help="upstream's diagnostic plots")

    n = sub.add_parser("normalize", help="DA-normalised factor files, Data/ES layout")
    n.add_argument("--run-id", default="spain_linear")
    n.add_argument("--from", dest="date_from", required=True)
    n.add_argument("--to", dest="date_to", required=True)
    n.add_argument("--out", help="output root (default: normalized_forecasts/<run-id>/ES "
                                 "in the work folder); a resource folder per type below it")
    n.add_argument("--method", choices=("ratio", "floor", "entsoe"), default="ratio",
                   help="ratio: gate / DA-gate forecast (upstream). floor: 1 + (gate - DA) / "
                        "max(DA, floor-frac x installed capacity). entsoe: 1 + (gate - DA) / "
                        "ENTSO-E's published day-ahead forecast")
    n.add_argument("--floor-frac", type=float, default=0.05,
                   help="for --method floor: share of installed capacity (default 0.05)")
    n.set_defaults(func=cmd_normalize)

    args = p.parse_args()
    if getattr(args, "out", None):
        args.out = os.path.abspath(args.out)    # before _setup() changes directory
    _setup()
    args.func(args)


if __name__ == "__main__":
    main_cli()
