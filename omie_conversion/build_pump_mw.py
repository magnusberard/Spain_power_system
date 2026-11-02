"""Pumping power of each pumped-storage plant in the model ([da].pump_limits).

Data/generations.csv gives each pumped-storage plant one capacity, and data_preparation.jl lets
it pump with that same power (pmin = -pmax): 8.2 GW of pumping, against at most 4.45 GW pumped
in any hour of 2024 (REE e·sios 25) and 5.7 GW in the model's own Data/Storage.csv. Real plants
often pump with less than they turbine (only some machines are reversible). This writes the
pumping power per plant; turbining stays at the model's capacity.

Rule (decided 2026-10-28):
  1. JRC Hydro-power database (De Felice et al., CC-BY-4.0,
     https://github.com/energy-modelling-toolkit/hydro-power-database), column pumping_MW, for
     model plants with a clear JRC match (same site, by name and coordinates). A JRC entry that
     covers two model plants (La Muela I + II) is split pro rata on the model's capacity.
  2. Otherwise the model capacity times the size-weighted ratio pumping / model capacity of the
     matched plants (0.63): Aldeadávila II (JRC has no pumping, and its entry includes the
     conventional Aldeadávila I), Bolarque (no pumping in JRC), G0740 "Soutelo 2" (Soutelo or
     Conso: the name and size say Soutelo, the location Conso).
The `check` column holds independent figures (owner, OMIE's highest 2024 pumping bid per
market unit, from OMIE_data/curva_pbc_uof); they are not used.

    python omie_conversion/build_pump_mw.py
    python omie_conversion/build_pump_mw.py --jrc ../jrc_download/jrc-hydro-power-plant-database.csv

Writes Data/pumped_storage_pump_mw.csv: unit_id, name, turbine_mw_model, pump_mw, source,
jrc_name, jrc_turbine_mw, jrc_pump_mw, check.
"""
import argparse
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
JRC = os.path.join(HERE, "..", "..", "jrc_download", "jrc-hydro-power-plant-database.csv")
GEN = os.path.join(HERE, "..", "Data", "generations.csv")
OUT = os.path.join(HERE, "..", "Data", "pumped_storage_pump_mw.csv")

# model unit -> JRC plant name (pumped storage, Spain); None = no usable JRC pumping figure
MATCH = {
    "G0019": "Guillena GUILLENA GR 1 GENERAC",
    "G0070": "Villarino VLLRINO 1G - Almendra (Villarino) Hydroelectric Power Plant Spain",
    "G0095": "Valdecanas",
    "G0104": "Tajo encantada TJE1",
    "G0155": "Muela",
    "G0281": "Muela",
    "G0323": "Torrejon",
    "G0563": "TANES GR,1 GENERAC,",
    "G0656": "Estany gento sallente",
    "G0657": "MORALETS GR 1 GENERAC",
    "G0705": "Montamara",
    "G0853": "Aguayo",
    "G0162": None,   # Aldeadávila II
    "G0302": None,   # Bolarque II
    "G0740": None,   # Soutelo or Conso
}
NAMES = {"G0162": "Aldeadavila II", "G0302": "Bolarque II", "G0853": "Aguayo", "G0705": "Montamara"}
# independent figures, for checking only (OMIE: highest pumping bid of the market unit in 2024;
# several units are a company's group of plants in one basin)
CHECK = {
    "G0155": "Iberdrola 744; OMIE MUEB (La Muela I+II) 1185",
    "G0281": "Iberdrola 549; OMIE MUEB (La Muela I+II) 1185",
    "G0070": "Iberdrola 726; OMIE DUEB (Villarino + Aldeadavila II) 1228",
    "G0162": "Iberdrola 400; OMIE DUEB (Villarino + Aldeadavila II) 1228",
    "G0302": "OMIE UFBB 208 (4 reversible units x 52 MW)",
    "G0740": "JRC Soutelo 78 / Conso 216; OMIE SILB (Sil basin) 412",
    "G0656": "OMIE SLTB 400",
    "G0853": "OMIE AGUB 360",
    "G0104": "OMIE TJEB 315",
    "G0019": "OMIE GUIB 225",
    "G0657": "OMIE MLTB 219",
    "G0095": "OMIE TAJB (Valdecanas + Torrejon) 176",
    "G0323": "OMIE TAJB (Valdecanas + Torrejon) 176",
    "G0563": "OMIE TANB 53",
    "G0705": "",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jrc", default=JRC)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    jrc = pd.read_csv(args.jrc)
    jrc = jrc[(jrc.country_code == "ES") & (jrc.type == "HPHS")].set_index("name")
    gen = pd.read_csv(GEN)
    ps = gen[(gen.primary_fuel == "Hydro") & (gen.technology == "pumped_storage")].set_index("unit_id")
    missing = set(ps.index) ^ set(MATCH)
    if missing:
        raise SystemExit(f"pumped-storage units in generations.csv and MATCH differ: {sorted(missing)}")

    # model capacity behind each JRC plant (La Muela I + II share one JRC entry)
    share_base = ps.capacity_mw.groupby(pd.Series(MATCH)).sum()
    rows = []
    for uid, jname in MATCH.items():
        cap = float(ps.capacity_mw[uid])
        name = NAMES.get(uid, ps.name[uid])
        if jname is not None:
            j = jrc.loc[jname]
            if pd.isna(j.pumping_MW):
                raise SystemExit(f"{uid}: JRC '{jname}' has no pumping_MW")
            pump = float(j.pumping_MW) * cap / share_base[jname]
            rows.append((uid, name, cap, pump, "JRC", jname, j.installed_capacity_MW, j.pumping_MW))
        else:
            rows.append((uid, name, cap, None, "ratio", "", None, None))
    out = pd.DataFrame(rows, columns=["unit_id", "name", "turbine_mw_model", "pump_mw", "source",
                                      "jrc_name", "jrc_turbine_mw", "jrc_pump_mw"])
    jm = out.source == "JRC"
    ratio = out.pump_mw[jm].sum() / out.turbine_mw_model[jm].sum()
    out.loc[~jm, "pump_mw"] = out.turbine_mw_model[~jm] * ratio
    out.loc[~jm, "source"] = f"ratio {ratio:.3f} x model capacity"
    out["pump_mw"] = out.pump_mw.round(1)
    out["check"] = out.unit_id.map(CHECK)
    out = out.sort_values("unit_id")
    out.to_csv(args.out, index=False, lineterminator="\n")

    print(f"{args.out}: {len(out)} plants")
    print(f"  ratio pumping / model capacity (JRC-matched plants): {ratio:.3f}")
    print(f"  pumping {out.pump_mw.sum():.0f} MW (model capacity {out.turbine_mw_model.sum():.0f} MW)")
    print(out[["unit_id", "name", "turbine_mw_model", "pump_mw", "source"]].to_string(index=False))


if __name__ == "__main__":
    main()
