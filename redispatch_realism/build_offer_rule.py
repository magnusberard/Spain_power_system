"""A rule for phase II's buy-back (down) offers, for runs without REE's offers (2035), built from 2024's offers.

For every curve in phase2_offers_2024_tail.csv (per model unit and hour, plus the pooled per-technology curves),
the price at fixed points of its volume, EDGES = 1, 2, 5, 10, 20, 50, 100 % (segments taken highest price first,
as the model does), is put relative to that hour's day-ahead price (OMIE). Two forms, fixed before the data were seen
(5 Nov): RATIO, price = r_tech,e x p_DA; DISCOUNT, price = p_DA - d_tech,e (EUR/MWh). Both estimated as medians on
January-June 2024, hours with p_DA >= 10 EUR/MWh; the form with the lower January-June error in the system cost of
turning down (p_DA - min(price, p_DA), EUR/MWh) is kept. Test: July-December 2024, the same error, per technology and
edge, and the cost of turning 5 %, 20 % and 100 % of a unit down, rule against REE's offers.
Writes data/phase2_offer_rule.csv: technology (fuel:technology), share (segment width), ratio or discount.

    python redispatch_realism/build_offer_rule.py
"""
import os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
HERE = Path(__file__).resolve().parent
D = Path(os.environ.get("ESIOS_DIR", r"C:\Users\magnu\dev\esios_download"))
EDGES = [0.01, 0.02, 0.05, 0.10, 0.20, 0.50, 1.00]

o = pd.read_csv(D / "phase2_offers_2024_tail.csv")
gen = pd.read_csv(HERE.parent / "Data" / "generations.csv").set_index("unit_id")
def tech_of(k):
    if k.startswith("tech:"):
        return k[5:]
    return f"{gen.primary_fuel.get(k, '?')}:{gen.technology.get(k, '?')}" if k in gen.index else "?"
o["tech"] = o.key.map({k: tech_of(k) for k in o.key.unique()})
pda = pd.read_csv(Path(r"C:\Users\magnu\dev\spain-model-runs\reference\real_hourly_2024.csv.gz"))[["date", "hour", "price"]]
o = o.merge(pda, on=["date", "hour"], how="left").rename(columns={"price": "p_da", "price_x": "price"}) if "price" in o else o
o = o.rename(columns={"price_x": "price", "price_y": "p_da"})
o = o.sort_values(["date", "hour", "key", "price"], ascending=[True, True, True, False])
o["cum"] = o.groupby(["date", "hour", "key"]).share.cumsum()

# price at each edge: the price of the segment that covers that cumulative share
rows = []
for e in EDGES:
    x = o[o.cum >= e - 1e-9].groupby(["date", "hour", "key"]).head(1)
    rows.append(x.assign(edge=e)[["date", "hour", "key", "tech", "p_da", "price", "edge"]])
pts = pd.concat(rows, ignore_index=True)
pts = pts[pts.tech != "?"]
pts["h1"] = pts.date < "2024-07-01"
ok = pts.p_da >= 10
pts["ratio"] = pts.price / pts.p_da
pts["disc"] = pts.p_da - pts.price
fit = pts[pts.h1 & ok].groupby(["tech", "edge"]).agg(ratio=("ratio", "median"), discount=("disc", "median"), n=("ratio", "size"))

def sys_cost(p_da, price):
    return p_da - np.minimum(price, p_da)
def err(df, form):
    f = fit.reindex(pd.MultiIndex.from_frame(df[["tech", "edge"]]))
    pred = df.p_da.values * f.ratio.values if form == "ratio" else df.p_da.values - f.discount.values
    return np.abs(sys_cost(df.p_da.values, pred) - sys_cost(df.p_da.values, df.price.values))
h1, h2 = pts[pts.h1 & ok], pts[~pts.h1 & ok]
e_r, e_d = np.nanmean(err(h1, "ratio")), np.nanmean(err(h1, "discount"))
form = "ratio" if e_r <= e_d else "discount"
print(f"Jan-Jun mean error in the cost of turning down (EUR/MWh): ratio {e_r:.2f}, discount {e_d:.2f} -> {form}")
e2 = err(h2, form)
print(f"Jul-Dec (test) mean error: {np.nanmean(e2):.2f} EUR/MWh; real mean cost {sys_cost(h2.p_da, h2.price).mean():.2f} EUR/MWh")

# test per technology: cost of turning 5 %, 20 %, 100 % of a unit down, rule vs offers, Jul-Dec
def cost_upto(df_curve, frac, p_da, rule_prices=None):
    pass
print("\nJul-Dec, mean system cost per MWh turned down at each edge, real offers vs rule:")
h2 = h2.assign(real=sys_cost(h2.p_da, h2.price))
f = fit.reindex(pd.MultiIndex.from_frame(h2[["tech", "edge"]]))
h2 = h2.assign(rule=sys_cost(h2.p_da.values, h2.p_da.values * f.ratio.values if form == "ratio" else h2.p_da.values - f.discount.values))
t = h2.groupby(["tech", "edge"])[["real", "rule"]].mean().unstack("edge")
print(t.round(1).to_string())
w = h2.groupby("tech")[["real", "rule"]].mean()
w["n"] = h2.groupby("tech").size()
print("\nby technology (all edges):"); print(w.round(2).to_string())
print("rank correlation of technologies by cost, real vs rule:", round(w.real.rank().corr(w.rule.rank()), 2))

rule = fit.reset_index()
rule["share"] = rule.groupby("tech").edge.diff().fillna(rule.edge)
out = rule[["tech", "edge", "share", "ratio", "discount", "n"]].rename(columns={"tech": "technology"})
out.insert(0, "form", form)
out.to_csv(HERE / "data" / "phase2_offer_rule.csv", index=False, float_format="%.4f")
print(f"\nwrote data/phase2_offer_rule.csv ({len(out)} rows, form {form})")
print(out[out.technology.isin(["Gas:Combined_cycle", "Wind:Onshore", "Solar:PV", "Hydro:reservoir", "Nuclear:Nuclear", "Gas:CHP"])].round(3).to_string(index=False))
