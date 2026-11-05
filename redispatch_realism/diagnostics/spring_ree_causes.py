import sys, pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
ph = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_tc_phase.csv.gz", encoding="utf-8", encoding_errors="replace")
ph = ph.rename(columns={ph.columns[3]: "unit", ph.columns[7]: "cause"})
up = ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")].copy()
tech = pd.read_csv(r"C:\Users\magnu\dev\Spain_power_system\.claude\worktrees\redispatch-realism\redispatch_realism\data\ree_unit_technology.csv").set_index("ree_unit")
up["g"] = up.unit.str.strip().map(tech.group).fillna("unmapped")
up["m"] = up.date.str[5:7]
sp = up[up.m.isin(["03", "04", "05", "06"])]
print("cause x technology, Mar-Jun (GWh):")
print((sp.pivot_table(index="g", columns="cause", values="mwh", aggfunc="sum", fill_value=0) / 1e3).round(0).to_string())
nu = up[up.g == "nuclear"]
print("\nnuclear phase I up by unit and month (GWh):")
t = nu.pivot_table(index="unit", columns="m", values="mwh", aggfunc="sum", fill_value=0) / 1e3
t.insert(0, "name", [tech.description.get(u.strip(), "") for u in t.index])
print(t.round(0).to_string())
nsp = nu[nu.m.isin(["03", "04", "05"])]
print("\nnuclear phase I up, mean MW by hour of day (Mar-May):")
print((nsp.groupby("hour").mwh.sum() / nsp.date.nunique()).round(0).to_dict())
w = nu.eur_mwh.notna()
print("nuclear phase I up: mean price", round(np.average(nu.eur_mwh[w], weights=nu.mwh[w]), 1), "EUR/MWh;",
      "unit-hours", len(nu), "; mean MW per unit-hour", round(nu.mwh.mean()))
print("\nnuclear days with phase I up, Mar-May:", nsp.date.nunique(), "of 92")
