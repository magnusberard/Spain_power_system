"""Download REE's I90DIA files and keep the technical-constraint redispatch per unit and hour.

I90DIA (e·sios archive 34) is public, needs no token and is published with a 90-day lag. One
.xls per day (~7 MB zipped, 37 sheets). This keeps, per programming unit (unidad de programación):

  i90_tc_phase.csv     I90DIA03 energy (MWh) + I90DIA09 price (€/MWh): day-ahead technical
                       constraints, phase I and II (Redespacho UPOPVPV/UPOPVPA = phase I up, the
                       rest rebalancing — our reading of the codes, not documented by REE)
  i90_tc_realtime.csv  I90DIA08 energy + I90DIA10 price: real-time constraints, quarter-hours
                       summed (energy) or averaged (price) to the hour
  i90_limits.csv       I90DIA34 (day-ahead) and I90DIA35 (real-time) security limits REE set
                       per unit, hourly mean
  i90_pdvp.csv         I90DIA01: the viable day-ahead programme (PDVP, after phase I and II)
                       per unit and hour, MWh; non-zero rows only, and with --pdvp-units only
                       the units in that CSV's ree_unit column (e.g. ree_unit_crosswalk.csv)
  i90_afrr_band.csv    I90DIA05: secondary-regulation (aFRR) band REE assigned per unit and hour,
                       MW, up and down (Sentido); summed over units = REE's reserve requirement

Columns: date, hour (0–23), the sheet's own keys (Redespacho, Sentido, Unidad de Programación,
Tipo Restricción, …), then mwh / eur_mwh / mw. Every day is first written to <out>/days/ (so an
interrupted download resumes), then everything is combined into <out>/*.csv.gz.

    python redispatch_realism/fetch_i90.py 2024-01-01 2024-12-31
    python redispatch_realism/fetch_i90.py 2024-12-02 2024-12-04 --out ../esios_download/i90

Default <out>: $ESIOS_DIR/i90, else esios_download/i90 next to the repo (as fetch_esios.py).
Needs xlrd (pip install xlrd). Zips are deleted after parsing unless --keep-zips.
"""
import argparse
import datetime as dt
import os
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

try:
    import xlrd
except ImportError:
    sys.exit("fetch_i90.py needs xlrd to read REE's .xls files: pip install xlrd")

URL = ("https://api.esios.ree.es/archives/34/download?date_type=datos"
       "&start_date={d}T00:00:00&end_date={d}T23:59:59&locale=es")
REPO = Path(__file__).resolve().parents[1]
UNIT = "Unidad de Programación"


