"""Build the voltage-zone must-run (step RD5) from REE's 2024 I90 data.

REE starts combined cycles and coal for voltage control in phase I, and does it zone by zone:
on 2 Dec 2024 at night it ran ~12 CCGTs spread over Spain, while our AC model, left to itself
(RD9), started its units all in one region. So the requirement is taken from what REE did:

  1. voltage units: thermal units REE raised in phase I for a voltage cause (I90 Tipo Restricción
     in --causes, default SOT and COT — our reading of REE's undocumented codes: their 2024 total,
     7.1 TWh, is close to e·sios's voltage-control phase I volume, 6.1 TWh), mapped to model units
     with ree_unit_crosswalk.csv;
  2. zones: those plants grouped by distance (single linkage, --radius-km); each zone's members
     are every model thermal unit (CCGT, gas turbine, coal, nuclear) within the radius of a
     voltage plant of the zone;
  3. requirement: in every hour where REE raised a unit of the zone for voltage, the number of
     the zone's thermal units online in REE's viable programme (PDVP, I90DIA01, > --online-mw).
     That is the least REE accepted there; hours without voltage action have no requirement.

    python redispatch_realism/build_voltage_zones.py
    python redispatch_realism/build_voltage_zones.py --radius-km 60 --out redispatch_realism/data

Writes <out>/voltage_zone_units.csv (zone, unit_id, name, fuel, technology, lat, lon,
voltage_unit) and <out>/voltage_zone_requirement.csv (date, hour, zone, n_online, n_raised).
"""
import argparse
import os
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
THERMAL = {("Gas", "Combined_cycle"), ("Gas", "Gas_turbine"), ("Coal", "Coal"), ("Nuclear", "Nuclear")}


def km(a, b):
    (la1, lo1), (la2, lo2) = map(lambda p: (radians(p[0]), radians(p[1])), (a, b))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path, default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90")
    ap.add_argument("--causes", nargs="+", default=["SOT", "COT"])
    ap.add_argument("--radius-km", type=float, default=50.0)
    ap.add_argument("--online-mw", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=HERE / "data")
    a = ap.parse_args()

    x = pd.read_csv(HERE / "ree_unit_crosswalk.csv")
    gen = pd.read_csv(REPO / "Data" / "generations.csv")
    gen = gen[[(f, t) in THERMAL for f, t in zip(gen.primary_fuel, gen.technology)]]
    ph = pd.read_csv(a.i90 / "i90_tc_phase.csv.gz")
    up = ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir") & ph["Tipo Restricción"].isin(a.causes)]
    up = up.merge(x[["ree_unit", "model_unit_id"]], left_on="Unidad de Programación", right_on="ree_unit")
    up = up.dropna(subset=["model_unit_id"])
    vunits = gen[gen.unit_id.isin(up.model_unit_id.unique())]
    print(f"voltage units: {len(vunits)} model units from {up.ree_unit.nunique()} REE units "
          f"({up.mwh.sum() / 1e3:,.0f} GWh of phase I up, causes {a.causes})")

    # 2. zones: single linkage over the voltage plants
    pts = list(zip(vunits.unit_id, zip(vunits.y, vunits.x)))
    zone = {u: i for i, (u, _) in enumerate(pts)}
    for i, (u, p) in enumerate(pts):
        for v, q in pts[i + 1:]:
            if km(p, q) <= a.radius_km and zone[u] != zone[v]:
                old, new = zone[v], zone[u]
                zone = {k: (new if z == old else z) for k, z in zone.items()}
    mwh = up.groupby("model_unit_id").mwh.sum()
    names = {}
    for z in set(zone.values()):
        members = [u for u in zone if zone[u] == z]
        top = max(members, key=lambda u: mwh.get(u, 0))
        names[z] = str(gen.set_index("unit_id").loc[top, "name"]).replace(" power station", "").split(" (")[0]
    rows = []
    for _, g in gen.iterrows():
        near = [zone[u] for u, p in pts if km((g.y, g.x), p) <= a.radius_km]
        if near:
            z = min(near, key=lambda z: min(km((g.y, g.x), p) for u, p in pts if zone[u] == z))
            rows.append(dict(zone=names[z], unit_id=g.unit_id, name=g["name"], fuel=g.primary_fuel,
                             technology=g.technology, lat=g.y, lon=g.x, voltage_unit=g.unit_id in zone))
    zu = pd.DataFrame(rows).sort_values(["zone", "unit_id"])

    # 3. requirement: online thermal units of the zone in REE's PDVP, in hours with voltage action
    pv = pd.read_csv(a.i90 / "i90_pdvp.csv.gz")
    pv = pv[pv.mwh > a.online_mw].merge(x[["ree_unit", "model_unit_id"]], left_on="Unidad de Programación", right_on="ree_unit")
    pv = pv.merge(zu[["zone", "unit_id"]], left_on="model_unit_id", right_on="unit_id")
    online = pv.groupby(["date", "hour", "zone"]).model_unit_id.nunique().rename("n_online")
    act = up.merge(zu[["zone", "unit_id"]], left_on="model_unit_id", right_on="unit_id")
    raised = act.groupby(["date", "hour", "zone"]).model_unit_id.nunique().rename("n_raised")
    req = pd.concat([raised, online], axis=1).dropna(subset=["n_raised"]).fillna({"n_online": 0}).astype(int).reset_index()

    a.out.mkdir(parents=True, exist_ok=True)
    zu.to_csv(a.out / "voltage_zone_units.csv", index=False)
    req.to_csv(a.out / "voltage_zone_requirement.csv", index=False)
    print(f"{zu.zone.nunique()} zones, {len(zu)} member units; requirement rows {len(req)} "
          f"({req[['date', 'hour']].drop_duplicates().shape[0]} hours)")
    s = req.groupby("zone").agg(hours=("hour", "size"), n_online=("n_online", "mean"), n_raised=("n_raised", "mean"))
    s["members"] = zu.groupby("zone").size()
    print(s.round(1).sort_values("hours", ascending=False).to_string())


if __name__ == "__main__":
    main()
