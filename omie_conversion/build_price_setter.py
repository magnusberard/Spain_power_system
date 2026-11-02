"""Who set the real Spanish day-ahead price, hour by hour, from OMIE's per-unit bid curves.

For each hour, the price-setting bid is the step whose price equals the Spanish marginal price
(marginalpdbc) and that was only partly matched: the unit offered more at that price than it got
(sell side) or wanted to buy more at that price than it got (buy side). OMIE's curva_pbc_uof
files list every bid step twice, offered ("O") and matched ("C"), for the whole MIBEL market
("MI"); a unit's offered and matched energy at the clearing price are summed over its steps.

  sell side, partly matched  -> that unit set the price (its technology from the unit map)
  buy side, partly matched   -> demand set it (pumping/storage buying, retailers, exports)
  several partly matched     -> the type holding most of the unmatched energy at the price
                                (e.g. hundreds of wind and solar units at ~0 EUR); clear if it holds
                                at least half of it, else "unclear"; n_candidates and "tie" recorded
  no Iberian bid at the price -> the price lies between Iberian bid steps, so it was set outside
                                Iberia through the European market coupling: "Imports" (zone
                                "coupling")

Units are mapped with OMIE_data/unit_technology_map_merged.csv (built by parse_unit_list.py +
build_unit_map.py) into the model's price-setter groups (scripts/publish_run.py, SETTER_GROUPS),
plus "Demand bid". Hours with different Spanish and Portuguese prices only take Spanish units.

    python omie_conversion/build_price_setter.py --year 2024
    python omie_conversion/build_price_setter.py --year 2024 --omie-dir ../OMIE_data

Writes <out> (default Data/OMIE/price_setter_<year>.csv): date, hour (0-23, local clock),
price_es, unit, technology, zone, side (sell/buy), group, n_candidates, tie, clear.
"""
import argparse
import csv
import io
import os
import zipfile
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, ".."))
OMIE_DEFAULT = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")

# the model's groups (scripts/publish_run.py SETTER_GROUPS) + demand
GROUPS = ["Hydro (water value)", "Storage", "CCGT", "Gas turbine & oil", "Coal", "Nuclear",
          "Wind, solar, run-of-river", "CHP group", "Imports", "Shortage / unclear", "Demand bid"]
SELL_TECH = {
    "Hidráulica Generación": 0,
    "Hidráulica de Bombeo Puro": 1, "Almacenamiento Venta": 1, "Híbrida Renov.-Almacenamiento": 1,
    "Ciclo Combinado": 2,
    "Gas": 3,
    "Hulla Antracita": 4, "Carbón de Importación": 4, "Lignito Negro": 4, "Lignito Pardo": 4,
    "Nuclear": 5,
    "RE Mercado Eólica": 6, "RE Tar. CUR Eólica": 6, "RE Mercado Solar Fotovoltáica": 6,
    "RE Tar. CUR Solar Fotovoltáica": 6, "RE Mercado Solar Térmica": 6, "RE Tar. CUR Solar Térmica": 6,
    "Híbrida Renovable": 6,
    "RE Mercado Térmica no Renovab.": 7, "RE Mercado Térmica Renovable": 7, "RE Mercado Hidráulica": 7,
    "RE Tar. CUR Térmica Renovable": 7, "RE Tar. CUR Térmica no Renov.": 7, "RE Mercado Geotérmica": 7,
    "RE Tar. CUR Hidráulica": 7, "Híbrida Renov.-Térmica": 7, "RE Tarifa (Repres.)": 7,
    "RE Tarifa CUR (uof)": 6,   # Portugal's regulated renewables, mostly wind
    "Import. de agentes externos": 8, "Import. de comercializadoras": 8,
}
# buyers that are storage charging count as storage; every other buyer is "Demand bid"
STORAGE_BUY = {"Consumo de bombeo", "Consumo Bombeo Mixto", "Consumo Bombeo Puro", "Almacenamiento Compra"}


def num(x):
    x = x.strip()
    return float(x.replace(".", "").replace(",", ".")) if x else 0.0


def load_units(path):
    m = {}
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m[r["code"]] = (r["zone"], r["technology"])
    return m


def load_prices(omie, d):
    """{OMIE hour (1-based): (price ES, price PT)} for one day."""
    p = os.path.join(omie, "marginalpdbc", f"marginalpdbc_{d:%Y%m%d}.1")
    out = {}
    with open(p, encoding="latin-1") as f:
        for line in f:
            c = line.strip().split(";")
            if len(c) >= 6 and c[0].isdigit() and c[3].isdigit():
                out[int(c[3])] = (float(c[5]), float(c[4]))   # file: ... hour; price PT; price ES
    return out


