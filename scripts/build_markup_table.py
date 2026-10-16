"""Build the [costs.markup] inputs from OMIE's 2024 day-ahead bids.

Inputs (Data/markup/):
  omie_hourly_2024.csv   one row per OMIE hour of 2024, from
                         omie_conversion/markup_rsi.py: Spanish price, matched
                         demand, offered capacity, largest firm's offered capacity,
                         RSI, and the MW-weighted Lerner index (bid - cost)/bid of
                         the gas and of the coal bid steps within +-20 % of the
                         price (cost = the model's own daily cost,
                         daily_costs_2024.csv from scripts/export_daily_costs.jl).
Outputs (Data/markup/):
  rsi_2024.csv           date, hour (0-23, the model's hours), rsi
  markup_table_2024.csv  rsi, L_gas, L_coal: one point per RSI interval (the
                         interval's median RSI and median L), read by markup.jl and
                         interpolated linearly between points.

Choices (documented in config.toml [costs.markup]):
  - L is measured over cost INCLUDING the generation tax (IVPEE, 7 % of the
    value of production; 2024: 3.5 % Q1, 5.25 % Q2, 7 % H2 after RDL 8/2023):
    1 - L_tax = (1 - L) / (1 - tax).
  - Hours count only where the price is at least 0.8 x the cheapest gas cost
    (eta 0.60) or coal cost that day: below that, gas/coal "near the price" are
    must-run bids, not price-setting ones.
  - Intervals of RSI 0.1 wide, the sparse ends merged (< 1.3, >= 1.9).

    python scripts/build_markup_table.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

D = Path(__file__).resolve().parent.parent / "Data" / "markup"
TAX = {1: 0.035, 2: 0.0525, 3: 0.07, 4: 0.07}
EDGES = [0, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 99]

h = pd.read_csv(D / "omie_hourly_2024.csv")
c = pd.read_csv(D / "daily_costs_2024.csv")[["date", "gas_060", "coal"]]
h = h.merge(c, on="date")
h["tax"] = (h.date.str[5:7].astype(int).sub(1) // 3 + 1).map(TAX)


def points(tag, costcol, edges):
    x = h.dropna(subset=[f"L_{tag}"])
    x = x[x.price >= 0.8 * x[costcol]].copy()
    x["L"] = 1 - (1 - x[f"L_{tag}"]) / (1 - x.tax)
    return x.groupby(pd.cut(x.rsi, edges), observed=True).agg(
        rsi=("rsi", "median"), L=("L", "median"), hours=("L", "size"))


gas, coal = points("gas", "gas_060", EDGES), points("coal", "coal", EDGES)
# one table: the gas interval medians of RSI as x; coal L read at the same intervals
tab = pd.DataFrame({"rsi": gas.rsi.round(4), "L_gas": gas.L.round(4), "L_coal": coal.L.values.round(4),
                    "hours_gas": gas.hours.values, "hours_coal": coal.hours.values})
tab.to_csv(D / "markup_table_2024.csv", index=False)
print(tab.to_string(index=False))

# sensitivity: 0.05 and 0.2 wide intervals, gas, read at the 0.1 points
for w in (0.05, 0.2):
    e = [0, 1.3] + list(np.round(np.arange(1.3 + w, 1.9 + 1e-9, w), 3)) + [99]
    p = points("gas", "gas_060", e)
    at = np.interp(tab.rsi, p.rsi, p.L)
    print(f"gas, {w}-wide intervals: max |L - L(0.1)| at the table points = {np.max(np.abs(at - tab.L_gas)):.3f}")

# hourly RSI on the model's 0-23 hours. OMIE numbers periods 1-23/24/25 in local
# time; on the 23-period day (March) hour 2 is missing -> period of hour 1 reused;
# on the 25-period day (October) the two 02:00 periods are averaged.
rows = []
for d, g in h.groupby("date"):
    r = g.sort_values("hour").rsi.to_numpy()
    if len(r) == 23:
        r = np.r_[r[:2], r[1], r[2:]]
    elif len(r) == 25:
        r = np.r_[r[:2], (r[2] + r[3]) / 2, r[4:]]
    rows += [(d, k, round(float(v), 4)) for k, v in enumerate(r)]
pd.DataFrame(rows, columns=["date", "hour", "rsi"]).to_csv(D / "rsi_2024.csv", index=False)
print(f"wrote {D / 'markup_table_2024.csv'} and {D / 'rsi_2024.csv'} ({len(rows)} hours)")
