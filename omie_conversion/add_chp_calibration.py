"""
Compute per-day [chp] block sizes and insert them into config.toml's
[chp.by_date."yyyy-mm-dd"] tables, using the same method as the two
hand-derived study days (see config.toml's [chp] comments):

    waste_mw     = (ENTSO-E Biomass + Waste GWh/day) * 1000 / 24
    minihydro_mw = (ENTSO-E Hydro(all types) GWh/day − OMIE Hydropower GWh/day) * 1000 / 24
    gas_mw       = OMIE "Cogeneración/Residuos/Mini hidráulica" daily mean MW
                   − waste_mw − minihydro_mw

The three blocks together stand in for OMIE's cogeneration/waste/mini-hydro
market group, so gas_mw is what is left of that group once the two non-gas
parts are taken out.  This reproduces the hand-derived reference days
(8 Jul: 3410 − 730 − 420 = 2260 MW; 2 Dec: 3919 − 650 − 350 = 2919 MW) and
the 54 / 70 GWh/day of the Spanish model paper, section 5.1.1.  The earlier
formula, ENTSO-E Fossil Gas − OMIE day-ahead CCGT, came out 1.8-2.4x too
high: ENTSO-E's gas figure is actual delivered output and includes the CCGT
units committed after the day-ahead, which OMIE's day-ahead CCGT does not.

"OMIE Hydropower" and the cogeneration group come from OMIE's technology
report (convert_omie_to_model_data.py, OMIE_data/tecnologias/); ENTSO-E's
side comes from entsoe_download/chp_entsoe_2024.csv (fetch_chp_entsoe_year.py).

Usage:
    python3 add_chp_calibration.py --from-date 2024-07-01 --to-date 2024-12-29
    # gas_mw only, from the waste_mw/minihydro_mw already in config.toml
    # (no ENTSO-E data needed); --dry-run writes the report and leaves
    # config.toml untouched
    python3 add_chp_calibration.py --from-date 2024-01-02 --to-date 2024-12-29 \\
        --gas-from-config --dry-run
"""
import argparse
import csv
import os
import re
import sys
import tomllib
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_omie_to_model_data as c  # noqa: E402

CONFIG_PATH = os.path.join(c.HERE, "..", "config.toml")
ENTSOE_DIR = os.environ.get("ENTSOE_DIR") or os.path.join(c.HERE, "..", "..", "entsoe_download")
CHP_ENTSOE_CSV = os.path.join(ENTSOE_DIR, "chp_entsoe_2024.csv")
REPORT_CSV = os.path.join(c.HERE, "..", "results", "chp_gas_mw_report.csv")


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


def cogen_group_mw(d):
    """Daily mean MW of OMIE's cogeneration/waste/mini-hydro group."""
    group_totals, _, _ = c.reconstruct_day(d)
    return sum(group_totals["cogen"]) / 24


def gas_residual_mw(cogen_mw, waste_mw, minihydro_mw):
    """(clamped gas_mw, unclamped residual).  The residual goes negative when
    the ENTSO-E-based waste + mini-hydro estimate exceeds the whole OMIE group
    (mini-hydro is only an upper bound -- it also absorbs intraday hydro
    adjustment), so the clamp is reported alongside rather than hidden."""
    raw = cogen_mw - waste_mw - minihydro_mw
    return max(0.0, raw), raw


def compute(entsoe_chp, d):
    d_str = d.isoformat()
    if d_str not in entsoe_chp:
        return None
    e = entsoe_chp[d_str]
    group_totals, _, _ = c.reconstruct_day(d)
    omie_hydro_gwh = sum(group_totals["hydro"]) / 1000
    entsoe_biomass_waste_gwh = (sum(e["biomass_mw"]) + sum(e["waste_mw"])) / 1000
    entsoe_hydro_gwh = sum(e["hydro_total_mw"]) / 1000

    waste_mw = round(max(0.0, entsoe_biomass_waste_gwh * 1000 / 24), 1)
    minihydro_mw = round(max(0.0, (entsoe_hydro_gwh - omie_hydro_gwh) * 1000 / 24), 1)
    cogen_mw = sum(group_totals["cogen"]) / 24
    gas_mw, raw = gas_residual_mw(cogen_mw, waste_mw, minihydro_mw)
    return round(gas_mw, 1), waste_mw, minihydro_mw, cogen_mw, raw