def sheet_long(book, name, value_name, how="sum"):
    """A per-unit sheet in long form: id columns (before 'Total'), one row per hour."""
    if name not in book.sheet_names():
        return pd.DataFrame()
    sh = book.sheet_by_name(name)
    rows = [sh.row_values(i) for i in range(sh.nrows)]
    # keyed by programming unit; the aFRR band (I90DIA05) is keyed by market participant
    # from 20 Nov 2024, when Spain's secondary-regulation market changed
    keys = (UNIT, "Participante del Mercado")
    try:
        hi = next(i for i, r in enumerate(rows) if any(str(c).strip() in keys for c in r))
    except StopIteration:
        return pd.DataFrame()
    head = [str(c).strip() for c in rows[hi]]
    key = next(k for k in keys if k in head)
    df = pd.DataFrame(rows[hi + 1:], columns=head)
    df = df[df[key].astype(str).str.strip() != ""]
    # time columns: "00-01" … (hourly) or "1.0" … "96.0" (quarter-hours); the rest are keys,
    # except the totals and the empty "Hora" / "Cuarto de Hora del dia" label columns
    is_time = lambda c: bool(re.fullmatch(r"\d\d-\d\d", c) or re.fullmatch(r"\d+(\.0)?", c))
    times = [c for c in head if is_time(c)]
    ids = [c for c in head if c and not is_time(c) and c not in ("Total", "Hora", "Cuarto de Hora del dia")]
    long = df.melt(id_vars=ids, value_vars=times, var_name="slot", value_name=value_name)
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce")
    long = long.dropna(subset=[value_name])
    n = len(times)                                   # 24 hourly or 96 quarter-hourly (92/100 on DST days)
    pos = {c: i for i, c in enumerate(times)}
    long["hour"] = long.slot.map(lambda c: min(23, pos[c] * 24 // n))
    agg = long.groupby(ids + ["hour"], dropna=False)[value_name]
    return (agg.sum() if how == "sum" else agg.mean()).reset_index()


TABLES = ("tc_phase", "tc_realtime", "limits", "pdvp", "afrr_band")


def parse_day(xls_bytes, d, pdvp_units=None):
    book = xlrd.open_workbook(file_contents=xls_bytes, on_demand=True)
    out = {}
    pv = sheet_long(book, "I90DIA01", "mwh", "sum")
    if not pv.empty:
        pv = pv[pv.mwh != 0]
        if pdvp_units is not None:
            pv = pv[pv[UNIT].isin(pdvp_units)]
        out["pdvp"] = pv
    band = sheet_long(book, "I90DIA05", "mw", "mean")
    if not band.empty:
        out["afrr_band"] = band[band.mw != 0]
    for key, (e_sheet, p_sheet) in {"tc_phase": ("I90DIA03", "I90DIA09"),
                                    "tc_realtime": ("I90DIA08", "I90DIA10")}.items():
        e, p = sheet_long(book, e_sheet, "mwh", "sum"), sheet_long(book, p_sheet, "eur_mwh", "mean")
        if not e.empty:
            e = e[e.mwh != 0]
            keys = [c for c in e.columns if c in p.columns and c != "eur_mwh"] if not p.empty else []
            out[key] = e.merge(p[keys + ["eur_mwh"]], on=keys, how="left") if keys else e
    lim = [sheet_long(book, s, "mw", "mean").assign(stage=st) for s, st in (("I90DIA34", "day-ahead"), ("I90DIA35", "real-time"))]
    lim = [x for x in lim if not x.empty]
    if lim:
        out["limits"] = pd.concat(lim, ignore_index=True)
    for v in out.values():
        v.insert(0, "date", d)
    return out


def fetch(d, zdir, retries=3):
    z = zdir / f"I90DIA_{d}.zip"
    if not z.exists():
        for k in range(retries):
            try:
                z.write_bytes(urllib.request.urlopen(URL.format(d=d), timeout=180).read())
                break
            except Exception as e:                      # network hiccup: wait and retry
                if k == retries - 1:
                    raise
                time.sleep(10 * (k + 1))
    with zipfile.ZipFile(z) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".xls"))
        return z, zf.read(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("first", help="YYYY-MM-DD")
    ap.add_argument("last", help="YYYY-MM-DD")
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90")
    ap.add_argument("--keep-zips", action="store_true")
    ap.add_argument("--pdvp-units", type=Path, help="CSV with a ree_unit column: keep only these units in i90_pdvp")
    a = ap.parse_args()
    pdvp_units = set(pd.read_csv(a.pdvp_units).ree_unit) if a.pdvp_units else None
    days = pd.date_range(a.first, a.last).strftime("%Y-%m-%d")
    ddir, zdir = a.out / "days", a.out / "zips"
    ddir.mkdir(parents=True, exist_ok=True); zdir.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(days, 1):
        if (ddir / f"{d}.done").exists() and all((ddir / f"{d}_{k}.csv").exists() for k in ("pdvp", "afrr_band")):
            continue                                    # (days fetched before these tables existed are fetched again)
        t = time.time()
        try:
            z, xls = fetch(d, zdir)
            parts = parse_day(xls, d, pdvp_units)
        except Exception as e:
            print(f"[{i}/{len(days)}] {d}: FAILED ({e})", flush=True)
            continue
        for k, v in parts.items():
            v.to_csv(ddir / f"{d}_{k}.csv", index=False)
        (ddir / f"{d}.done").touch()
        if not a.keep_zips:
            z.unlink()
        print(f"[{i}/{len(days)}] {d}: " + ", ".join(f"{k} {len(v)}" for k, v in parts.items())
              + f"  ({time.time() - t:.0f} s)", flush=True)
    for k in TABLES:
        files = sorted(ddir.glob(f"*_{k}.csv"))
        if files:
            pd.concat((pd.read_csv(f) for f in files), ignore_index=True).to_csv(a.out / f"i90_{k}.csv.gz", index=False)
            print(f"  {a.out / f'i90_{k}.csv.gz'}: {len(files)} days")


if __name__ == "__main__":
    main()
