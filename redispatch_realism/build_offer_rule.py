"""A rule for phase II's buy-back (down) offers, for runs without REE's offers (2035), built from REE's offers.

For every curve in a phase II offers file (build_phase2_offers.py: per model unit and hour, plus pooled per-technology
curves), the price at fixed points of its volume, EDGES = 1, 2, 5, 10, 20, 50, 100 % (segments taken highest price
first, as the model does), is put relative to that hour's day-ahead price (OMIE). Two forms, fixed before the data
were seen (5 Nov): RATIO, price = r_tech,e x p_DA; DISCOUNT, price = p_DA - d_tech,e (EUR/MWh). Both are estimated as
medians over the estimation period, hours with p_DA >= 10 EUR/MWh; the form with the lower estimation-period error in
the system cost of turning down (p_DA - min(price, p_DA), EUR/MWh) is kept and judged on the test period: the same
error, per technology and edge, and whether the technologies' order is kept.

Periods (--fit / --test): "2024H1"/"2024H2" (the first version) or whole years, e.g. --fit 2023 --test 2024 (full
seasons both ways; 2023's day-ahead prices from fetch_omie_prices.py). Writes data/phase2_offer_rule.csv:
technology (fuel:technology), edge, share (segment width), ratio, discount, n.

    python redispatch_realism/build_offer_rule.py --fit 2023 --test 2024
    python redispatch_realism/build_offer_rule.py --fit 2024H1 --test 2024H2
    python redispatch_realism/build_offer_rule.py --fit 2023+2024 --test 2024   # final rule, all data (test in-sample)
"""
import argparse, os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
HERE = Path(__file__).resolve().parent
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
EDGES = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00]
OFFERS = {"2023": D / "phase2_offers_2023_tail.csv", "2024": D / "phase2_offers_2024_tail.csv"}
PRICES = {"2023": D / "omie_prices_2023.csv",
          "2024": Path(r"C:\Users\magnu\dev\spain-model-runs\reference\real_hourly_2024.csv.gz")}
gen = pd.read_csv(HERE.parent / "Data" / "generations.csv").set_index("unit_id")

def tech_of(k):
    if k.startswith("tech:"):
        return k[5:]
    return f"{gen.primary_fuel.get(k, '?')}:{gen.technology.get(k, '?')}" if k in gen.index else "?"

def edge_points(period):
    """Price at each edge of every curve in a period ("2023", "2024", "2024H1", "2024H2", or several joined by "+",
    e.g. "2023+2024" for the final rule on all data), with that hour's p_DA."""
    if "+" in period:
        return pd.concat([edge_points(p) for p in period.split("+")], ignore_index=True)
    year, half = period[:4], period[4:]
    o = pd.read_csv(OFFERS[year])
    if half:
        o = o[(o.date < f"{year}-07-01") if half == "H1" else (o.date >= f"{year}-07-01")]
    o["tech"] = o.key.map({k: tech_of(k) for k in o.key.unique()})
    pda = pd.read_csv(PRICES[year])[["date", "hour", "price"]].rename(columns={"price": "p_da"})
    o = o.merge(pda, on=["date", "hour"], how="inner")
    o = o.sort_values(["date", "hour", "key", "price"], ascending=[True, True, True, False])
    o["cum"] = o.groupby(["date", "hour", "key"]).share.cumsum()
    rows = []
    for e in EDGES:
        x = o[o.cum >= e - 1e-9].groupby(["date", "hour", "key"]).head(1)
        rows.append(x.assign(edge=e)[["date", "hour", "key", "tech", "p_da", "price", "edge"]])
    pts = pd.concat(rows, ignore_index=True)
    pts = pts[(pts.tech != "?") & (pts.p_da >= 10)]
    pts["ratio"] = pts.price / pts.p_da
    pts["disc"] = pts.p_da - pts.price
    return pts

def sys_cost(p_da, price):
    return p_da - np.minimum(price, p_da)

def predict(df, fit, form):
    f = fit.reindex(pd.MultiIndex.from_frame(df[["tech", "edge"]]))
    return df.p_da.values * f.ratio.values if form == "ratio" else df.p_da.values - f.discount.values

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", default="2024H1"); ap.add_argument("--test", default="2024H2")
    a = ap.parse_args()
    fp, tp = edge_points(a.fit), edge_points(a.test)
    print(f"estimation {a.fit}: {fp.date.nunique()} days, {len(fp):,} edge points | test {a.test}: {tp.date.nunique()} days, {len(tp):,}")
    fit = fp.groupby(["tech", "edge"]).agg(ratio=("ratio", "median"), discount=("disc", "median"), n=("ratio", "size"))
    real_f = sys_cost(fp.p_da.values, fp.price.values)
    e = {form: np.nanmean(np.abs(sys_cost(fp.p_da.values, predict(fp, fit, form)) - real_f)) for form in ("ratio", "discount")}
    form = min(e, key=e.get)
    print(f"{a.fit} mean error in the cost of turning down (EUR/MWh): ratio {e['ratio']:.2f}, discount {e['discount']:.2f} -> {form}")
    tp = tp.assign(real=sys_cost(tp.p_da.values, tp.price.values), rule=sys_cost(tp.p_da.values, predict(tp, fit, form)))
    print(f"{a.test} (test) mean error {np.nanmean(np.abs(tp.rule - tp.real)):.2f} EUR/MWh; real mean cost {tp.real.mean():.2f}; "
          f"rule mean cost {tp.rule.mean():.2f}; technologies without a rule: {sorted(set(tp.tech) - set(fp.tech))}")
    print(f"\n{a.test}, mean system cost per MWh turned down at each edge, real offers vs rule:")
    print(tp.groupby(["tech", "edge"])[["real", "rule"]].mean().unstack("edge").round(1).to_string())
    w = tp.groupby("tech")[["real", "rule"]].mean()
    w["n"] = tp.groupby("tech").size()
    print("\nby technology (all edges):"); print(w.round(2).to_string())
    print("rank correlation of technologies by cost, real vs rule:", round(w.dropna().real.rank().corr(w.dropna().rule.rank()), 2))
    rule = fit.reset_index()
    rule["share"] = rule.groupby("tech").edge.diff().fillna(rule.edge)
    out = rule[["tech", "edge", "share", "ratio", "discount", "n"]].rename(columns={"tech": "technology"})
    out.insert(0, "form", form)
    out.insert(1, "estimated_on", a.fit)
    out.to_csv(HERE / "data" / "phase2_offer_rule.csv", index=False, float_format="%.4f")
    print(f"\nwrote data/phase2_offer_rule.csv ({len(out)} rows, form {form}, estimated on {a.fit})")

if __name__ == "__main__":
    main()
