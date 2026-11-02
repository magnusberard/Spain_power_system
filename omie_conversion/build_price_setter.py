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

--market ida does the same for the European intraday auctions (from 14 Jun 2024): OMIE's
curva_pibc_uof (one file per day and session: 01/02/03 = IDA1/IDA2/IDA3; IDA3 trades hours 12-23)
with marginalpibc for the prices (both fetched by fetch_omie_bid_curves.py --market ida). Simple
block orders (all-or-nothing over several hours) cannot be partly matched, so they are not
candidates. The model's ID2 compares with IDA2 and its ID3 with IDA3.

Groups: wind, solar (PV + thermal) and other renewables (hybrids, Portugal's regulated
renewables "RE Tarifa CUR", technology not given) are separate since 2 Nov 2026; the old joint
group "Wind, solar, run-of-river" keeps its index for packages published before.

    python omie_conversion/build_price_setter.py --year 2024
    python omie_conversion/build_price_setter.py --year 2024 --omie-dir ../OMIE_data
    python omie_conversion/build_price_setter.py --year 2024 --market ida

Writes <out> (default Data/OMIE/price_setter_<year>.csv, --market ida: price_setter_ida_<year>.csv):
date, hour (0-23, local clock), [session,] price_es, unit, technology, zone, side (sell/buy),
group, n_candidates, tie, clear.
"""
import argparse
import csv
import calendar
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
          "Wind, solar, run-of-river", "CHP group", "Imports", "Shortage / unclear", "Demand bid",
          "Wind", "Solar, run-of-river", "Other renewables"]
SELL_TECH = {
    "Hidráulica Generación": 0,
    "Hidráulica de Bombeo Puro": 1, "Almacenamiento Venta": 1, "Híbrida Renov.-Almacenamiento": 1,
    "Ciclo Combinado": 2,
    "Gas": 3,
    "Hulla Antracita": 4, "Carbón de Importación": 4, "Lignito Negro": 4, "Lignito Pardo": 4,
    "Nuclear": 5,
    "RE Mercado Eólica": 11, "RE Tar. CUR Eólica": 11, "RE Mercado Solar Fotovoltáica": 12,
    "RE Tar. CUR Solar Fotovoltáica": 12, "RE Mercado Solar Térmica": 12, "RE Tar. CUR Solar Térmica": 12,
    "Híbrida Renovable": 13,
    "RE Mercado Térmica no Renovab.": 7, "RE Mercado Térmica Renovable": 7, "RE Mercado Hidráulica": 7,
    "RE Tar. CUR Térmica Renovable": 7, "RE Tar. CUR Térmica no Renov.": 7, "RE Mercado Geotérmica": 7,
    "RE Tar. CUR Hidráulica": 7, "Híbrida Renov.-Térmica": 7, "RE Tarifa (Repres.)": 7,
    "RE Tarifa CUR (uof)": 13,   # Portugal's regulated renewables (mostly wind; technology not given)
    "Import. de agentes externos": 8, "Import. de comercializadoras": 8,
}
# buyers that are storage charging count as storage; a generator buying back counts as its own type;
# every other buyer (retailers, consumers, exports) is "Demand bid"
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


def load_prices(omie, d, session=None):
    """{OMIE hour (1-based): (price ES, price PT)} for one day (and intraday session)."""
    p = (os.path.join(omie, "marginalpdbc", f"marginalpdbc_{d:%Y%m%d}.1") if session is None
         else os.path.join(omie, "marginalpibc", f"marginalpibc_{d:%Y%m%d}{session}.1"))
    out = {}
    if not os.path.exists(p):
        return out
    with open(p, encoding="latin-1") as f:
        for line in f:
            c = line.strip().split(";")
            if len(c) >= 6 and c[0].isdigit() and c[3].isdigit():
                out[int(c[3])] = (float(c[5]), float(c[4]))   # file: ... hour; price PT; price ES
    return out


def day_hours(d):
    """23 on the last Sunday of March, 25 on the last Sunday of October, else 24 (Spain)."""
    def last_sunday(m):
        n = calendar.monthrange(d.year, m)[1]
        return max(w for w in range(n - 6, n + 1) if date(d.year, m, w).weekday() == 6)
    if (d.month, d.day) == (3, last_sunday(3)):
        return 23
    return 25 if (d.month, d.day) == (10, last_sunday(10)) else 24


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
    for unit, side, e, pr, st, *rest in rows:
        if abs(pr - p_es) > 0.005 or (rest and rest[0] == "S"):   # block orders cannot be partly matched
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
        if side == "C":   # a buyer: storage charging, a generator buying back (common in the intraday auctions), or demand
            return 1 if tech in STORAGE_BUY else SELL_TECH.get(tech, 10)
        return SELL_TECH.get(tech, 9)
    by_group = defaultdict(float)
    for rem, _, (unit, side) in partly:
        by_group[grp(unit, side)] += rem
    g, eg = max(by_group.items(), key=lambda x: x[1])
    total = sum(by_group.values())
    rem, _, (unit, side) = max((c for c in partly if grp(*c[2]) == g), key=lambda c: c[0])
    zone, tech = units.get(unit, ("", ""))
    clear = g != 9 and eg >= 0.5 * total
    res = sum(by_group.get(k, 0.0) for k in (11, 12, 13))
    if not clear and res >= 0.5 * total:   # wind, solar and other renewables tied at the price (often ~0 EUR): the joint group
        g, clear = 6, True
        rem, _, (unit, side) = max((c for c in partly if grp(*c[2]) in (11, 12, 13)), key=lambda c: c[0])
        zone, tech = units.get(unit, ("", ""))
    return dict(unit=unit, technology=tech, zone=zone, side="buy" if side == "C" else "sell",
                group=g if clear else 9, n=len(partly), tie=len(partly) > 1, clear=clear)

def read_hours(fh):
    """{OMIE hour: [(unit, side, energy, price, status, block)]} from one bid-curve file."""
    by_hour = defaultdict(list)
    for line in io.TextIOWrapper(fh, encoding="latin-1"):
        c = line.split(";")
        if len(c) < 8 or not c[0].isdigit():
            continue
        by_hour[int(c[0])].append((c[3], c[4], num(c[5]), num(c[6]), c[7], c[8].strip() if len(c) > 8 else "N"))
    return by_hour


def setters_for_day(by_hour, prices, n, units, extra):
    rows = []
    for k in sorted(by_hour):
        h = clock_hour(k, n)
        if h is None or k not in prices:
            continue
        p_es, p_pt = prices[k]
        st = setter_for_hour(by_hour[k], p_es, abs(p_es - p_pt) > 0.005, units)
        rows.append(dict(date=extra["date"], hour=h, **{k2: v for k2, v in extra.items() if k2 != "date"},
                         price_es=p_es, unit=st["unit"], technology=st["technology"], zone=st["zone"],
                         side=st["side"], group=GROUPS[st["group"]], n_candidates=st["n"], tie=int(st["tie"]),
                         clear=int(st["clear"])))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--omie-dir", default=OMIE_DEFAULT)
    ap.add_argument("--market", choices=("da", "ida"), default="da")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    ida = a.market == "ida"
    out = a.out or os.path.join(REPO, "Data", "OMIE", f"price_setter{'_ida' if ida else ''}_{a.year}.csv")
    units = load_units(os.path.join(a.omie_dir, "unit_technology_map_merged.csv"))
    rows_out, no_price = [], 0
    folder = "curva_pibc_uof" if ida else "curva_pbc_uof"
    for month in range(1, 13):
        zp = os.path.join(a.omie_dir, folder, f"{folder}_{a.year}{month:02d}.zip")
        if ida and not os.path.exists(zp):
            continue
        z = zipfile.ZipFile(zp)
        for name in sorted(z.namelist()):
            stem = name[len(folder) + 1:]
            d = date(int(stem[0:4]), int(stem[4:6]), int(stem[6:8]))
            session = stem[8:10] if ida else None
            prices = load_prices(a.omie_dir, d, session)
            if not prices:
                no_price += 1
                continue
            extra = dict(date=d.isoformat(), **({"session": int(session)} if ida else {}))
            rows_out += setters_for_day(read_hours(z.open(name)), prices, day_hours(d), units, extra)
        print(f"{a.year}-{month:02d}: {len(rows_out)} hours so far")
    if no_price:
        print(f"{no_price} files without a marginal-price file, skipped")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0]))
        w.writeheader()
        w.writerows(rows_out)
    n = len(rows_out)
    clear = sum(r["clear"] for r in rows_out)
    print(f"\nwrote {out}: {n} hours, clear {clear} ({100 * clear / n:.1f} %)")
    for ses in sorted({r.get("session") for r in rows_out}, key=lambda x: x or 0):
        part = [r for r in rows_out if r.get("session") == ses]
        share = defaultdict(int)
        for r in part:
            share[r["group"]] += 1
        print(f"\n{'IDA' + str(ses) if ses else 'day-ahead'}: {len(part)} hours")
        for g, v in sorted(share.items(), key=lambda x: -x[1]):
            print(f"  {g:28s} {100 * v / len(part):5.1f} %")


if __name__ == "__main__":
    main()
