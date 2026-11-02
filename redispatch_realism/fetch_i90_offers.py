"""Download REE's offer books for technical constraints from the I90DIA files (every offer, not only accepted ones).

The I90DIA file (e·sios archive 34, public, 90-day lag; see fetch_i90.py) holds the offers REE ranks in the
technical-constraints process (P.O. 3.2) next to the results fetch_i90.py keeps. This keeps, per programming unit:

  i90_offers_tc.csv.gz       I90DIA17 simple offers for technical constraints (day-ahead, phases I and II):
                             date, hour, Sentido (Venta = up/sell, Compra = down/buy-back), unit, Bloque,
                             Tipo Oferta, Precedencia, mwh, eur_mwh. Blocks with no energy in an hour are dropped.
  i90_offers_tc_rt.csv.gz    I90DIA32 simple offers updated for real-time constraints, quarter-hours to the hour:
                             mwh = sum of MW over the hour's quarter-hours / 4, eur_mwh = MW-weighted mean
                             (plain mean where all quarter-hours are 0 MW, which are then dropped anyway).
  i90_offers_complex.csv.gz  I90DIA18 (stage day-ahead) and I90DIA33 (stage real-time) complex offers: cold and
                             hot start-up price (€), minimum income per hour (€/h), unit price (€/MWh).
  i90_startup_times.csv.gz   I90DIA29 declared start-up times (minutes, hot/cold/turbine) per unit, market, mode.

Energy in I90DIA17 is signed as REE publishes it (buy-back offers negative); the sign is kept.
Each day goes to <out>/days/ first, so an interrupted download resumes; then everything is combined.

    python redispatch_realism/fetch_i90_offers.py 2024-01-01 2024-06-30 --out ../esios_download/i90_offers
    python redispatch_realism/fetch_i90_offers.py 2024-03-14 2024-03-14 --zips <dir with I90DIA_2024-03-14.zip>

Needs xlrd. Zips are deleted after parsing unless --keep-zips.
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_i90 import fetch, REPO, UNIT  # noqa: E402  (same download, same archive)

import xlrd  # noqa: E402

TABLES = ("offers_tc", "offers_tc_rt", "offers_complex", "startup_times")


def _rows(book, name):
    if name not in book.sheet_names():
        return None
    sh = book.sheet_by_name(name)
    return [sh.row_values(i) for i in range(sh.nrows)]


def _header(rows):
    return next(i for i, r in enumerate(rows) if any(str(c).strip() == UNIT for c in r))


def offer_sheet(book, name, quarter=False):
    """A block-offer sheet (I90DIA17 hourly MWh/€ pairs, I90DIA32 quarter-hour MW/€ pairs) in long form per hour."""
    rows = _rows(book, name)
    if not rows:
        return pd.DataFrame()
    hi = _header(rows)
    head = [str(c).strip() for c in rows[hi]]
    label = [str(c).strip() for c in rows[hi - 1]]
    is_time = lambda c: bool(re.fullmatch(r"\d\d-\d\d", c) or re.fullmatch(r"\d+(\.0)?", c))
    slots = [j for j, c in enumerate(label) if is_time(c)]           # energy column; price is the next one
    first = slots[0]
    ids = [c for c in head[:first] if c and c not in ("Total MWh", "PMP €/MWh", "Indicadores")]
    idx = [head.index(c) for c in ids]
    n = len(slots)                                                    # 24 / 96 (92, 100 on DST days)
    recs = []
    for r in rows[hi + 1:]:
        if str(r[head.index(UNIT)]).strip() == "":
            continue
        key = [r[k] for k in idx]
        for p, j in enumerate(slots):
            e, pr = r[j], r[j + 1]
            if e == "" or e is None:
                continue
            recs.append(key + [min(23, p * 24 // n), float(e), float(pr) if pr != "" else float("nan")])
    df = pd.DataFrame(recs, columns=ids + ["hour", "v", "eur_mwh"])
    if df.empty:
        return df
    if quarter:
        df["w"] = df.v.abs()
        df["pw"] = df.eur_mwh * df.w
        g = df.groupby(ids + ["hour"], dropna=False)
        out = g.agg(v=("v", "sum"), w=("w", "sum"), pw=("pw", "sum"), pm=("eur_mwh", "mean"), k=("v", "size")).reset_index()
        out["mwh"] = out.v * 24 / n                                   # MW summed over quarter-hours → MWh
        out["eur_mwh"] = (out.pw / out.w).where(out.w > 0, out.pm)
        df = out[ids + ["hour", "mwh", "eur_mwh"]]
    else:
        df = df.rename(columns={"v": "mwh"})
    return df[df.mwh != 0].reset_index(drop=True)


def flat_sheet(book, name):
    """A one-row-per-unit sheet (I90DIA18/33 complex offers, I90DIA29 start-up times)."""
    rows = _rows(book, name)
    if not rows:
        return pd.DataFrame()
    hi = _header(rows)
    head = [str(c).strip() for c in rows[hi]]
    df = pd.DataFrame(rows[hi + 1:], columns=head)
    df = df.loc[:, [c for c in head if c]]
    return df[df[UNIT].astype(str).str.strip() != ""].reset_index(drop=True)


def parse_day(xls_bytes, d):
    book = xlrd.open_workbook(file_contents=xls_bytes, on_demand=True)
    out = {"offers_tc": offer_sheet(book, "I90DIA17"),
           "offers_tc_rt": offer_sheet(book, "I90DIA32", quarter=True)}
    cx = [flat_sheet(book, s).assign(stage=st) for s, st in (("I90DIA18", "day-ahead"), ("I90DIA33", "real-time"))]
    cx = [x for x in cx if not x.empty]
    if cx:
        out["offers_complex"] = pd.concat(cx, ignore_index=True)
    out["startup_times"] = flat_sheet(book, "I90DIA29")
    out = {k: v for k, v in out.items() if not v.empty}
    for v in out.values():
        v.insert(0, "date", d)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("first", help="YYYY-MM-DD")
    ap.add_argument("last", help="YYYY-MM-DD")
    ap.add_argument("--out", type=Path,
                    default=Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download") / "i90_offers")
    ap.add_argument("--zips", type=Path, help="directory for the daily zips (default <out>/zips); reuses zips found there")
    ap.add_argument("--keep-zips", action="store_true")
    a = ap.parse_args()
    days = pd.date_range(a.first, a.last).strftime("%Y-%m-%d")
    ddir, zdir = a.out / "days", (a.zips or a.out / "zips")
    ddir.mkdir(parents=True, exist_ok=True); zdir.mkdir(parents=True, exist_ok=True)
    failed = []
    for i, d in enumerate(days, 1):
        if (ddir / f"{d}.done").exists():
            continue
        t = time.time()
        try:
            z, xls = fetch(d, zdir)
            parts = parse_day(xls, d)
        except Exception as e:
            print(f"[{i}/{len(days)}] {d}: FAILED ({e})", flush=True)
            failed.append(d)
            continue
        for k, v in parts.items():
            v.to_csv(ddir / f"{d}_{k}.csv", index=False)
        (ddir / f"{d}.done").touch()
        if not a.keep_zips and a.zips is None:
            z.unlink()
        print(f"[{i}/{len(days)}] {d}: " + ", ".join(f"{k} {len(v)}" for k, v in parts.items())
              + f"  ({time.time() - t:.0f} s)", flush=True)
    for k in TABLES:
        files = sorted(ddir.glob(f"*_{k}.csv"))
        if files:
            pd.concat((pd.read_csv(f) for f in files), ignore_index=True).to_csv(a.out / f"i90_{k}.csv.gz", index=False)
            print(f"  {a.out / f'i90_{k}.csv.gz'}: {len(files)} days")
    if failed:
        print(f"FAILED days ({len(failed)}): {' '.join(failed)}  (rerun the same command to retry)")


if __name__ == "__main__":
    main()
