"""Step 4: phase II's down offers from REE's own buy-back offers, per model unit and hour (replaces B's fitted prices).

P.O. 3.2 §6.2.2: in phase II REE takes the offers to reduce the schedule in decreasing price. REE's I90DIA17 holds every
such offer (Sentido = Compra: energy and buy-back price per unit, block and hour; fetch_i90_offers.py). Agreed 2 Nov
2026: 2024 runs use each day's own offers (input, not a fit to REE's results); 2035 will use an offer rule instead.

Per (date, hour) this writes a down-offer curve as segments (share of the unit's own schedule, price €/MWh), sorted
from the highest buy-back price (cheapest to turn down) to the lowest:

  unit curves   a model unit matched to REE units (ree_unit_crosswalk.csv, model_unit_id / model_units_multi): the
                blocks of its REE units in that hour, by their energy shares (the model's schedule differs from REE's,
                so REE's MWh are used as shares of the unit's own schedule, not as MWh)
  group curves  per model fuel:technology, the pooled blocks of every REE unit of that technology in that hour
                (data/ree_unit_technology.csv), compressed to --segments equal-energy segments at their
                energy-weighted prices; used by model units without their own offers in the hour
  left out      pumped storage (kept out of phase II until phase I has a state of charge, decision of 30 Oct),
                and REE units with no technology ("unidentified", 12.6 % of Jan-Jun phase II down)

Two stated rules (applied in redispatch_objective.jl, not here): the refund is capped at the day-ahead price, since
phase II only restores the balance after phase I and REE never redispatches for profit (P.O. 3.2 §6.2); a model unit
or technology with no curve in an hour keeps its [redispatch.bids] value.

    python redispatch_realism/build_phase2_offers.py --from 2024-12-02 --to 2024-12-29 \
        --offers ../esios_download/i90_offers ../esios_download/i90_offers_h2 --out redispatch_realism/data/phase2_offers_dec.csv
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
UNIT = "Unidad de Programación"

# model fuel:technology -> REE group (data/ree_unit_technology.csv); None = left out of phase II offers
MODEL_GROUP = {
    "Biomass:Biomass": "biomass and waste", "Biomass:CHP_Waste": "biomass and waste",
    "Coal:Coal": "coal", "Gas:Combined_cycle": "CCGT",
    "Gas:Gas_turbine": "CCGT",          # stated: REE has no separate open-cycle gas group on the peninsula
    "Gas:CHP": "CHP", "Oil:Combined_cycle": "oil",
    "Hydro:reservoir": "hydro", "Hydro:run_of_river": "run-of-river", "Hydro:mini_hydro": "run-of-river",
    "Hydro:pumped_storage": None,       # kept out (decision of 30 Oct)
    "Nuclear:Nuclear": "nuclear",
    "Solar:PV": "solar PV", "Solar:Solar Thermal": "solar thermal",
    "Wind:Onshore": "wind", "Wind:Offshore": "wind",
}


def curve(blocks, k=None):
    """blocks: DataFrame with e (MWh > 0) and p (€/MWh). Segments (share, price) from the highest price down;
    with k, compressed to k equal-energy segments at their energy-weighted prices."""
    b = blocks[blocks.e > 0].sort_values("p", ascending=False)
    tot = b.e.sum()
    if tot <= 0:
        return []
    if k is None or len(b) <= k:
        g = b.groupby("p", sort=False).e.sum()
        return [(e / tot, p) for p, e in g.items()]
    edges = np.linspace(0, tot, k + 1)
    cum0 = np.concatenate([[0.0], b.e.cumsum().values[:-1]])
    cum1 = cum0 + b.e.values
    out = []
    for i in range(k):
        lo, hi = edges[i], edges[i + 1]
        w = np.clip(np.minimum(cum1, hi) - np.maximum(cum0, lo), 0, None)
        if w.sum() > 0:
            out.append(((hi - lo) / tot, float((w * b.p.values).sum() / w.sum())))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="first", required=True)
    ap.add_argument("--to", dest="last", required=True)
    esios = Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download")
    ap.add_argument("--offers", nargs="+", type=Path, default=[esios / "i90_offers", esios / "i90_offers_h2"])
    ap.add_argument("--segments", type=int, default=5, help="segments of a pooled technology curve (equal energy)")
    ap.add_argument("--unit-segments", type=int, default=5, help="at most this many segments per unit curve")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    parts = []
    for d in a.offers:
        f = d / "i90_offers_tc.csv.gz"
        if not f.exists():
            continue
        for ch in pd.read_csv(f, chunksize=2_000_000, usecols=["date", "hour", "Sentido", UNIT, "mwh", "eur_mwh"]):
            ch = ch[(ch.Sentido == "Compra") & (ch.date >= a.first) & (ch.date <= a.last)]
            if len(ch):
                parts.append(ch)
    off = pd.concat(parts, ignore_index=True)
    off = off.assign(u=off[UNIT].str.strip(), e=off.mwh.abs(), p=off.eur_mwh).drop(columns=[UNIT, "Sentido", "mwh", "eur_mwh"])
    off = off[off.p.notna()]
    days = sorted(off.date.unique())
    print(f"buy-back offers {a.first} .. {a.last}: {len(off):,} block-hours, {len(days)} days, {off.u.nunique()} REE units")

    tech = pd.read_csv(HERE / "data" / "ree_unit_technology.csv").set_index("ree_unit").group
    off["group"] = off.u.map(tech).fillna("unidentified")

    cw = pd.read_csv(HERE / "ree_unit_crosswalk.csv")
    pairs = []
    for r in cw.itertuples():
        ids = ([r.model_unit_id] if isinstance(r.model_unit_id, str) else []) + \
              (r.model_units_multi.split() if isinstance(r.model_units_multi, str) else [])
        pairs += [(r.ree_unit, m) for m in ids]
    pairs = pd.DataFrame(pairs, columns=["u", "model_unit"]).drop_duplicates()
    gen = pd.read_csv(REPO / "Data" / "generations.csv").set_index("unit_id")
    pairs["key"] = (gen.primary_fuel + ":" + gen.technology).reindex(pairs.model_unit).values
    pairs = pairs[pairs.key.map(MODEL_GROUP).notna()]          # pumped storage and unknown kinds left out
    print(f"model units with their own REE offers: {pairs.model_unit.nunique()} (from {pairs.u.nunique()} REE units)")

    rows = []
    # unit curves
    m = off.merge(pairs[["u", "model_unit"]], on="u")
    for (d, h, mu), b in m.groupby(["date", "hour", "model_unit"], sort=False):
        for i, (s, p) in enumerate(curve(b, a.unit_segments)):
            rows.append((d, h, mu, i, round(s, 6), round(p, 3)))
    n_unit = len(rows)
    # group curves, keyed by model fuel:technology
    for key, grp in MODEL_GROUP.items():
        if grp is None:
            continue
        sub = off[off.group == grp]
        for (d, h), b in sub.groupby(["date", "hour"], sort=False):
            for i, (s, p) in enumerate(curve(b, a.segments)):
                rows.append((d, h, "tech:" + key, i, round(s, 6), round(p, 3)))
    out = pd.DataFrame(rows, columns=["date", "hour", "key", "seg", "share", "price"])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False)
    print(f"{a.out}: {n_unit:,} unit-curve segments, {len(out) - n_unit:,} technology-curve segments")
    # what the curves say, per technology: energy-weighted mean buy-back price over the period
    g = off[off.group != "unidentified"].groupby("group").apply(lambda b: pd.Series(
        {"GWh_offered": b.e.sum() / 1e3, "mean_price": (b.e * b.p).sum() / b.e.sum(), "share_at_0": b.e[b.p == 0].sum() / b.e.sum()}))
    print(g.round(2).sort_values("mean_price", ascending=False).to_string())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
