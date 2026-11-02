"""Technology of every REE programming unit in the redispatch data, from REE's and OMIE's own unit lists.

ree_unit_crosswalk.csv maps REE units to MODEL units and so leaves out wind, solar and portfolio units that have no
single model unit. Phase II targets and offers need the technology of every REE unit, so this table gives each unit
seen in REE's I90 phase I/II results (and, if downloaded, in the offer books of fetch_i90_offers.py):

  1. REE's e·sios list of programming units (archive 82, public): "Tipo de producción". e·sios serves only the
     current list (the same file for any date), so units deregistered since 2024 are missing from it.
  2. OMIE's list of bidding units of 25 June 2024 (LISTA_UNIDADES.PDF, Internet Archive snapshot
     web.archive.org/web/20240625063507/https://www.omie.es/sites/default/files/dados/listados/LISTA_UNIDADES.PDF),
     parsed with omie_conversion/parse_unit_list.py: "TECNOLOGÍA", for units missing from 1.
  3. Neither: technology "unidentified". Not guessed from the unit's name.

Output redispatch_realism/data/ree_unit_technology.csv:
  ree_unit, description, ree_production_type, ree_unit_type, ree_max_mw, omie_technology_2024, group, source

group: CCGT, nuclear, coal, oil, pumped storage (turbine), pumped storage (pump), hydro (reservoir, REE "UGH"),
run-of-river (REE "no UGH"), CHP, wind, solar PV, solar thermal, biomass and waste, hybrid, demand/trading, other,
unidentified.

    python redispatch_realism/build_ree_unit_technology.py --omie-list <omie_units_20240625.csv>
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
URL = ("https://api.esios.ree.es/archives/82/download?date_type=datos"
       "&start_date={d}T00:00:00&end_date={d}T23:59:59&locale=es")
UNIT = "Unidad de Programación"

# REE "Tipo de producción" -> group
REE_GROUP = {
    "Ciclo Combinado": "CCGT", "Nuclear": "nuclear",
    "Hulla antracita": "coal", "Hulla sub-bituminosa": "coal", "Subproductos minería": "coal",
    "Fuel": "oil", "Gas Natural": "other",
    "Turbinación bombeo": "pumped storage (turbine)", "Consumo bombeo": "pumped storage (pump)",
    "Hidráulica UGH": "hydro", "Hidráulica no UGH": "run-of-river",
    "Gas Natural Cogeneración": "CHP", "Derivados del petróleo ó carbón": "CHP",
    "Eólica terrestre": "wind", "Eólica marina": "wind",
    "Solar fotovoltaica": "solar PV", "Solar térmica": "solar thermal",
    "Biomasa": "biomass and waste", "Biogás": "biomass and waste", "Residuos varios": "biomass and waste",
    "Residuos domésticos y similares": "biomass and waste", "Energía residual": "other",
    "Híbrida renovable": "hybrid", "Híbrida renovable-almacenamiento": "hybrid",
    "Híbrida renovable-térmica no renovable": "hybrid",
    "Almacenamiento": "storage", "Porfolio": "portfolio", "Oceano y geotérmica": "other",
    "Importación Francia": "interconnection", "Exportación Francia": "interconnection",
    "Importación Marruecos": "interconnection", "Exportación Marruecos": "interconnection",
    "Exportación Andorra": "interconnection", "Enlace Baleares": "interconnection",
}
# OMIE "TECNOLOGÍA" (June 2024 list, names as printed there) -> group, for units REE's current list no longer has
OMIE_GROUP = {
    "Ciclo Combinado": "CCGT", "Nuclear": "nuclear", "Hulla Antracita": "coal", "Carbón de Importación": "coal",
    "Hidráulica de Bombeo Puro": "pumped storage (turbine)", "Consumo de bombeo": "pumped storage (pump)",
    "Consumo Bombeo Mixto": "pumped storage (pump)", "Consumo Bombeo Puro": "pumped storage (pump)",
    "Hidráulica Generación": "hydro", "RE Mercado Hidráulica": "run-of-river", "RE Tar. CUR Hidráulica": "run-of-river",
    "RE Mercado Eólica": "wind", "RE Tar. CUR Eólica": "wind",
    "RE Mercado Solar Fotovoltáica": "solar PV", "RE Tar. CUR Solar Fotovoltáica": "solar PV",
    "RE Mercado Solar Térmica": "solar thermal", "RE Tar. CUR Solar Térmica": "solar thermal",
    "RE Mercado Térmica no Renovab.": "CHP", "RE Tar. CUR Térmica no Renov.": "CHP",
    "RE Mercado Térmica Renovable": "biomass and waste", "RE Tar. CUR Térmica Renovable": "biomass and waste",
    "RE Mercado Geotérmica": "other", "Almacenamiento Compra": "storage", "Almacenamiento Venta": "storage",
    "Porfolio Produccion Compra": "portfolio", "Porfolio Produccion Venta": "portfolio",
}


def ree_list(path):
    if not path.exists():
        d = pd.Timestamp.today().strftime("%Y-%m-%d")
        path.write_bytes(urllib.request.urlopen(URL.format(d=d), timeout=180).read())
    js = json.loads(path.read_text(encoding="utf-8"))["UnidadesProgramacion"]
    df = pd.DataFrame(js)
    df["ree_unit"] = df["Código de UP"].str.strip()
    return df.drop_duplicates("ree_unit").set_index("ree_unit")


def ree_group(row):
    t = row["Tipo de producción"]
    if t in REE_GROUP:
        return REE_GROUP[t]
    if row.get("Tipo de UP") and row["Tipo de UP"] != "Generación":
        return "demand/trading"
    return "other"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--i90", type=Path,
                    default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90")
    ap.add_argument("--offers", type=Path, help="fetch_i90_offers.py output dir (adds the units of the offer books)")
    ap.add_argument("--ree-list", type=Path,
                    default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "ree_programming_units.json",
                    help="REE e·sios archive 82 JSON; downloaded here if missing")
    ap.add_argument("--omie-list", type=Path, default=HERE / "data" / "omie_units_20240625.csv",
                    help="parse_unit_list.py CSV of OMIE's list of 25 June 2024")
    ap.add_argument("--out", type=Path, default=HERE / "data" / "ree_unit_technology.csv")
    a = ap.parse_args()

    units = set(pd.read_csv(a.i90 / "i90_tc_phase.csv.gz", usecols=[UNIT])[UNIT].str.strip())
    if a.offers and (a.offers / "i90_offers_tc.csv.gz").exists():
        units |= set(pd.read_csv(a.offers / "i90_offers_tc.csv.gz", usecols=[UNIT])[UNIT].str.strip())
    R = ree_list(a.ree_list)
    O = pd.DataFrame()
    if a.omie_list:
        O = pd.read_csv(a.omie_list).assign(code=lambda x: x.code.str.strip(),
                                            technology=lambda x: x.technology.str.replace("\n", " ").str.strip())
        O = O.drop_duplicates("code").set_index("code")

    rows = []
    for u in sorted(units):
        rec = {"ree_unit": u, "description": "", "ree_production_type": "", "ree_unit_type": "", "ree_max_mw": "",
               "omie_technology_2024": "", "group": "unidentified", "source": "none"}
        if u in O.index:
            rec["omie_technology_2024"] = O.at[u, "technology"]
            rec["description"] = O.at[u, "description"]
        if u in R.index:
            r = R.loc[u]
            rec.update(description=r["Descripción larga"], ree_production_type=r["Tipo de producción"],
                       ree_unit_type=r["Tipo de UP"], ree_max_mw=str(r["Potencia máxima MW"]).replace(",", "."),
                       group=ree_group(r), source="REE e·sios UP list (current)")
        elif rec["omie_technology_2024"]:
            rec["group"] = OMIE_GROUP.get(rec["omie_technology_2024"], "demand/trading")
            rec["source"] = "OMIE unit list 25 Jun 2024"
        rows.append(rec)
    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"{a.out}: {len(df)} units; by source: {df.source.value_counts().to_dict()}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