def existing_chp_dates(config_text):
    return set(re.findall(r'\[chp\.by_date\."(\d{4}-\d{2}-\d{2})"\]', config_text))


# The two original, hand-derived reference days -- their [chp.by_date] blocks
# carry the actual hand-derived gas_mw (2260/2920) this whole project's
# gas_mw investigation was measured against. Never touched by --force or
# --gas-from-config.
PROTECTED_DATES = {"2024-07-08", "2024-12-02"}


def remove_block(config_text, d_str):
    """Strip one whole [chp.by_date."d_str"] block (header + its key=value
    lines), for --force to let it be recomputed instead of skipped."""
    pattern = rf'\n?\[chp\.by_date\."{re.escape(d_str)}"\]\n(?:[^\[\n][^\n]*\n)*'
    return re.sub(pattern, "", config_text)


def set_block_gas(config_text, d_str, gas_mw):
    """Put `gas_mw = …` as the first key of an existing [chp.by_date] block,
    replacing any gas_mw line the block already has."""
    pattern = rf'(\[chp\.by_date\."{re.escape(d_str)}"\]\n)((?:[^\[\n][^\n]*\n)*)'
    m = re.search(pattern, config_text)
    if not m:
        raise RuntimeError(f"No [chp.by_date.\"{d_str}\"] block in config.toml")
    body = re.sub(r'^gas_mw\s*=.*\n', "", m.group(2), flags=re.M)
    new = f"{m.group(1)}gas_mw       = {gas_mw}\n{body}"
    return config_text[:m.start()] + new + config_text[m.end():]


def date_range(from_date, to_date):
    d = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    while d <= end:
        yield d
        d += timedelta(days=1)


def write_report(rows, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "cogen_group_mw", "waste_mw", "minihydro_mw",
                    "gas_mw", "gas_residual_raw_mw", "clamped", "config_gas_mw"])
        for r in rows:
            w.writerow([r["date"], round(r["cogen"], 1), r["waste"], r["minihydro"],
                        r["gas"], round(r["raw"], 1), int(r["raw"] < 0),
                        "" if r["config_gas"] is None else r["config_gas"]])
    print(f"Report: {os.path.normpath(path)} ({len(rows)} days)")


def print_summary(rows):
    for r in rows:
        if r["date"] in PROTECTED_DATES and r["config_gas"] is not None:
            print(f"  reference {r['date']}: {r['cogen']:.1f} - {r['waste']} - "
                  f"{r['minihydro']} = {r['gas']:.1f} MW  (hand-derived {r['config_gas']})")
    gas = sorted(r["gas"] for r in rows)
    if gas:
        n = len(gas)
        print(f"  gas_mw over {n} days: min {gas[0]:.0f}, median {gas[n // 2]:.0f}, "
              f"mean {sum(gas) / n:.0f}, max {gas[-1]:.0f} MW; "
              f"{sum(r['raw'] < 0 for r in rows)} days clamped at 0")


