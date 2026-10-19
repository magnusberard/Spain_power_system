"""Download REE's monthly hydro reserves and producible hydro energy (REData, no token).

These are the observed hydrological STATE and INFLOW the hydro-state workflow is allowed to use
(see hydro_state/README.md): the reservoir level is a measured stock, and the producible is the
energy the natural inflows could have generated. Neither is a market outcome, so neither can
leak real hydro dispatch or prices into the model.

Series (REData API, apidatos.ree.es, open):
  generacion/reservas-hidroelectricas  total / annual / multi-year reservoirs, GWh and fill
  generacion/producible-hidraulico     producible GWh, producible index (vs the historical
                                       mean) and its exceedance probability

REData returns monthly values only (the daily request comes back empty). Values arrive scaled
by 1000 (GWh * 1000, index * 1000, percent * 1000); they are divided back here.

Usage:
    python hydro_state/fetch_ree_hydro.py                       # 2014-01 .. 2024-12
    python hydro_state/fetch_ree_hydro.py --from 2023-01 --to 2024-12

Writes Data/hydro_state/ree_hydro_monthly.csv with one row per month:
    month, reserves_total_gwh, fill_total, reserves_annual_gwh, fill_annual,
    reserves_multiyear_gwh, fill_multiyear, producible_gwh, producible_index,
    producible_exceedance_pct
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "Data", "hydro_state", "ree_hydro_monthly.csv")
API = "https://apidatos.ree.es/es/datos/generacion/{widget}"
SCALE = 1000.0

# REData title prefix → (value column, fill column); fill is None for producible series
RESERVES = {
    "Total reservas": ("reserves_total_gwh", "fill_total"),
    "Reservas embalses anuales": ("reserves_annual_gwh", "fill_annual"),
    "Reservas embalses hiperanuales": ("reserves_multiyear_gwh", "fill_multiyear"),
}
PRODUCIBLE = {
    "Producible hidraulico": "producible_gwh",
    "Índice de producible": "producible_index",
    "Probabilidad de ser superado": "producible_exceedance_pct",
}


def fetch(widget: str, year: int) -> list:
    """One calendar year of a REData widget, monthly. REData limits a request to one year."""
    params = {"start_date": f"{year}-01-01T00:00", "end_date": f"{year}-12-31T23:59",
              "time_trunc": "month"}
    url = API.format(widget=widget) + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8")).get("included", [])


def series_by_title(included: list, mapping: dict) -> dict:
    out = {}
    for inc in included:
        title = inc["attributes"]["title"]
        for prefix, cols in mapping.items():
            if title.startswith(prefix):
                out[prefix] = (cols, inc["attributes"].get("values") or [])
    missing = set(mapping) - set(out)
    if missing:
        sys.exit(f"REData response lacks series {sorted(missing)}; titles seen: "
                 f"{[i['attributes']['title'] for i in included]}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="start", default="2014-01", help="first month, YYYY-MM")
    ap.add_argument("--to", dest="end", default="2024-12", help="last month, YYYY-MM")
    args = ap.parse_args()
    y0, y1 = int(args.start[:4]), int(args.end[:4])

    rows: dict = {}
    for year in range(y0, y1 + 1):
        for prefix, (cols, values) in series_by_title(
                fetch("reservas-hidroelectricas", year), RESERVES).items():
            val_col, fill_col = cols
            for v in values:
                m = v["datetime"][:7]
                rows.setdefault(m, {})[val_col] = v["value"] / SCALE
                rows[m][fill_col] = v.get("percentage")
        for prefix, (col, values) in series_by_title(
                fetch("producible-hidraulico", year), PRODUCIBLE).items():
            for v in values:
                rows.setdefault(v["datetime"][:7], {})[col] = v["value"] / SCALE
        print(f"{year}: {sum(1 for m in rows if m.startswith(str(year)))} months")

    df = pd.DataFrame.from_dict(rows, orient="index").rename_axis("month").sort_index()
    df = df.loc[(df.index >= args.start) & (df.index <= args.end)]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, float_format="%.4f")
    print(f"Wrote {len(df)} months -> {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
