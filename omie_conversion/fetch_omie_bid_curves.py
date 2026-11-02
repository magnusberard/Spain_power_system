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

--market ida: the intraday auctions' bid curves instead (curva_pibc_uof, one
file per day and session, curva_pibc_uof_YYYYMMDDSS.1, SS 01/02/03 = IDA1/2/3,
same columns + "Simple Block Orders"; from 14 Jun 2024, ~16 MB a month) and
their marginal prices (marginalpibc_YYYYMMDDSS.1, one small file per day and
session, in OMIE_data/marginalpibc/), for build_price_setter.py --market ida.

Usage:
    python3 fetch_omie_bid_curves.py --from-month 2024-01 --to-month 2024-12
    python3 fetch_omie_bid_curves.py --month 2024-05
    python3 fetch_omie_bid_curves.py --market ida --from-month 2024-06 --to-month 2024-12

Caches the zips in OMIE_data/curva_pbc_uof/ (about 19 MB each), so a rerun
does not re-download months already fetched.
"""
import argparse
import calendar
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OMIE_DATA = os.environ.get("OMIE_DATA_DIR") or os.path.join(HERE, "..", "..", "OMIE_data")
CURVES = {"da": "curva_pbc_uof", "ida": "curva_pibc_uof"}
CACHE_DIR = os.path.join(OMIE_DATA, CURVES["da"])
FILE_URL = "https://www.omie.es/es/file-download?parents={kind}&filename={name}"
URL = FILE_URL.replace("{kind}", CURVES["da"]).replace("{name}", CURVES["da"] + "_{ym}.zip")
IDA_START = "20240614"   # the European intraday auctions replaced the MIBEL sessions on 14 June 2024


def zip_path(ym):
    return os.path.join(CACHE_DIR, f"{os.path.basename(CACHE_DIR)}_{ym}.zip")


def fetch_marginal_ida(ym):
    """marginalpibc_YYYYMMDDSS.1 for every day and session of the month (cached)."""
    out = os.path.join(OMIE_DATA, "marginalpibc")
    os.makedirs(out, exist_ok=True)
    y, m = int(ym[:4]), int(ym[4:])
    got = miss = 0
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        day = f"{ym}{d:02d}"
        if day < IDA_START:
            continue
        for ss in ("01", "02", "03"):
            name = f"marginalpibc_{day}{ss}.1"
            path = os.path.join(out, name)
            if os.path.exists(path):
                got += 1
                continue
            r = subprocess.run(["curl", "-sS", "-m", "60", "-o", path + ".part", "-w", "%{http_code}",
                                FILE_URL.format(kind="marginalpibc", name=name)], capture_output=True)
            ok = r.returncode == 0 and r.stdout.decode().strip() == "200"
            if ok:
                with open(path + ".part", "rb") as f:
                    ok = f.read(12).startswith(b"MARGINALPIBC")
            if ok:
                os.replace(path + ".part", path); got += 1
            else:
                if os.path.exists(path + ".part"):
                    os.remove(path + ".part")
                miss += 1
            time.sleep(0.2)
    return f"marginal prices: {got} sessions, {miss} missing"


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
    ap.add_argument("--market", choices=("da", "ida"), default="da",
                    help="da = day-ahead (curva_pbc_uof), ida = intraday auctions (curva_pibc_uof + marginalpibc)")
    args = ap.parse_args()
    global CACHE_DIR, URL
    CACHE_DIR = os.path.join(OMIE_DATA, CURVES[args.market])
    URL = FILE_URL.replace("{kind}", CURVES[args.market]).replace("{name}", CURVES[args.market] + "_{ym}.zip")
    if args.month:
        todo = list(months(args.month, args.month))
    elif args.from_month and args.to_month:
        todo = list(months(args.from_month, args.to_month))
    else:
        sys.exit(__doc__)

    fails = []
    for ym in todo:
        status = fetch_month(ym, force=args.force)
        if args.market == "ida" and not status.startswith("failed"):
            status += "; " + fetch_marginal_ida(ym)
        print(f"  {ym}: {status}")
        if status.startswith("failed"):
            fails.append(ym)
    print(f"\n{len(todo) - len(fails)} of {len(todo)} months in {CACHE_DIR}")
    if fails:
        print("Failed months:", fails)


if __name__ == "__main__":
    main()
