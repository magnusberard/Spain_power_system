"""List REE e·sios indicators that matter for comparing the model with what REE really did.

e·sios (https://www.esios.ree.es) is Red Eléctrica's data platform. It has the data behind the
model's last two stages that OMIE and ENTSO-E do not publish in detail: balancing energy
(aFRR, mFRR, RR), redispatch for technical constraints, and imbalances. This script downloads
e·sios' catalogue of indicators once and prints the ones whose name matches those topics, so we
can pick the series to download with fetch_esios.py.

Usage (token is read from the environment, never from a file):
    $env:ESIOS_TOKEN = '...'          # PowerShell
    python esios_download/find_indicators.py
    python esios_download/find_indicators.py --search "restricciones"   # own search term

Writes <DATA_DIR>/indicators.csv (the whole catalogue: id, name, short name, description).
DATA_DIR is $ESIOS_DIR, else the esios_download/ folder NEXT TO the repo (outside it), like
entsoe_download.
"""
import argparse
import os
import re
import sys

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("ESIOS_DIR") or os.path.join(HERE, "..", "..", "esios_download")
API = "https://api.esios.ree.es"

# topic -> regular expression on the indicator name (e·sios names are in Spanish)
TOPICS = {
    "aFRR (secondary regulation)": r"secundaria|aFRR",
    "mFRR (tertiary regulation)": r"terciaria|mFRR",
    "RR (replacement reserve)": r"sustituci[oó]n|\bRR\b",
    "Technical constraints (redispatch)": r"restricciones t[eé]cnicas|restricciones por garant|redespacho",
    "Imbalances": r"desv[ií]o",
    "Real-time constraints": r"tiempo real",
}


def headers(token):
    # e·sios accepts the personal token as x-api-key; the Accept header selects API version 1
    return {"Accept": "application/json; application/vnd.esios-api-v1+json",
            "Content-Type": "application/json", "x-api-key": token}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--search", help="own regular expression on the indicator name (case-insensitive)")
    ap.add_argument("--refresh", action="store_true", help="download the catalogue again")
    args = ap.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "indicators.csv")
    if args.refresh or not os.path.exists(path):
        token = os.environ.get("ESIOS_TOKEN")
        if not token:
            sys.exit("Set ESIOS_TOKEN first: $env:ESIOS_TOKEN = '...'")
        r = requests.get(f"{API}/indicators", headers=headers(token), timeout=60)
        if r.status_code in (401, 403):
            sys.exit(f"e·sios refused the token (HTTP {r.status_code}). Check that ESIOS_TOKEN is the token from REE's email.")
        r.raise_for_status()
        rows = [dict(id=i.get("id"), name=i.get("name", ""), short_name=i.get("short_name", ""),
                     description=re.sub(r"<[^>]+>", " ", i.get("description") or "").strip())
                for i in r.json().get("indicators", [])]
        cat = pd.DataFrame(rows).sort_values("id")
        cat.to_csv(path, index=False, encoding="utf-8")
        print(f"Downloaded the catalogue: {len(cat)} indicators -> {path}\n")
    cat = pd.read_csv(path, encoding="utf-8").fillna("")

    topics = {"Your search": args.search} if args.search else TOPICS
    for topic, pattern in topics.items():
        hit = cat[cat.name.str.contains(pattern, case=False, regex=True)]
        print(f"== {topic}: {len(hit)}")
        for r in hit.itertuples():
            print(f"  {r.id:>6}  {r.name}")
        print()


if __name__ == "__main__":
    main()
