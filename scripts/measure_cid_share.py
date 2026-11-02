"""Measure how much of its remaining forecast error each source trades in the continuous
intraday market (CID), from REE e·sios, 14 Jun - 31 Dec 2024 — the [participation].cid
shares in config.toml.

Per source (wind, solar = PV + solar thermal, demand) and hour:
    last   = schedule after the last auction for that hour: PHF2 (IDA2) in hours 0-11,
             PHF3 (IDA3) in hours 12-23 (IDA3 trades 12-23 only)
    trade  = PHFC (after continuous trading) - last
    error  = actual - last
    share  = slope of trade on error (least squares), and sum|trade| / sum|error|

From 1 Oct 2024 e·sios gives PHF2/PHF3 as quarter-hour energy (MWh per 15 min), so their
hourly mean is multiplied by 4; PHFC and the actuals are MW per hour throughout.
Caveats: the error also holds REE's real-time curtailment of wind and solar, and cover from
other plants of the same portfolio does not show in the source's own schedule, so the share
is a lower bound. CID trades made before IDA3 sit in PHF3 and count as auction trades.

Download the series first (esios_download/fetch_trading_shares.py, next to the model repo):
    wind 152 / 187 / 1411 / 551, PV 154 / 189 / 1413 / 1295,
    solar thermal 155 / 190 / 1414 / 1294, demand 10144 / 10145 / 10279 / 1293
    (PHF2 / PHF3 / PHFC / actual).

    python scripts/measure_cid_share.py [--dir ../esios_download/hourly]
"""
import argparse
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    "wind": ("152_phf2_wind", "187_phf3_wind", "1411_phfc_wind", "551_real_wind"),
    "pv": ("154_phf2_pv", "189_phf3_pv", "1413_phfc_pv", "1295_real_pv"),
    "solar_thermal": ("155_phf2_solar_thermal", "190_phf3_solar_thermal",
                      "1414_phfc_solar_thermal", "1294_real_solar_thermal"),
    "demand": ("10144_phf2_demand", "10145_phf3_demand", "10279_phfc_demand", "1293_real_demand"),
}
QUARTER_HOUR_FROM = "2024-10-01"


def series(folder, name):
    d = pd.read_csv(os.path.join(folder, name + ".csv"))
    return d.groupby(["date", "hour"]).value.mean()    # the 25-hour clock-change day


def source(folder, names):
    d = pd.DataFrame({k: series(folder, f) for k, f in zip(("phf2", "phf3", "phfc", "act"), names)})
    q = d.index.get_level_values(0) >= QUARTER_HOUR_FROM
    d.loc[q, ["phf2", "phf3"]] *= 4
    return d


def shares(d):
    h = d.index.get_level_values(1)
    d = d.assign(last=np.where(h >= 12, d.phf3, d.phf2)).dropna(subset=["last", "phfc", "act"])
    trade, err = d.phfc - d["last"], d.act - d["last"]
    rows = []
    h, day = d.index.get_level_values(1), d.index.get_level_values(0)
    for label, m in (("all", np.ones(len(d), bool)), ("hours 0-11", h < 12), ("hours 12-23", h >= 12),
                     ("Jun-Sep", day < QUARTER_HOUR_FROM), ("Oct-Dec", day >= QUARTER_HOUR_FROM)):
        t, e = trade[m], err[m]
        rows.append(dict(subset=label, hours=int(m.sum()), slope=np.polyfit(e, t, 1)[0],
                         volume_ratio=t.abs().sum() / e.abs().sum(), corr=np.corrcoef(e, t)[0, 1],
                         mean_abs_error_mw=e.abs().mean(), mean_abs_trade_mw=t.abs().mean()))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", default=os.path.join(HERE, "..", "..", "esios_download", "hourly"))
    folder = ap.parse_args().dir
    src = {k: source(folder, v) for k, v in FILES.items()}
    pv, st = (src.pop(k).fillna({"phf2": 0, "phfc": 0, "act": 0}) for k in ("pv", "solar_thermal"))
    src["solar"] = pv.add(st, fill_value=0)
    pd.set_option("display.width", 140)
    for name in ("wind", "solar", "demand"):
        print(f"\n{name}")
        print(shares(src[name]).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
