"""Spring diagnosis, part 3: model phase I up by technology and month vs REE (I90), and Ascó in the model."""
import sys, glob, os, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
W = r"C:\Users\magnu\dev\Spain_power_system\.claude\worktrees\redispatch-realism"
R = r"C:\Users\magnu\dev\solstorm_results\y24act"
p = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(R, "2024-*", "rd_phase1.csv")))])
p["d"] = (p.phase1_mw - p.da_mw).clip(lower=0)
p["m"] = p.date.str[5:7]
G = {"Combined_cycle": "CCGT", "Gas_turbine": "CCGT", "Coal": "coal", "Nuclear": "nuclear", "reservoir": "hydro",
     "run_of_river": "hydro", "pumped_storage": "pumped storage", "CHP": "CHP"}
p["g"] = p.technology.map(G).fillna("other")
mdl = p.pivot_table(index="m", columns="g", values="d", aggfunc="sum", fill_value=0) / 1e3
ph = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_tc_phase.csv.gz", encoding="utf-8", encoding_errors="replace")
ph = ph.rename(columns={ph.columns[3]: "unit"})
up = ph[ph.Redespacho.str.startswith("UPO") & (ph.Sentido == "Subir")].copy()
tech = pd.read_csv(os.path.join(W, "redispatch_realism", "data", "ree_unit_technology.csv")).set_index("ree_unit").group
up["g"] = up.unit.str.strip().map(tech).replace({"pumped storage (pump)": "pumped storage", "pumped storage (turbine)": "pumped storage"}).fillna("other")
up["m"] = up.date.str[5:7]
ree = up.pivot_table(index="m", columns="g", values="mwh", aggfunc="sum", fill_value=0) / 1e3
t = pd.DataFrame({"REE nuclear": ree.get("nuclear", 0), "model nuclear": mdl.get("nuclear", 0),
                  "REE non-nuclear": ree.sum(axis=1) - ree.get("nuclear", 0), "model non-nuclear": mdl.sum(axis=1) - mdl.get("nuclear", 0),
                  "REE CCGT": ree.get("CCGT", 0), "model CCGT": mdl.get("CCGT", 0), "REE coal": ree.get("coal", 0), "model coal": mdl.get("coal", 0),
                  "model hydro": mdl.get("hydro", 0)})
t.loc["total"] = t.sum()
print("phase I up by technology (GWh):"); print(t.round(0).to_string())
g = pd.read_csv(os.path.join(W, "Data", "generations.csv"))
print("\nmodel nuclear units:"); print(g[g.primary_fuel == "Nuclear"][["unit_id", "bus_id", "name", "capacity_mw", "y", "x"]].to_string(index=False))
