"""Build the unit-specific phase I requirement (fix 2, 2024 only, like RD5's zones).

RD5 asks for enough units per voltage zone, so the model meets a zone with its cheapest members. REE
evidently needs some units themselves: it raised Aboño 2 in phase I on 358 days of 2024 at 181 €/MWh,
while the model met the zone "Soto de Ribera" with CCGTs. A unit REE raised in phase I (I90DIA03,
UPOPVPV, Subir) on at least --min-days days of the year is required in every hour REE raised it.
Nuclear is left out (its schedule is input data, frozen in the model).

    python redispatch_realism/build_unit_requirement.py --i90 ../esios_download/i90 --min-days 183

Writes redispatch_realism/data/phase1_unit_requirement.csv: date, hour, unit_id (model unit), ree_unit.
The threshold (half the year by default) is a judgment of "needed specifically", not fitted.
"""
import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, required=True)
    ap.add_argument("--min-days", type=int, default=183)
    ap.add_argument("--out", type=Path, default=HERE / "data" / "phase1_unit_requirement.csv")
    # which units count as "needed specifically" is chosen on these days only (O14: Jan-Jun); the hours a chosen
    # unit is required stay REE's own, for every day of the year (input data, like the RD5 zone needs)
    ap.add_argument("--select-days", nargs=2, metavar=("FIRST", "LAST"), default=["2024-01-01", "2024-12-31"])
    a = ap.parse_args()
    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv")
    x = x[x.model_unit_id.notna() & (x.technology != "nuclear")][["ree_unit", "model_unit_id", "technology"]]
    ph = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz", low_memory=False,
                     usecols=["date", "hour", "Redespacho", "Sentido", "Unidad de Programación", "mwh"])
    up = ph[(ph.Redespacho == "UPOPVPV") & (ph.Sentido == "Subir") & (ph.mwh > 0)]
    up = up.rename(columns={"Unidad de Programación": "ree_unit"}).merge(x, on="ree_unit")
    sel = up[(up.date >= a.select_days[0]) & (up.date <= a.select_days[1])]
    days = sel.groupby("ree_unit").date.nunique()
    keep = days[days >= a.min_days].index
    req = (up[up.ree_unit.isin(keep)][["date", "hour", "model_unit_id", "ree_unit"]]
           .drop_duplicates().rename(columns={"model_unit_id": "unit_id"}).sort_values(["date", "hour", "unit_id"]))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    req.to_csv(a.out, index=False)
    print(f"{len(keep)} units on >= {a.min_days} days: " + ", ".join(f"{u} ({days[u]} d)" for u in keep.sort_values()))
    print(f"wrote {a.out}: {len(req):,} unit-hours over {req.date.nunique()} days")


if __name__ == "__main__":
    main()
