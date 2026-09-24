"""
Observed Spanish market data, in a shape that does not assume two study days.

The validation reference shipped with the repository is written per study day:
`omie_price.csv` keys its rows by month name (`jul`, `dec`), `OMIE_intraday.csv`
puts the day in the COLUMN name (`2id_j8_tot`, `3id_d2_pos`), and the cleared
programme is one file per day (`actual_generation_July_8.csv`).  That shape
works for two days and cannot express a year.

This module defines a tidy alternative and prefers it when present, falling
back to the legacy files otherwise.  Both are normalised to the same structures,
so callers never branch on which one is in use:

    ref["price"][date]      Series, index hour 0-23, EUR/MWh
    ref["omie"][date]       DataFrame, index hour 0-23, columns = categories, MW
    ref["intraday"]         DataFrame(date, gate, tec, ref_neg_mw, ref_pos_mw)
    ref["days"]             sorted list of dates the reference covers

Tidy format — drop these into Data/OMIE/ and a full year works unchanged:

    reference_price.csv       date,hour,price_eur_mwh
    reference_generation.csv  date,hour,category,mw
    reference_intraday.csv    date,session,tec,neg_mw,pos_mw

`category` uses the vocabulary in `paper_figures_2024.CATEGORIES`; `session` is
the gate label (ID2, ID3, ...).  Each file is optional and falls back on its own,
so the year can arrive one series at a time.

On the intraday columns: `neg_mw` and `pos_mw` are the mean over the day's hours
of the downward and upward position change, taken hour by hour and only then
averaged — the construction the legacy file already uses (verified: its values
are exact 24ths, and neg + pos reproduces its `tot` column to the cent).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from paper_figures_2024 import (
    CATEGORIES,
    OMIE_CAT,
    OMIE_DIR,
    OMIE_FILE,
    OMIE_IMPORT_COLS,
    OMIE_PRICE_ROW,
)

TIDY_PRICE = "reference_price.csv"
TIDY_GENERATION = "reference_generation.csv"
TIDY_INTRADAY = "reference_intraday.csv"

# Legacy OMIE_intraday.csv column prefixes → gate label, and its per-day tags.
LEGACY_SESSION = {"2id": "ID2", "3id": "ID3"}
LEGACY_DAY_TAG = {"2024-07-08": "j8", "2024-12-02": "d2"}


def _read(path: Path):
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path)


# ── price ────────────────────────────────────────────────────────────────────
def _price_tidy(root: Path):
    df = _read(root / TIDY_PRICE)
    if df is None:
        return None
    df["date"] = df["date"].astype(str)
    return {d: g.set_index("hour")["price_eur_mwh"].reindex(range(24))
            for d, g in df.groupby("date")}


def _price_legacy(root: Path):
    df = _read(root / "omie_price.csv")
    if df is None:
        return {}
    df = df.set_index(df.columns[0])
    out = {}
    for date, row in OMIE_PRICE_ROW.items():
        if row in df.index:
            out[date] = pd.Series(df.loc[row].to_numpy(dtype=float)[:24],
                                  index=range(24))
    return out


# ── cleared generation programme ─────────────────────────────────────────────
def _generation_tidy(root: Path):
    df = _read(root / TIDY_GENERATION)
    if df is None:
        return None
    df["date"] = df["date"].astype(str)
    out = {}
    for d, g in df.groupby("date"):
        piv = (g.pivot_table(index="hour", columns="category", values="mw",
                             aggfunc="sum")
                .reindex(range(24)).fillna(0.0))
        out[d] = piv.reindex(columns=[c for c in CATEGORIES if c in piv.columns])
    return out


def _generation_legacy(root: Path):
    out = {}
    for date, fname in OMIE_FILE.items():
        raw = _read(root / fname)
        if raw is None:
            continue
        raw = raw.apply(pd.to_numeric, errors="coerce").fillna(0.0)
        frame = pd.DataFrame(index=range(24))
        for col, cat in OMIE_CAT.items():
            if col in raw.columns:
                frame[cat] = frame.get(cat, 0.0) + raw[col].to_numpy()[:24]
        imp = sum(raw[c].to_numpy()[:24] for c in OMIE_IMPORT_COLS
                  if c in raw.columns)
        frame["Imports"] = imp
        out[date] = frame.reindex(
            columns=[c for c in CATEGORIES if c in frame.columns]).fillna(0.0)
    return out


# ── intraday session volumes ─────────────────────────────────────────────────
COLS = ["date", "gate", "tec", "ref_neg_mw", "ref_pos_mw"]


def _intraday_tidy(root: Path):
    df = _read(root / TIDY_INTRADAY)
    if df is None:
        return None
    return pd.DataFrame({
        "date": df["date"].astype(str),
        "gate": df["session"].astype(str),
        "tec": df["tec"].astype(str).str.strip(),
        "ref_neg_mw": df["neg_mw"].astype(float),
        "ref_pos_mw": df["pos_mw"].astype(float),
    })


def _intraday_legacy(root: Path):
    raw = _read(root / "OMIE_intraday.csv")
    if raw is None:
        return pd.DataFrame(columns=COLS)
    raw = raw.set_index(raw.columns[0])
    raw.index = [str(i).strip() for i in raw.index]
    rows = []
    for date, tag in LEGACY_DAY_TAG.items():
        for sess, gate in LEGACY_SESSION.items():
            neg_c, pos_c = f"{sess}_{tag}_neg", f"{sess}_{tag}_pos"
            if neg_c not in raw.columns or pos_c not in raw.columns:
                continue
            for tec in raw.index:
                rows.append({"date": date, "gate": gate, "tec": tec,
                             "ref_neg_mw": float(raw.loc[tec, neg_c]),
                             "ref_pos_mw": float(raw.loc[tec, pos_c])})
    return pd.DataFrame(rows, columns=COLS)


# ── public ───────────────────────────────────────────────────────────────────
def load_reference(root=None, verbose: bool = True) -> dict:
    """Observed reference data, tidy format where available, legacy otherwise."""
    root = Path(root) if root is not None else Path(OMIE_DIR)
    sources = {}

    price = _price_tidy(root)
    sources["price"] = "tidy" if price is not None else "legacy"
    if price is None:
        price = _price_legacy(root)

    gen = _generation_tidy(root)
    sources["generation"] = "tidy" if gen is not None else "legacy"
    if gen is None:
        gen = _generation_legacy(root)

    intr = _intraday_tidy(root)
    sources["intraday"] = "tidy" if intr is not None else "legacy"
    if intr is None:
        intr = _intraday_legacy(root)

    days = sorted(set(price) | set(gen) |
                  set(intr["date"].unique() if not intr.empty else []))
    if verbose:
        desc = ", ".join(f"{k}={v}" for k, v in sources.items())
        print(f"Reference data             : {len(days)} day(s) [{desc}]")
        if all(v == "legacy" for v in sources.values()):
            print(f"  (legacy per-day files; for a longer horizon add "
                  f"{TIDY_PRICE} / {TIDY_GENERATION} / {TIDY_INTRADAY} "
                  f"to {root})")
    return {"price": price, "omie": gen, "intraday": intr,
            "days": days, "sources": sources}


__all__ = ["load_reference", "TIDY_PRICE", "TIDY_GENERATION", "TIDY_INTRADAY"]
