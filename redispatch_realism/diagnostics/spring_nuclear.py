"""Spring diagnosis, part 2: nuclear. Model DA nuclear (y24act) vs OMIE's day-ahead programme (before REE's phase I)
and actual nuclear output (ENTSO-E, after phase I and real time); per month and hour of day; Ascó in particular."""
import sys, glob, os, pandas as pd, numpy as np
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
W = r"C:\Users\magnu\dev\Spain_power_system\.claude\worktrees\redispatch-realism"
real = pd.read_csv(r"C:\Users\magnu\dev\spain-model-runs\reference\real_hourly_2024.csv.gz")
real["m"] = real.date.str[5:7]
gens = pd.read_csv(os.path.join(W, "Data", "generations.csv"))
print("generations.csv columns:", list(gens.columns)[:10])
nuc = gens[gens.iloc[:, 2] == "Nuclear"]
print("model nuclear units:", nuc.iloc[:, [0, 1, 5]].to_string(index=False))
R = r"C:\Users\magnu\dev\solstorm_results\y24act"
da = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(R, "2024-*", "da_dispatch.csv")))])
da = da[da.fuel == "Nuclear"]
mdl = da.groupby(["date", "hour"]).dispatch_mw.sum().rename("model_DA").reset_index()
j = real.merge(mdl, on=["date", "hour"], how="left")
j["phase1_add"] = j.phys_Nuclear - j.omie_Nuclear
print("\nnuclear, mean MW by month: OMIE day-ahead (before phase I), actual (ENTSO-E), model day-ahead")
print(j.groupby("m")[["omie_Nuclear", "phys_Nuclear", "model_DA"]].mean().round(0).T.to_string())
sp = j[j.m.isin(["03", "04", "05"])]
print("\nspring (Mar-May), mean MW by hour of day:")
print(sp.groupby("hour")[["omie_Nuclear", "phys_Nuclear", "model_DA"]].mean().round(0).T.to_string())
# per unit, Ascó: model's units at Ascó vs REE's PDVP and phase I up
by_unit = da[da.date.str[5:7].isin(["03", "04", "05"])].groupby("gen_id").dispatch_mw.mean().round(0)
print("\nmodel DA nuclear by unit, spring mean MW:"); print(by_unit.to_string())
