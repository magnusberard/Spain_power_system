"""Hourly upward reserve requirement for step RD7: REE's assigned aFRR upward band, 2024.

Sums I90DIA05 (fetch_i90.py → i90_afrr_band.csv.gz) over units (until 19 Nov 2024) or market
participants (from 20 Nov 2024, Spain's new secondary-regulation market) per hour.

    python redispatch_realism/build_reserve_requirement.py
Writes redispatch_realism/data/reserve_requirement.csv: date, hour, afrr_up_mw, afrr_down_mw.
"""
import argparse
import os
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path,
                    default=Path(os.environ.get("ESIOS_DIR") or HERE.parents[1] / "esios_download") / "i90")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "reserve_requirement.csv")
    a = ap.parse_args()
    b = pd.read_csv(a.i90 / "i90_afrr_band.csv.gz")
    t = b.groupby(["date", "hour", "Sentido"]).mw.sum().unstack("Sentido").fillna(0.0)
    t = t.rename(columns={"Subir": "afrr_up_mw", "Bajar": "afrr_down_mw"}).reset_index()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    t[["date", "hour", "afrr_up_mw", "afrr_down_mw"]].round(1).to_csv(a.out, index=False)
    print(f"{a.out}: {len(t)} hours; upward band mean {t.afrr_up_mw.mean():.0f} MW, "
          f"range {t.afrr_up_mw.min():.0f}–{t.afrr_up_mw.max():.0f} MW")
    print(t.assign(month=t.date.str[:7]).groupby("month").afrr_up_mw.mean().round(0).to_string())


if __name__ == "__main__":
    main()
