"""
Compute per-day nuclear/coal availability from the OMIE reconstruction
(same method as the two hand-derived study days, see config.toml comments):

    nuclear_availability = day's peak OMIE-cleared nuclear MW / 7408 (nameplate)
    coal_availability    = day's peak OMIE-cleared coal MW    / 2900 (nameplate)

and insert them into config.toml's [da.nuclear_availability_by_date] /
[da.coal_availability_by_date] tables, for every day in a date range that
doesn't already have an entry (the two existing hand-derived days are left
untouched).

Usage:
    python3 add_nuclear_coal_calibration.py --from-date 2024-07-01 --to-date 2024-12-29
"""
import argparse
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_omie_to_model_data as c  # noqa: E402

NUCLEAR_NAMEPLATE = 7408.0
COAL_NAMEPLATE = 2900.0
CONFIG_PATH = os.path.join(c.HERE, "..", "config.toml")


def compute(unit_map, d):
    group_totals, _, _ = c.reconstruct_day(d, unit_map)
    nuclear_avail = max(group_totals["nuclear"]) / NUCLEAR_NAMEPLATE
    coal_avail = max(group_totals["coal"]) / COAL_NAMEPLATE
    return round(nuclear_avail, 3), round(coal_avail, 3)


def existing_dates(config_text, table_name):
    """Dates already present as keys under a given [da.X_by_date] table.
    The header pattern is anchored to the start of a line (^) so it can't
    match the same literal text appearing inside a comment above it."""
    m = re.search(rf"^\[da\.{re.escape(table_name)}\](.*?)(?=\n\[|\Z)", config_text, re.S | re.M)
    if not m:
        return set()
    return set(re.findall(r'"(\d{4}-\d{2}-\d{2})"\s*=', m.group(1)))


def insert_entries(config_text, table_name, entries):
    """Append date=value lines at the end of an existing [da.X_by_date] table."""
    if not entries:
        return config_text
    pattern = rf"(^\[da\.{re.escape(table_name)}\].*?)(\n\n|\n\[)"
    m = re.search(pattern, config_text, re.S | re.M)
    if not m:
        raise RuntimeError(f"Could not find [da.{table_name}] block in config.toml")
    block, sep = m.group(1), m.group(2)
    new_lines = "\n" + "\n".join(f'"{d}" = {v}' for d, v in entries)
    return config_text[:m.start()] + block + new_lines + sep + config_text[m.end():]


# The two original, hand-derived reference days -- never touched by --force,
# even though this script's own formula reproduces them (see config.toml's
# [da] comments: these ARE the source of that formula, not a check on it).
PROTECTED_DATES = {"2024-07-08", "2024-12-02"}


def remove_dates_in_range(config_text, table_name, from_date, to_date):
    """Strip existing '"yyyy-mm-dd" = value' lines for a table, for dates
    inside [from_date, to_date] -- used by --force to let a date be
    recomputed instead of silently skipped as 'already present'."""
    def repl(m):
        if m.group(1) in PROTECTED_DATES:
            return m.group(0)
        return "" if from_date <= m.group(1) <= to_date else m.group(0)
    m = re.search(rf"^\[da\.{re.escape(table_name)}\](.*?)(?=\n\[|\Z)", config_text, re.S | re.M)
    if not m:
        return config_text
    block = re.sub(r'\n"(\d{4}-\d{2}-\d{2})"\s*=\s*[0-9.]+', repl, m.group(1))
    return config_text[:m.start(1)] + block + config_text[m.end(1):]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--force", action="store_true",
                     help="recompute and replace dates already present in the range "
                          "(instead of skipping them)")
    args = ap.parse_args()

    unit_map = c.load_unit_map()
    config_text = open(CONFIG_PATH, encoding="utf-8").read()
    if args.force:
        config_text = remove_dates_in_range(config_text, "nuclear_availability_by_date",
                                             args.from_date, args.to_date)
        config_text = remove_dates_in_range(config_text, "coal_availability_by_date",
                                             args.from_date, args.to_date)
    have_nuclear = existing_dates(config_text, "nuclear_availability_by_date")
    have_coal = existing_dates(config_text, "coal_availability_by_date")

    d = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    new_nuclear, new_coal = [], []
    n_done = n_skipped = 0
    while d <= end:
        d_str = d.isoformat()
        if d_str in c.EXCLUDED_DATES:
            d += timedelta(days=1)
            continue
        if d_str in have_nuclear and d_str in have_coal:
            n_skipped += 1
            d += timedelta(days=1)
            continue
        try:
            nuc, coal = compute(unit_map, d)
        except FileNotFoundError:
            print(f"  MISSING raw data for {d_str}, skipped")
            d += timedelta(days=1)
            continue
        if d_str not in have_nuclear:
            new_nuclear.append((d_str, nuc))
        if d_str not in have_coal:
            new_coal.append((d_str, coal))
        n_done += 1
        d += timedelta(days=1)

    config_text = insert_entries(config_text, "nuclear_availability_by_date", new_nuclear)
    config_text = insert_entries(config_text, "coal_availability_by_date", new_coal)
    open(CONFIG_PATH, "w", encoding="utf-8").write(config_text)

    print(f"Added {len(new_nuclear)} nuclear + {len(new_coal)} coal entries "
          f"({n_done} days computed, {n_skipped} already had both)")


if __name__ == "__main__":
    main()
