"""
Compute per-day [chp] block sizes and insert them into config.toml's
[chp.by_date."yyyy-mm-dd"] tables, using the same method as the two
hand-derived study days (see config.toml's [chp] comments):

    gas_mw       = (ENTSO-E Fossil Gas GWh/day − OMIE cleared CCGT GWh/day) * 1000 / 24
    waste_mw     = (ENTSO-E Biomass + Waste GWh/day) * 1000 / 24
    minihydro_mw = (ENTSO-E Hydro(all types) GWh/day − OMIE Hydropower GWh/day) * 1000 / 24

"OMIE cleared CCGT"/"OMIE Hydropower" come from our own per-unit reconstruction
(convert_omie_to_model_data.py); ENTSO-E's side comes from
entsoe_download/chp_entsoe_2024.csv (fetch_chp_entsoe_year.py).

Usage:
    python3 add_chp_calibration.py --from-date 2024-07-01 --to-date 2024-12-29
"""
import argparse
import csv
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_omie_to_model_data as c  # noqa: E402

CONFIG_PATH = os.path.join(c.HERE, "..", "config.toml")
ENTSOE_DIR = os.environ.get("ENTSOE_DIR") or os.path.join(c.HERE, "..", "..", "entsoe_download")
CHP_ENTSOE_CSV = os.path.join(ENTSOE_DIR, "chp_entsoe_2024.csv")


def load_entsoe_chp():
    """date -> {fossil_gas_mw: [24], biomass_mw: [24], waste_mw: [24], hydro_total_mw: [24]}"""
    by_date = {}
    with open(CHP_ENTSOE_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = by_date.setdefault(r["date"], {
                "fossil_gas_mw": [0.0] * 24, "biomass_mw": [0.0] * 24,
                "waste_mw": [0.0] * 24, "hydro_total_mw": [0.0] * 24,
            })
            h = int(r["delivery_time"])
            d["fossil_gas_mw"][h] = float(r["fossil_gas_mw"])
            d["biomass_mw"][h] = float(r["biomass_mw"])
            d["waste_mw"][h] = float(r["waste_mw"])
            d["hydro_total_mw"][h] = (float(r["hydro_pumped_mw"]) + float(r["hydro_ror_mw"])
                                       + float(r["hydro_reservoir_mw"]))
    return by_date


def compute(unit_map, entsoe_chp, d):
    d_str = d.isoformat()
    if d_str not in entsoe_chp:
        return None
    e = entsoe_chp[d_str]
    group_totals, _, _ = c.reconstruct_day(d, unit_map)
    omie_ccgt_gwh = sum(group_totals["ccgt"]) / 1000
    omie_hydro_gwh = sum(group_totals["hydro"]) / 1000
    entsoe_gas_gwh = sum(e["fossil_gas_mw"]) / 1000
    entsoe_biomass_waste_gwh = (sum(e["biomass_mw"]) + sum(e["waste_mw"])) / 1000
    entsoe_hydro_gwh = sum(e["hydro_total_mw"]) / 1000

    gas_mw = max(0.0, (entsoe_gas_gwh - omie_ccgt_gwh) * 1000 / 24)
    waste_mw = max(0.0, entsoe_biomass_waste_gwh * 1000 / 24)
    minihydro_mw = max(0.0, (entsoe_hydro_gwh - omie_hydro_gwh) * 1000 / 24)
    return round(gas_mw, 1), round(waste_mw, 1), round(minihydro_mw, 1)


def existing_chp_dates(config_text):
    return set(re.findall(r'\[chp\.by_date\."(\d{4}-\d{2}-\d{2})"\]', config_text))


# The two original, hand-derived reference days -- their [chp.by_date] blocks
# carry the actual hand-derived gas_mw (2260/2920) this whole project's
# gas_mw investigation was measured against. Never touched by --force.
PROTECTED_DATES = {"2024-07-08", "2024-12-02"}


def remove_block(config_text, d_str):
    """Strip one whole [chp.by_date."d_str"] block (header + its key=value
    lines), for --force to let it be recomputed instead of skipped."""
    pattern = rf'\n?\[chp\.by_date\."{re.escape(d_str)}"\]\n(?:[^\[\n][^\n]*\n)*'
    return re.sub(pattern, "", config_text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--force", action="store_true",
                     help="recompute and replace dates already present in the range "
                          "(instead of skipping them); never touches the two protected "
                          "hand-derived reference days regardless")
    args = ap.parse_args()

    unit_map = c.load_unit_map()
    entsoe_chp = load_entsoe_chp()
    config_text = open(CONFIG_PATH, encoding="utf-8").read()
    if args.force:
        d = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date)
        while d <= end:
            d_str = d.isoformat()
            if d_str not in PROTECTED_DATES:
                config_text = remove_block(config_text, d_str)
            d += timedelta(days=1)
    have = existing_chp_dates(config_text)

    d = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    new_blocks = []
    n_done = n_skipped = n_missing = 0
    while d <= end:
        d_str = d.isoformat()
        if d_str in c.EXCLUDED_DATES:
            d += timedelta(days=1)
            continue
        if d_str in have:
            n_skipped += 1
            d += timedelta(days=1)
            continue
        result = compute(unit_map, entsoe_chp, d)
        if result is None:
            n_missing += 1
            d += timedelta(days=1)
            continue
        gas_mw, waste_mw, minihydro_mw = result
        # gas_mw is deliberately omitted: it doesn't reproduce the two
        # reference days (comes out ~1.8-2.4x too high, consistently, for a
        # reason not yet identified -- see project notes) while waste_mw and
        # minihydro_mw both reproduce them almost exactly. Omitting the key
        # here falls back to [chp].gas_mw's global default (chp_blocks_for in
        # run_market_chain.jl checks the per-day table first, then the
        # top-level default), rather than writing a value known to be wrong.
        new_blocks.append(
            f'\n[chp.by_date."{d_str}"]\n'
            f"waste_mw     = {waste_mw}\n"
            f"minihydro_mw = {minihydro_mw}\n"
        )
        n_done += 1
        d += timedelta(days=1)

    # Append the new [chp.by_date."..."] tables right after the last existing
    # one (end of the [chp] section, before the next top-level [section]).
    m = re.search(r'(\[chp\.by_date\."[^"]+"\]\n(?:[^\[]*\n)*)(?=\n\[|\Z)', config_text)
    if not m:
        raise RuntimeError("Could not find any [chp.by_date...] block to anchor after")
    insert_at = m.end()
    config_text = config_text[:insert_at] + "".join(new_blocks) + config_text[insert_at:]
    open(CONFIG_PATH, "w", encoding="utf-8").write(config_text)

    print(f"Added {n_done} [chp.by_date] blocks ({n_skipped} already had one, "
          f"{n_missing} missing ENTSO-E data, skipped)")


if __name__ == "__main__":
    main()
