"""Build Data/gas_unit_efficiency.csv: one efficiency per combined-cycle gas unit
(CCGT) in Data/generations.csv, from the unit's build year.

Why: the model gives every CCGT the same efficiency (0.56, [costs.gas_srmc]),
so every gas plant has the same cost and the gas price is one flat step. Real
plants differ: newer units burn less gas per MWh. With one efficiency per unit
the gas fleet becomes a merit order (cheapest units first).

Sources
  Build year  Global Energy Monitor, Global Oil and Gas Plant Tracker (GOGPT),
              August 2026 release, sheet "Gas & Oil Units", column "Start year".
              CC BY 4.0. One row per unit (not per site), and its MW match the
              units in generations.csv.
  Efficiency  ENTSO-E, ERAA 2025 / TYNDP 2026 Data Collection Guidelines, p. 6
              ("Thermal Categories"; same text in the ERAA 2026 guidelines,
              p. 16): CCGT "present 1" = 56 %, "present 2" = 58 %, "new" = 60 %.

Our assumption (not ENTSO-E's): ENTSO-E does not assign categories by build
year (the TSO assigns them; the list per unit is not public), so we use build
year as a proxy:
    built 2001-2005 -> present 1, 0.56
    built 2006-2010 -> present 2, 0.58
    built 2011 or later -> new,   0.60
Units under 100 MW (mostly industrial cogeneration) and units without a build
year keep the model's 0.56. No Spanish CCGT of 100 MW or more was built before
2001, so the "old" categories are not needed.

Matching: each model unit is paired with the GEM unit at the same site (within
5 km) with the closest MW, largest model units first, each GEM unit used once.
HAND_MATCHES below covers the units the rule cannot find.

Usage (from the repo root):
    python scripts/build_gas_unit_efficiency.py
    python scripts/build_gas_unit_efficiency.py --gem "<path to GOGPT .xlsx>" --dry-run
"""
import argparse
import csv
import math
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN_FILE = REPO / "Data" / "generations.csv"
OUT_FILE = REPO / "Data" / "gas_unit_efficiency.csv"
GEM_FILE = REPO.parent / "Global Oil and Gas Plant Tracker (GOGPT) - August 2026.xlsx"
GEM_SHEET = "Gas & Oil Units"

MODEL_ETA = 0.56        # [costs.gas_srmc].eta.ccgt today
SMALL_MW = 100.0        # below this: kept at MODEL_ETA
MAX_KM = 5.0            # same site

# (first build year, ENTSO-E category, efficiency), checked from the last row up
ENTSOE_GROUPS = [(2001, "present 1", 0.56),
                 (2006, "present 2", 0.58),
                 (2011, "new",       0.60)]

# model unit_id -> (GEM unit ID, why)
HAND_MATCHES = {
    "G0172": ("G100001030389",
              "GEM lists this 275 MW unit as the separate site 'Escatron Peaker', 10 km from Escatron 3"),
}