def clock_hour(k, n):
    """OMIE hour 1..n -> local clock hour 0..23 (23/25-hour days at the clock changes); None = repeated hour."""
    if n == 23:
        return k - 1 if k <= 2 else k
    if n == 25:
        return k - 1 if k <= 3 else (None if k == 4 else k - 2)
    return k - 1


def setter_for_hour(rows, p_es, split, units):
    """rows: [(unit, side, energy, price, status)] for one hour. Returns a dict."""
    offered = defaultdict(float); matched = defaultdict(float)
    for unit, side, e, pr, st in rows:
        if abs(pr - p_es) > 0.005:
            continue
        if split and units.get(unit, ("", ""))[0] != "ZONA ESPAÑOLA":
            continue
        (offered if st == "O" else matched)[(unit, side)] += e
    cands = []
    for key, eo in offered.items():
        em = matched.get(key, 0.0)
        if eo - em > 0.05:
            cands.append((eo - em, em > 0.05, key))
    if not cands:
        # no Iberian bid at the price: set in the coupled European market
        return dict(unit="", technology="", zone="coupling", side="", group=8, n=0, tie=False, clear=True)
    # partly matched steps first (the marginal ones); if none, steps at the price left wholly unmatched
    partly = [c for c in cands if c[1]] or cands
    def grp(unit, side):
        tech = units.get(unit, ("", ""))[1]
        return (1 if tech in STORAGE_BUY else 10) if side == "C" else SELL_TECH.get(tech, 9)
    by_group = defaultdict(float)
    for rem, _, (unit, side) in partly:
        by_group[grp(unit, side)] += rem
    g, eg = max(by_group.items(), key=lambda x: x[1])
    total = sum(by_group.values())
    rem, _, (unit, side) = max((c for c in partly if grp(*c[2]) == g), key=lambda c: c[0])
    zone, tech = units.get(unit, ("", ""))
    clear = g != 9 and eg >= 0.5 * total
    return dict(unit=unit, technology=tech, zone=zone, side="buy" if side == "C" else "sell",
                group=g if clear else 9, n=len(partly), tie=len(partly) > 1, clear=clear)

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--omie-dir", default=OMIE_DEFAULT)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.join(REPO, "Data", "OMIE", f"price_setter_{a.year}.csv")
    units = load_units(os.path.join(a.omie_dir, "unit_technology_map_merged.csv"))
    rows_out = []
    for month in range(1, 13):
        z = zipfile.ZipFile(os.path.join(a.omie_dir, "curva_pbc_uof", f"curva_pbc_uof_{a.year}{month:02d}.zip"))
        for name in sorted(z.namelist()):
            d = date(int(name[14:18]), int(name[18:20]), int(name[20:22]))
            prices = load_prices(a.omie_dir, d)
            by_hour = defaultdict(list)
            for line in io.TextIOWrapper(z.open(name), encoding="latin-1"):
                c = line.split(";")
                if len(c) < 8 or not c[0].isdigit():
                    continue
                by_hour[int(c[0])].append((c[3], c[4], num(c[5]), num(c[6]), c[7]))
            n = len(prices)
            for k in sorted(by_hour):
                h = clock_hour(k, n)
                if h is None or k not in prices:
                    continue
                p_es, p_pt = prices[k]
                s = setter_for_hour(by_hour[k], p_es, abs(p_es - p_pt) > 0.005, units)
                rows_out.append(dict(date=d.isoformat(), hour=h, price_es=p_es, unit=s["unit"],
                                     technology=s["technology"], zone=s["zone"], side=s["side"],
                                     group=GROUPS[s["group"]], n_candidates=s["n"], tie=int(s["tie"]),
                                     clear=int(s["clear"])))
        print(f"{a.year}-{month:02d}: {len(rows_out)} hours so far")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]))
        w.writeheader(); w.writerows(rows_out)
    n = len(rows_out); clear = sum(r["clear"] for r in rows_out)
    print(f"\nwrote {out}: {n} hours, clear {clear} ({100 * clear / n:.1f} %)")
    share = defaultdict(int)
    for r in rows_out:
        share[r["group"]] += 1
    for g, v in sorted(share.items(), key=lambda x: -x[1]):
        print(f"  {g:28s} {100 * v / n:5.1f} %")


if __name__ == "__main__":
    main()
