"""
Parse OMIE's "LISTADO DE UNIDADES OFERTANTES VIGENTES" (list of active bidding
units) PDF into a clean CSV mapping each unit code to its zone and technology.

This mapping is what lets us turn the per-unit pdbf_YYYYMMDD.1 schedule files
(unit code + hourly MW) into technology totals (load / wind / solar).

Usage:
    python3 parse_unit_list.py <path-to-LISTA_UNIDADES.pdf> <output-csv>

Example:
    python3 parse_unit_list.py \
        "../../OMIE_data/LISTA_UNIDADES.pdf" \
        "../../OMIE_data/unit_technology_map.csv"
"""
import csv
import sys

import pdfplumber

# OMIE has used at least two column layouts over the years: the current one
# (7 columns) and an older one (8 columns) with an extra "ESTADO" status
# column inserted before ZONA/FRONTERA. Column positions are looked up by
# name instead of assumed fixed, so either layout (or a future one that adds
# more columns) parses correctly as long as these names are all present.
REQUIRED_COLUMNS = {
    "code": "CODIGO",
    "description": "DESCRIPCIÓN",
    "agent": "AGENTE PROPIETARIO",
    "ownership_pct": "PORCENTAJE\nPROPIEDAD",
    "unit_type": "TIPO UNIDAD",
    "zone": "ZONA/FRONTERA",
    "technology": "TECNOLOGÍA",
}
OPTIONAL_COLUMNS = {
    "status": "ESTADO",
}


def parse_unit_list(pdf_path):
    """Yield one dict per row across every page of the unit list PDF."""
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            table = page.extract_table()
            if not table:
                print(f"  warning: no table found on page {page_num}", file=sys.stderr)
                continue
            header, *body = table
            try:
                col_idx = {key: header.index(name) for key, name in REQUIRED_COLUMNS.items()}
            except ValueError:
                print(f"  warning: unrecognised header on page {page_num}, skipped: {header}",
                      file=sys.stderr)
                continue
            for key, name in OPTIONAL_COLUMNS.items():
                if name in header:
                    col_idx[key] = header.index(name)
            for row in body:
                if not row or not row[0] or len(row) <= max(col_idx.values()):
                    continue  # skip stray/blank/short rows
                out = {key: (row[i] or "").strip() for key, i in col_idx.items()}
                rows.append(out)
    return rows


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    pdf_path, out_csv = sys.argv[1], sys.argv[2]

    rows = parse_unit_list(pdf_path)
    print(f"Parsed {len(rows)} unit rows from {pdf_path}")

    # A unit code can legitimately appear more than once across pages only if
    # OMIE lists it twice by mistake; warn so it's not silently masked.
    codes = [r["code"] for r in rows]
    dupes = {c for c in codes if codes.count(c) > 1}
    if dupes:
        print(f"  warning: {len(dupes)} duplicate unit codes found: "
              f"{sorted(dupes)[:10]}{'...' if len(dupes) > 10 else ''}",
              file=sys.stderr)

    fieldnames = ["code", "description", "agent", "ownership_pct",
                  "unit_type", "zone", "technology"]
    if any("status" in r for r in rows):
        fieldnames.append("status")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {out_csv}")


if __name__ == "__main__":
    main()
