"""
Convert raw OMIE per-unit day-ahead schedule data (pdbf) into the model's
Data/ES_old/{load,Solar,Wind}/<d>_<m>_<yyyy>.csv format, for any day of 2024.

Validated (see project chat history / commit message) to reproduce the two
hand-checked reference days (2024-07-08, 2024-12-02) to within rounding:
  - Wind, Solar (PV + thermal): EXACT match against Data/OMIE/actual_generation_*.csv
  - Load: domestic generation (8 OMIE technology categories, from pdbf + the
    unit-technology map) + the day-ahead scheduled cross-border import terms
    (from da_exchange_2024.csv), clamped at 0 -- also an EXACT match.

Formula:
    domestic = Coal + Nuclear + CCGT + Hydro + Wind + SolarThermal + SolarPV
               + Cogeneration/Waste/SmallHydro
    load  = domestic + max(0, FR->ES day-ahead exchange) + max(0, PT->ES day-ahead exchange)
    wind  = Wind
    solar = SolarThermal + SolarPV

Usage:
    python3 convert_omie_to_model_data.py --validate            # check the 2 reference days
    python3 convert_omie_to_model_data.py --date 2024-03-15      # one day, prints only
    python3 convert_omie_to_model_data.py --all                  # writes all 362 days
    python3 convert_omie_to_model_data.py --all --out DIR        # write elsewhere (dry-run friendly)
"""
import argparse
import csv
import os
from collections import defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OMIE_DATA = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")
ENTSOE_DIR = os.environ.get("ENTSOE_DIR") or os.path.join(HERE, "..", "..", "entsoe_download")
REPO_DATA = os.path.join(HERE, "..", "Data")

UNIT_MAP_CSV = os.path.join(OMIE_DATA, "unit_technology_map_merged.csv")
EXCHANGE_CSV = os.path.join(ENTSOE_DIR, "da_exchange_2024.csv")
ES_OLD_DIR = os.path.join(REPO_DATA, "ES_old")
OMIE_REF_DIR = os.path.join(REPO_DATA, "OMIE")

# Days excluded from the run: the [ES] forecast-factor files don't cover
# these 3, and per project decision they're simply skipped rather than
# generated/guessed at.
EXCLUDED_DATES = {"2024-01-01", "2024-12-30", "2024-12-31"}

# The 8 raw OMIE "TECNOLOGÍA" categories, grouped into the technology buckets
# that reproduce Data/OMIE/actual_generation_*.csv exactly (validated against
# both 2024-07-08 and 2024-12-02, all 24 hours, to 0.000 MW).
TECH_GROUPS = {
    "coal":         ["Hulla Antracita", "Carbón de Importación"],
    "nuclear":      ["Nuclear"],
    "ccgt":         ["Ciclo Combinado"],
    "hydro":        ["Hidráulica Generación", "Hidráulica de Bombeo Puro"],
    "wind":         ["RE Mercado Eólica", "RE Tar. CUR Eólica"],
    "solar_th":     ["RE Mercado Solar Térmica", "RE Tar. CUR Solar Térmica"],
    "solar_pv":     ["RE Mercado Solar Fotovoltáica", "RE Tar. CUR Solar Fotovoltáica"],
    "cogen":        ["RE Mercado Térmica no Renovab.", "RE Mercado Térmica Renovable",
                      "RE Mercado Hidráulica", "RE Tar. CUR Térmica Renovable",
                      "RE Tar. CUR Térmica no Renov.", "RE Mercado Geotérmica",
                      "RE Tar. CUR Hidráulica"],
}
TECH_TO_GROUP = {tech: g for g, techs in TECH_GROUPS.items() for tech in techs}


