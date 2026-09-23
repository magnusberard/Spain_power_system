"""Download OMIE's own "Energía horaria por tecnologías" (hourly energy by
technology) report -- the official, pre-aggregated national totals by
technology, publicly and permanently archived per day (unlike the unit list,
which is a live-only snapshot). No login needed.

This replaces the need for per-unit (`pdbf`) reconstruction + the fragile
unit-technology map: OMIE has already done the technology-level aggregation
for us, for every day, going back at least to 2020 (tested against 2022,
2023, 2024 dates -- see project chat history).

Report code: INT_PBC_TECNOLOGIAS_H, system=1 (Spain only; 2=Portugal,
9=combined Iberian). URL pattern confirmed against the existing hand-
validated Data/OMIE/actual_generation_July_8.csv: exact match, 0.0000 MW
across all 24 hours, all 13 columns.

Usage:
    python3 fetch_omie_technology.py --from-date 2024-01-01 --to-date 2024-12-29
    python3 fetch_omie_technology.py --date 2024-07-08     # single day

Caches raw .TXT files in OMIE_data/tecnologias/ (one per day), so a rerun
after an interruption doesn't re-hit the server for days already fetched.
"""
import argparse
import os
import sys
import time
import subprocess
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
OMIE_DATA = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")
CACHE_DIR = os.path.join(OMIE_DATA, "tecnologias")

BASE = "https://www.omie.es/sites/default/files/dados"
SYS_SPAIN = "1"


def url_for(d):
    dd, mm, yyyy = f"{d.day:02d}", f"{d.month:02d}", f"{d.year}"
    return (f"{BASE}/AGNO_{yyyy}/MES_{mm}/TXT/"
            f"INT_PBC_TECNOLOGIAS_H_{SYS_SPAIN}_{dd}_{mm}_{yyyy}_{dd}_{mm}_{yyyy}.TXT")


def cache_path(d):
    return os.path.join(CACHE_DIR, f"tecnologias_{d.year}{d.month:02d}{d.day:02d}.txt")


def fetch_day(d, force=False):
    path = cache_path(d)
    if os.path.exists(path) and not force:
        return "cached"
    os.makedirs(CACHE_DIR, exist_ok=True)
    url = url_for(d)
    r = subprocess.run(["curl", "-sS", "-m", "30", "-w", "\n%{http_code}", url],
                        capture_output=True)
    if r.returncode != 0:
        return f"curl error: {r.stderr.decode(errors='replace').strip()}"
    body, _, code = r.stdout.rpartition(b"\n")
    code = code.decode()
    if code != "200":
        return f"HTTP {code}"
    if len(body) < 100:
        return "empty/too short response"
    with open(path, "wb") as f:
        f.write(body)
    time.sleep(0.2)
    return "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--from-date")
    ap.add_argument("--to-date")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.date:
        days = [date.fromisoformat(args.date)]
    elif args.from_date and args.to_date:
        d0, d1 = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
        days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
    else:
        sys.exit(__doc__)

    n_ok = n_cached = n_fail = 0
    fails = []
    for d in days:
        status = fetch_day(d, force=args.force)
        if status == "ok":
            n_ok += 1
        elif status == "cached":
            n_cached += 1
        else:
            n_fail += 1
            fails.append((d.isoformat(), status))
            print(f"  {d.isoformat()}: FAILED ({status})")

    print(f"\nFetched {n_ok} new, {n_cached} already cached, {n_fail} failed "
          f"(of {len(days)} days) -> {CACHE_DIR}")
    if fails:
        print("Failed days:", fails)


if __name__ == "__main__":
    main()