def read_xlsx_sheet(path, sheet):
    """Rows of one sheet as dicts (header = first row). Standard library only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    targets = {s.get("name"): rels[s.get("{%s}id" % ns["r"])] for s in wb.find("m:sheets", ns)}
    if sheet not in targets:
        sys.exit(f"{path}: no sheet '{sheet}' (has {list(targets)})")
    target = targets[sheet].lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))

    def col(ref):
        n = 0
        for ch in re.match(r"[A-Z]+", ref).group():
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows = []
    for _, row in ET.iterparse(z.open(target)):
        if row.tag != "{%s}row" % ns["m"]:
            continue
        vals = {}
        for c in row.findall("m:c", ns):
            v, t = c.find("m:v", ns), c.get("t")
            if t == "inlineStr":
                x = "".join(e.text or "" for e in c.iter("{%s}t" % ns["m"]))
            elif v is None:
                x = ""
            elif t == "s":
                x = shared[int(v.text)]
            else:
                x = v.text
            vals[col(c.get("r"))] = x
        if vals:
            rows.append([vals.get(i, "") for i in range(max(vals) + 1)])
        row.clear()
    header = rows[0]
    return [dict(zip(header, r + [""] * (len(header) - len(r)))) for r in rows[1:]]


def km(lat1, lon1, lat2, lon2):
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def group_for(mw, year):
    if mw < SMALL_MW:
        return "small plant", MODEL_ETA
    if year is None:
        return "no build year", MODEL_ETA
    cat, eta = "before present 1", MODEL_ETA
    for first, c, e in ENTSOE_GROUPS:
        if year >= first:
            cat, eta = c, e
    return cat, eta


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gem", type=Path, default=GEM_FILE, help="GOGPT .xlsx file")
    ap.add_argument("--out", type=Path, default=OUT_FILE)
    ap.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    args = ap.parse_args()
    if not args.gem.exists():
        sys.exit(f"GEM file not found: {args.gem}")

    with open(GEN_FILE, encoding="utf-8-sig", newline="") as f:
        units = [r for r in csv.DictReader(f)
                 if r["primary_fuel"] == "Gas" and r["technology"] == "Combined_cycle"]
    gem = [r for r in read_xlsx_sheet(args.gem, GEM_SHEET) if r["Country/Area"] == "Spain"]
    gem_by_id = {r["GEM unit ID"]: r for r in gem}

    used, match = set(), {}
    for uid, (gid, why) in HAND_MATCHES.items():
        if gid not in gem_by_id:
            sys.exit(f"HAND_MATCHES: GEM unit {gid} not in {args.gem.name}")
        match[uid] = (gem_by_id[gid], "GEM (hand match)", why)
        used.add(gid)
    for u in sorted(units, key=lambda r: -float(r["capacity_mw"])):
        if u["unit_id"] in match:
            continue
        best = None
        for g in gem:
            if g["GEM unit ID"] in used or num(g["Latitude"]) is None:
                continue
            d = km(float(u["y"]), float(u["x"]), float(g["Latitude"]), float(g["Longitude"]))
            if d <= MAX_KM:
                key = (abs((num(g["Capacity (MW)"]) or 0.0) - float(u["capacity_mw"])), d)
                if best is None or key < best[0]:
                    best = (key, g)
        if best is not None:
            used.add(best[1]["GEM unit ID"])
            note = "" if best[0][0] <= 2 else f"MW differ: model {float(u['capacity_mw']):.0f}, GEM {best[1]['Capacity (MW)']}"
            match[u["unit_id"]] = (best[1], "GEM", note)

    out = []
    for u in units:
        mw = float(u["capacity_mw"])
        g, src, note = match.get(u["unit_id"], (None, "none", "no GEM unit within 5 km"))
        year = int(num(g["Start year"])) if g is not None and num(g["Start year"]) is not None else None
        if g is not None and year is None:
            src, note = "none", "GEM unit has no start year"
        cat, eta = group_for(mw, year)
        out.append({"unit_id": u["unit_id"], "name": u["name"], "capacity_mw": u["capacity_mw"],
                    "build_year": year if year is not None else "", "year_source": src,
                    "gem_unit_id": g["GEM unit ID"] if g is not None else "",
                    "gem_unit": f"{g['Plant name']} / {g['Unit name']}" if g is not None else "",
                    "entsoe_category": cat, "efficiency": f"{eta:.2f}", "note": note})

    # report
    tot = sum(float(r["capacity_mw"]) for r in out)
    print(f"CCGT units in generations.csv: {len(out)} ({tot:,.0f} MW); Spanish GEM units: {len(gem)}")
    print(f"with a build year: {sum(1 for r in out if r['build_year'] != '')}; "
          f"hand matches: {sum(1 for r in out if r['year_source'] == 'GEM (hand match)')}")
    print("efficiency groups:")
    groups = {}
    for r in out:
        k = (r["entsoe_category"], r["efficiency"])
        n, m = groups.get(k, (0, 0.0))
        groups[k] = (n + 1, m + float(r["capacity_mw"]))
    for (cat, eta), (n, m) in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        print(f"  {cat:16} {eta}  {n:3d} units  {m:8,.0f} MW")
    flagged = [r for r in out if r["note"]]
    if flagged:
        print("notes:")
        for r in flagged:
            print(f"  {r['unit_id']} {r['name'][:38]:38} {float(r['capacity_mw']):6.0f} MW  {r['note']}")
    if args.dry_run:
        print("dry run: nothing written")
        return
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(sorted(out, key=lambda r: r["unit_id"]))
    print(f"wrote {args.out.relative_to(REPO)} ({len(out)} rows)")


if __name__ == "__main__":
    main()