def load_unit_map():
    m = {}
    with open(UNIT_MAP_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m[r["code"]] = (r["zone"], r["technology"])
    return m


def load_exchange():
    """(date_str, delivery_time) -> (fr_clamped, pt_clamped)."""
    ex = {}
    with open(EXCHANGE_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            ex[(r["date"], int(r["delivery_time"]))] = (
                float(r["fr_import_clamped"]), float(r["pt_import_clamped"]))
    return ex


def pdbf_path(d):
    return os.path.join(OMIE_DATA, f"pdbf_{d.year}{d.month:02d}", f"pdbf_{d.year}{d.month:02d}{d.day:02d}.1")


def to_24(values_by_hour, n):
    """OMIE hour labels are 1-based, 23/24/25 of them depending on DST (n comes
    from the whole day's file, not this one technology group -- some groups
    have no line at all for hours they produced zero, so a group's own dict
    can't be used to infer how many hours the day actually had)."""
    v = [values_by_hour.get(h, 0.0) for h in range(1, n + 1)]
    if n == 24:
        return v
    if n == 23:            # spring forward: repeat the last hour
        return v + [v[-1]]
    if n == 25:             # autumn back: drop the repeated hour (hour 3)
        return v[:2] + v[3:]
    raise ValueError(f"unexpected {n} hours in pdbf file")


# OMIE's own "Energía horaria por tecnologías" report (INT_PBC_TECNOLOGIAS_H,
# fetched by fetch_omie_technology.py into OMIE_data/tecnologias/) gives the
# national total per technology, per hour, already aggregated by OMIE itself
# -- no per-unit lookup needed. Column names map 1:1 onto TECH_GROUPS; the 3
# columns not listed here (FUEL-GAS, AUTOPRODUCTOR, ALMACENAMIENTO) are the
# same 3 categories the reconstruction formula already excludes as
# unmodeled/negligible (see "Known gaps in load" in the method doc) -- and
# the two import columns aren't used here either, since the load formula's
# import term comes from ENTSO-E's day-ahead scheduled exchange, not OMIE's.
TECH_REPORT_COLUMNS = {
    "coal":     "CARBÓN",
    "nuclear":  "NUCLEAR",
    "ccgt":     "CICLO COMBINADO",
    "hydro":    "HIDRÁULICA",
    "wind":     "EÓLICA",
    "solar_th": "SOLAR TÉRMICA",
    "solar_pv": "SOLAR FOTOVOLTAICA",
    "cogen":    "COGENERACIÓN/RESIDUOS/MINI HIDRA",
}
TECH_REPORT_DIR = os.path.join(OMIE_DATA, "tecnologias")


def tech_report_path(d):
    return os.path.join(TECH_REPORT_DIR, f"tecnologias_{d.year}{d.month:02d}{d.day:02d}.txt")


def _es_number(x):
    x = x.strip()
    if x == "":
        return 0.0
    return float(x.replace(".", "").replace(",", "."))


def reconstruct_day(d, unit_map=None):
    """Returns (group_totals, unmapped_mw, n_unmapped) for one date.
    group_totals: {group_name: [24 hourly MW]}.

    Sourced from OMIE's own pre-aggregated technology report -- exact match
    (0.0000 MW) verified against Data/OMIE/actual_generation_July_8.csv, all
    24 hours, all 13 columns (see project chat history). unmapped_mw/
    n_unmapped are always (0.0, 0) here: there's no per-unit lookup step for
    this method to fail on. `unit_map` is accepted but unused, kept only so
    existing callers don't need updating.
    """
    path = tech_report_path(d)
    with open(path, encoding="latin-1") as f:
        lines = [ln.rstrip("\n").rstrip("\r") for ln in f]
    header = lines[2].split(";")
    col_idx = {name: i for i, name in enumerate(header)}

    by_group_hour = defaultdict(dict)
    max_hour = 0
    for line in lines[3:]:
        parts = line.split(";")
        if len(parts) < 3 or parts[1].strip() == "":
            continue
        hour = int(parts[1])
        if hour > max_hour:
            max_hour = hour
        for group, col_name in TECH_REPORT_COLUMNS.items():
            idx = col_idx.get(col_name)
            val = _es_number(parts[idx]) if idx is not None and idx < len(parts) else 0.0
            by_group_hour[group][hour] = val

    group_totals = {g: to_24(by_group_hour.get(g, {}), max_hour) for g in TECH_REPORT_COLUMNS}
    return group_totals, 0.0, 0


def build_series(d, unit_map, exchange):
    group_totals, unmapped_mw, n_unmapped = reconstruct_day(d, unit_map)
    domestic = [sum(group_totals[g][h] for g in TECH_GROUPS) for h in range(24)]
    wind = group_totals["wind"]
    solar = [group_totals["solar_th"][h] + group_totals["solar_pv"][h] for h in range(24)]

    d_str = d.isoformat()
    load = []
    for h in range(24):
        fr, pt = exchange.get((d_str, h), (0.0, 0.0))
        load.append(domestic[h] + fr + pt)

    return {"load": load, "Wind": wind, "Solar": solar}, unmapped_mw, n_unmapped


def es_filename(d):
    return f"{d.day}_{d.month}_{d.year}.csv"


def write_series(series, d, out_dir):
    for resource, values in series.items():
        outdir = os.path.join(out_dir, resource)
        os.makedirs(outdir, exist_ok=True)
        with open(os.path.join(outdir, es_filename(d)), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["delivery_time", "-12"])
            for h in range(24):
                w.writerow([h, values[h]])


def validate(unit_map, exchange):
    target_cols = {"load": None, "Wind": "Wind", "Solar": None}  # handled specially below
    ref_files = {"2024-07-08": "actual_generation_July_8.csv", "2024-12-02": "actual_generation_Dec_2.csv"}
    all_ok = True
    for d_str, ref_name in ref_files.items():
        d = date.fromisoformat(d_str)
        series, unmapped_mw, n_unmapped = build_series(d, unit_map, exchange)

        ref = {}
        with open(os.path.join(OMIE_REF_DIR, ref_name), encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                ref[int(row["Hour"])] = row

        ref_load = [sum(float(row[c]) for c in row if c != "Hour") for row in
                    [ref[h] for h in range(1, 25)]]
        ref_wind = [float(ref[h]["Wind"]) for h in range(1, 25)]
        ref_solar = [float(ref[h]["Solar Thermal"]) + float(ref[h]["Solar Photovoltaic"])
                     for h in range(1, 25)]

        print(f"\n{d_str}:")
        for name, calc, target in [("load", series["load"], ref_load),
                                    ("Wind", series["Wind"], ref_wind),
                                    ("Solar", series["Solar"], ref_solar)]:
            diffs = [abs(c - t) for c, t in zip(calc, target)]
            maxdiff = max(diffs)
            # Daily energy share, not worst-single-hour share: a handful of
            # unmapped units concentrated in a few hours can look like a large
            # local percentage even though their share of the whole day's
            # energy is tiny -- energy share is what we actually characterized
            # and accepted this residual by (< 0.5% of the day, both known
            # sources: unmapped units and the unmodeled Fuel-Gas/Self-producer
            # /Storage terms, both ~0 on both study days).
            energy_pct = 100 * sum(diffs) / sum(target) if sum(target) else 0
            if maxdiff < 0.5:
                status = "EXACT"
            elif energy_pct < 1.0:
                status = "OK (known residual)"
            else:
                status = "MISMATCH"
                all_ok = False
            print(f"  {name:6s} max diff = {maxdiff:8.3f} MW, energy share = {energy_pct:5.3f}%  [{status}]")
        print(f"  unmapped units: {n_unmapped} ({unmapped_mw:.1f} MW total impact)")

    print("\n" + ("ALL VALIDATION CHECKS PASSED" if all_ok else "VALIDATION FAILED -- see above"))
    return all_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--from-date", default="2024-01-01", help="first date for --all (inclusive)")
    ap.add_argument("--to-date", default="2024-12-31", help="last date for --all (inclusive)")
    ap.add_argument("--out", default=ES_OLD_DIR)
    args = ap.parse_args()

    unit_map = load_unit_map()
    exchange = load_exchange()

    if args.validate:
        ok = validate(unit_map, exchange)
        raise SystemExit(0 if ok else 1)

    if args.date:
        d = date.fromisoformat(args.date)
        series, unmapped_mw, n_unmapped = build_series(d, unit_map, exchange)
        print(f"{args.date}: load[0]={series['load'][0]:.1f}  wind[0]={series['Wind'][0]:.1f}  "
              f"solar[0]={series['Solar'][0]:.1f}  unmapped={n_unmapped} units ({unmapped_mw:.1f} MW)")
        return

    if args.all:
        d = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date)
        n_written = n_skipped = n_failed = 0
        worst_unmapped = []
        while d <= end:
            d_str = d.isoformat()
            if d_str in EXCLUDED_DATES:
                n_skipped += 1
                d += timedelta(days=1)
                continue
            try:
                series, unmapped_mw, n_unmapped = build_series(d, unit_map, exchange)
            except FileNotFoundError:
                print(f"  MISSING raw data for {d_str}, skipped")
                n_failed += 1
                d += timedelta(days=1)
                continue
            write_series(series, d, args.out)
            worst_unmapped.append((unmapped_mw, d_str, n_unmapped))
            n_written += 1
            d += timedelta(days=1)

        worst_unmapped.sort(reverse=True)
        print(f"\nWrote {n_written} days, skipped {n_skipped} excluded, {n_failed} failed (missing data)")
        print("Worst 10 days by unmapped MW impact:")
        for mw, d_str, n in worst_unmapped[:10]:
            print(f"  {d_str}: {mw:8.1f} MW across {n} unmapped units")
        return

    print(__doc__)


if __name__ == "__main__":
    main()
