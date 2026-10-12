"""Download OMIE's day-ahead bid curves per bidding unit (curva_pbc_uof): one
zip per month, with every sell and buy bid step of every unit, marked offered
(O) or matched (C). No login needed. OMIE publishes a month after a 90-day
confidentiality period, so all of 2024 is available.

build_res_offered.py reads these to find the solar and wind that was offered
in the day-ahead auction but not accepted.

File columns (one file per day inside the zip, curva_pbc_uof_YYYYMMDD.1):
    Hora;Fecha;Pais;Unidad;Tipo Oferta;Energía Compra/Venta;
    Precio Compra/Venta;Ofertada (O)/Casada (C)
Tipo Oferta: V = sell, C = buy. Pais = MI (the whole Iberian market; split
Spain/Portugal with the unit list's zone).

Usage:
    python3 fetch_omie_bid_curves.py --from-month 2024-01 --to-month 2024-12
    python3 fetch_omie_bid_curves.py --month 2024-05

Caches the zips in OMIE_data/curva_pbc_uof/ (about 19 MB each), so a rerun
does not re-download months already fetched.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OMIE_DATA = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")
CACHE_DIR = os.path.join(OMIE_DATA, "curva_pbc_uof")

URL = "https://www.omie.es/es/file-download?parents=curva_pbc_uof&filename=curva_pbc_uof_{ym}.zip"


def zip_path(ym):
    return os.path.join(CACHE_DIR, f"curva_pbc_uof_{ym}.zip")


def months(a, b):
    y, m = map(int, a.split("-"))
    y1, m1 = map(int, b.split("-"))
    while (y, m) <= (y1, m1):
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch_month(ym, force=False):
    path = zip_path(ym)
    if os.path.exists(path) and not force:
        return "cached"
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = path + ".part"
    r = subprocess.run(["curl", "-sS", "-m", "600", "-o", tmp, "-w", "%{http_code}",
                        URL.format(ym=ym)], capture_output=True)
    code = r.stdout.decode().strip()
    if r.returncode != 0 or code != "200":
        if os.path.exists(tmp):
            os.remove(tmp)
        return f"failed (curl {r.returncode}, HTTP {code}) {r.stderr.decode(errors='replace').strip()}"
    with open(tmp, "rb") as f:
        if f.read(2) != b"PK":                      # not a zip: OMIE error page
            os.remove(tmp)
            return "failed (response is not a zip)"
    os.replace(tmp, path)
    time.sleep(0.5)
    return f"ok ({os.path.getsize(path) / 1e6:.1f} MB)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM")
    ap.add_argument("--from-month", help="YYYY-MM")
    ap.add_argument("--to-month", help="YYYY-MM")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.month:
        todo = list(months(args.month, args.month))
    elif args.from_month and args.to_month:
        todo = list(months(args.from_month, args.to_month))
    else:
        sys.exit(__doc__)

    fails = []
    for ym in todo:
        status = fetch_month(ym, force=args.force)
        print(f"  {ym}: {status}")
        if status.startswith("failed"):
            fails.append(ym)
    print(f"\n{len(todo) - len(fails)} of {len(todo)} months in {CACHE_DIR}")
    if fails:
        print("Failed months:", fails)


if __name__ == "__main__":
    main()
