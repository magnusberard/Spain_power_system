"""Spring diagnosis, part 4: Ascó (ASC1, ASC2) before (PDBF) and after (PDVP) REE's phase I vs the model's DA."""
import sys, glob, os, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 250)
pv = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_pdvp.csv.gz", encoding="utf-8", encoding_errors="replace")
pv = pv.iloc[:, [0, 1, 3, 4]]; pv.columns = ["date", "unit", "hour", "mwh"]
pv["unit"] = pv.unit.str.strip()
ph = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_tc_phase.csv.gz", encoding="utf-8", encoding_errors="replace")
ph = ph.rename(columns={ph.columns[3]: "unit", ph.columns[7]: "cause"}); ph["unit"] = ph.unit.str.strip()
units = {"ASC1": "G0138", "ASC2": "G0139", "VAN2": "G0285", "ALZ1": "G0092", "ALZ2": "G0093", "COF1": "G0160", "TRL1": "G0307"}
R = r"C:\Users\magnu\dev\solstorm_results\y24act"
da = pd.concat([pd.read_csv(f) for f in sorted(glob.glob(os.path.join(R, "2024-*", "da_dispatch.csv")))])
da = da[da.fuel == "Nuclear"]
rows = []
for ree, mdl in units.items():
    a = pv[pv.unit == ree].groupby(["date", "hour"]).mwh.sum().rename("PDVP")
    u = ph[(ph.unit == ree) & ph.Redespacho.str.startswith("UPO")].groupby(["date", "hour"]).mwh.sum().rename("ph1_up")
    m = da[da.gen_id == mdl].set_index(["date", "hour"]).dispatch_mw.rename("model_DA")
    j = pd.concat([a, u, m], axis=1).fillna(0).reset_index()
    j["PDBF"] = j.PDVP - j.ph1_up
    j["unit"] = ree; j["m"] = j.date.str[5:7]
    rows.append(j)
j = pd.concat(rows)
sp = j[j.m.isin(["03", "04", "05"])]
print("spring (Mar-May) mean MW per unit: REE before phase I (PDBF), after (PDVP), model DA")
print(sp.groupby("unit")[["PDBF", "PDVP", "model_DA"]].mean().round(0).to_string())
a = sp[sp.unit.isin(["ASC1", "ASC2"])].groupby("hour")[["PDBF", "PDVP", "model_DA"]].sum() / sp.date.nunique()
print("\nAscó 1+2, spring mean MW by hour:"); print(a.round(0).T.to_string())
print("\nAscó 1+2 by month, mean MW:")
print(j[j.unit.isin(["ASC1", "ASC2"])].groupby(["m", "date", "hour"])[["PDBF", "PDVP", "model_DA"]].sum().groupby("m").mean().round(0).T.to_string())
