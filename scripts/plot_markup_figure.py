"""Report figure for the [costs.markup] mark-ups: Lerner index of 2024 OMIE gas and coal bids near
the price against the hourly residual supply index (RSI).

Shows every counted hour (dots), the median per RSI interval (the intervals the gas mark-up is fitted
on in scripts/build_markup_table.py), and the mark-up the model uses (markup.jl: gas = the interval
medians joined linearly, flat beyond the ends, kept within 0 <= L <= cap; coal = the constant L_coal).
Hours and filters are the same as in build_markup_table.py: gas or coal bid steps within +-20 % of the
price, price at least 0.8 x the day's lowest gas (eta 0.60) or coal cost, generation tax taken out.
2024: 4,256 gas hours, 1,714 coal hours, coal median 0.188.

Visual style after the PowerVision paper (Koks et al. 2026): serif font (STIX), full frame, framed
legend, units in brackets, matplotlib default colours. Used in the project thesis, Ch. 4, Sec. 4.2
(Overleaf Images/markup-rsi-gas-coal-2024.pdf, Figure fig:method-markup).

    python scripts/plot_markup_figure.py [out path without extension]
    (default: results/markup-rsi-gas-coal-2024; writes .pdf and .png)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "Data" / "markup"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "markup-rsi-gas-coal-2024"
TAX = {1: 0.035, 2: 0.0525, 3: 0.07, 4: 0.07}         # as build_markup_table.py / config.toml
EDGES = [0, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 99]     # as build_markup_table.py
L_COAL, CAP = 0.188, 0.5                               # config.toml [costs.markup]

h = pd.read_csv(D / "omie_hourly_2024.csv")
c = pd.read_csv(D / "daily_costs_2024.csv")[["date", "gas_060", "coal"]]
h = h.merge(c, on="date")
h["tax"] = (h.date.str[5:7].astype(int).sub(1) // 3 + 1).map(TAX)


def hours(tag, costcol):
    x = h.dropna(subset=[f"L_{tag}"])
    x = x[x.price >= 0.8 * x[costcol]].copy()
    x["L"] = 1 - (1 - x[f"L_{tag}"]) / (1 - x.tax)      # tax taken out
    return x


def interval_medians(x):
    return x.groupby(pd.cut(x.rsi, EDGES), observed=True).agg(
        rsi=("rsi", "median"), L=("L", "median"), n=("L", "size"))


gas, coal = hours("gas", "gas_060"), hours("coal", "coal")
tab = pd.read_csv(D / "markup_table_2024.csv")
print(f"gas hours {len(gas)}, coal hours {len(coal)}, coal median {coal.L.median():.3f}")

xs = np.linspace(1.0, 2.7, 1000)
model_gas = np.clip(np.interp(xs, tab.rsi, tab.L_gas), 0, CAP)
model_coal = np.full_like(xs, L_COAL)

C0, C1 = "#1f77b4", "#ff7f0e"                 # matplotlib default colours, as in PowerVision
DARK = {C0: "#174a7c", C1: "#b35300"}         # darker shade of the same hue for the medians
plt.rcParams.update({
    "font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 10,
    "axes.linewidth": 0.8, "xtick.direction": "out", "ytick.direction": "out",
    "legend.frameon": True, "legend.fancybox": True, "legend.edgecolor": "#cccccc",
    "legend.framealpha": 0.95, "legend.fontsize": 8.5, "pdf.fonttype": 42,
})
fig, axes = plt.subplots(1, 2, figsize=(6.5, 2.9), sharey=True, constrained_layout=True)
panels = [(axes[0], gas, C0, model_gas, f"Gas ({len(gas):,} hours)", "upper right"),
          (axes[1], coal, C1, model_coal, f"Coal ({len(coal):,} hours)", "lower left")]
for ax, d, col, model, title, loc in panels:
    ax.axhline(0, color="#999999", lw=0.6, zorder=1)
    ax.scatter(d.rsi, d.L, s=4, color=col, alpha=0.22, linewidths=0, zorder=2, label="One hour of 2024")
    ax.plot(xs, model, color="black", lw=1.6, ls=(0, (5, 2.5)), zorder=3, label="Mark-up in the model")
    m = interval_medians(d)
    print(title, m.round(3).to_dict("list"))
    ax.plot(m.rsi, m.L, "o", ms=6, color=DARK[col], mec="white", mew=1.0, zorder=4,
            label="Median per RSI interval")
    ax.set_title(title, fontsize=10)
    ax.set_xlim(1.0, 2.7)
    ax.set_xlabel("Residual supply index [-]")
    hs, ls = ax.get_legend_handles_labels()
    order = [ls.index(k) for k in ("One hour of 2024", "Median per RSI interval", "Mark-up in the model")]
    leg = ax.legend([hs[i] for i in order], [ls[i] for i in order], loc=loc, handlelength=2.2)
    dots = leg.legend_handles[0]
    dots.set_sizes([22])
    dots.set_alpha(1)
axes[0].set_ylim(-0.4, 0.5)
axes[0].set_ylabel("Lerner index [-]")
OUT.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUT.with_suffix(".pdf"))
fig.savefig(OUT.with_suffix(".png"), dpi=200)
print("wrote", OUT.with_suffix(".pdf"), "and .png")