def gas_from_config(args, config_text):
    """gas_mw for every [chp.by_date] block in range, from the block's own
    waste_mw/minihydro_mw.  Needs only the OMIE technology report."""
    by_date = tomllib.loads(config_text)["chp"]["by_date"]
    rows = []
    for d in date_range(args.from_date, args.to_date):
        d_str = d.isoformat()
        blk = by_date.get(d_str)
        if blk is None or d_str in c.EXCLUDED_DATES:
            continue
        waste_mw, minihydro_mw = blk["waste_mw"], blk["minihydro_mw"]
        cogen_mw = cogen_group_mw(d)
        gas_mw, raw = gas_residual_mw(cogen_mw, waste_mw, minihydro_mw)
        rows.append({"date": d_str, "cogen": cogen_mw, "waste": waste_mw,
                     "minihydro": minihydro_mw, "gas": round(gas_mw, 1), "raw": raw,
                     "config_gas": blk.get("gas_mw")})

    print_summary(rows)
    write_report(rows, args.report)
    if args.dry_run:
        print("Dry run: config.toml not modified.")
        return
    n_set = 0
    for r in rows:
        if r["date"] in PROTECTED_DATES:
            continue
        config_text = set_block_gas(config_text, r["date"], r["gas"])
        n_set += 1
    open(CONFIG_PATH, "w", encoding="utf-8", newline="").write(config_text)
    print(f"Set gas_mw in {n_set} [chp.by_date] blocks "
          f"({len(PROTECTED_DATES)} protected reference days left as they are)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-date", required=True)
    ap.add_argument("--to-date", required=True)
    ap.add_argument("--force", action="store_true",
                     help="recompute and replace dates already present in the range "
                          "(instead of skipping them); never touches the two protected "
                          "hand-derived reference days regardless")
    ap.add_argument("--gas-from-config", action="store_true",
                     help="only compute gas_mw, from the waste_mw/minihydro_mw already "
                          "in each [chp.by_date] block (no ENTSO-E data needed)")
    ap.add_argument("--dry-run", action="store_true",
                     help="write the report CSV and print the summary, but leave "
                          "config.toml untouched")
    ap.add_argument("--report", default=REPORT_CSV,
                     help="per-day report CSV (default results/chp_gas_mw_report.csv)")
    args = ap.parse_args()

    # newline="": keep config.toml's LF line endings as they are -- text-mode
    # defaults on Windows would rewrite every line as CRLF.
    config_text = open(CONFIG_PATH, encoding="utf-8", newline="").read()
    if args.gas_from_config:
        gas_from_config(args, config_text)
        return

    entsoe_chp = load_entsoe_chp()
    if args.force:
        for d in date_range(args.from_date, args.to_date):
            d_str = d.isoformat()
            if d_str not in PROTECTED_DATES:
                config_text = remove_block(config_text, d_str)
    have = existing_chp_dates(config_text)

    new_blocks = []
    rows = []
    n_done = n_skipped = n_missing = 0
    for d in date_range(args.from_date, args.to_date):
        d_str = d.isoformat()
        if d_str in c.EXCLUDED_DATES:
            continue
        if d_str in have:
            n_skipped += 1
            continue
        result = compute(entsoe_chp, d)
        if result is None:
            n_missing += 1
            continue
        gas_mw, waste_mw, minihydro_mw, cogen_mw, raw = result
        rows.append({"date": d_str, "cogen": cogen_mw, "waste": waste_mw,
                     "minihydro": minihydro_mw, "gas": gas_mw, "raw": raw,
                     "config_gas": None})
        new_blocks.append(
            f'\n[chp.by_date."{d_str}"]\n'
            f"gas_mw       = {gas_mw}\n"
            f"waste_mw     = {waste_mw}\n"
            f"minihydro_mw = {minihydro_mw}\n"
        )
        n_done += 1

    print_summary(rows)
    write_report(rows, args.report)
    if args.dry_run:
        print("Dry run: config.toml not modified.")
        return

    # Append the new [chp.by_date."..."] tables right after the last existing
    # one (end of the [chp] section, before the next top-level [section]).
    m = re.search(r'(\[chp\.by_date\."[^"]+"\]\n(?:[^\[]*\n)*)(?=\n\[|\Z)', config_text)
    if not m:
        raise RuntimeError("Could not find any [chp.by_date...] block to anchor after")
    insert_at = m.end()
    config_text = config_text[:insert_at] + "".join(new_blocks) + config_text[insert_at:]
    open(CONFIG_PATH, "w", encoding="utf-8", newline="").write(config_text)

    print(f"Added {n_done} [chp.by_date] blocks ({n_skipped} already had one, "
          f"{n_missing} missing ENTSO-E data, skipped)")


if __name__ == "__main__":
    main()
