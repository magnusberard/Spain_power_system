"""E2: does P.O. 1.5 §4.4 (forecast vs scheduled programme) plus the tertiary/secondary requirement and thermal
headroom explain REE's real-time additional reserve need (e·sios 1880), 2024?  Hourly, local time."""
import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
idx = pd.date_range("2024-01-01", "2024-12-31 23:00", freq="h")

def esios(path, ind, how="mean"):
    f = pd.read_csv(path); f = f[f.indicator == ind].copy()
    f["t"] = pd.to_datetime(f.datetime_utc).dt.tz_convert("Europe/Madrid").dt.tz_localize(None)
    s = f.set_index("t").value
    s = s[~s.index.duplicated()]
    return s.resample("h").mean().reindex(idx)

FC = r"C:\Users\magnu\dev\esios_download\forecasts\esios_forecasts_2024.csv.gz"
RS = r"C:\Users\magnu\dev\esios_download\forecasts\reserve\esios_reserve_2024.csv.gz"
need = esios(RS, 1880).fillna(0)                       # REE's identified real-time need (MW), 0 = none published
tert = esios(FC, 1788).ffill()                          # mFRR upward requirement
sec = esios(RS, 632).ffill()                            # secondary band assigned upward
dem_h3, wind_h3, pv_h3 = esios(FC, 1776), esios(FC, 1778), esios(FC, 1780)
dem_d1, wind_d1, pv_d1 = esios(FC, 1775), esios(FC, 1777), esios(FC, 1779)
st_fc = esios(FC, 543).fillna(0)                        # solar thermal forecast
dem_act, wind_act, pv_act = esios(FC, 1293), esios(FC, 551), esios(FC, 1295)

# scheduled programme: OMIE day-ahead per technology (local hours 0-23, 24 per day)
r = pd.read_csv(r"C:\Users\magnu\dev\spain-model-runs\reference\real_hourly_2024.csv.gz")
r.index = pd.to_datetime(r.date) + pd.to_timedelta(r.hour, unit="h")
r = r.reindex(idx)
omie_gen = r[[c for c in r.columns if c.startswith("omie_")]].sum(axis=1)

# pumping in the programme (I90 PDVP) and thermal headroom of running CCGT + coal
p = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_pdvp.csv.gz", encoding="utf-8", encoding_errors="replace")
p.columns = ["date", "unit", "tof", "hour", "mwh", "a", "b"]
p = p.groupby(["date", "unit", "hour"], as_index=False).mwh.sum()
t = pd.read_csv(r"C:\Users\magnu\dev\Spain_power_system\.claude\worktrees\redispatch-realism\redispatch_realism\data\ree_unit_technology.csv")
t["ree_max_mw"] = pd.to_numeric(t.ree_max_mw.astype(str).str.replace(",", "."), errors="coerce")
print("CCGT/coal units without max MW:", t[t.group.isin(["CCGT", "coal"]) & t.ree_max_mw.isna()].ree_unit.tolist())
p = p.merge(t[["ree_unit", "group", "ree_max_mw"]], left_on=p.unit.str.strip(), right_on="ree_unit", how="left")
p["t"] = pd.to_datetime(p.date) + pd.to_timedelta(p.hour, unit="h")
pump = p[p.group == "pumped storage (pump)"].groupby("t").mwh.sum().reindex(idx).fillna(0)       # negative
th = p[p.group.isin(["CCGT", "coal"]) & (p.mwh > 1)].copy()
th["head"] = (th.ree_max_mw - th.mwh).clip(lower=0)
head_th = th.groupby("t")["head"].sum().reindex(idx).fillna(0)
n_on = th.groupby("t").unit.nunique().reindex(idx).fillna(0)
big = p[p.mwh > 1].groupby("t").mwh.max().reindex(idx).ffill()    # largest scheduled unit (MW)

# §4.4 components (MW, upward = deficits of generation vs demand)
dem_sched = omie_gen + pump                              # programmed generation incl. imports, minus pumping ≈ programmed demand + exports
c = pd.DataFrame(index=idx)
for tag, d, w, s in (("H3", dem_h3, wind_h3, pv_h3), ("D1", dem_d1, wind_d1, pv_d1)):
    c[f"dem_{tag}"] = d - (dem_sched - (dem_sched - dem_h3).rolling(24 * 28, center=True, min_periods=24).median())   # level offset (exports) removed
    c[f"wind_{tag}"] = r.omie_Wind - w
    c[f"solar_{tag}"] = r.omie_Solar - (s + st_fc)
    c[f"supp_{tag}"] = c[[f"dem_{tag}", f"wind_{tag}", f"solar_{tag}"]].clip(lower=0).sum(axis=1)
c["req_H3"] = tert + sec + c.supp_H3
c["short_H3"] = (c.req_H3 - head_th).clip(lower=0)
c["req_D1"] = tert + sec + c.supp_D1
c["short_D1"] = (c.req_D1 - head_th).clip(lower=0)
c["headroom"] = -head_th
c["n_thermal_on"] = -n_on
c["actual_wind_short"] = (r.omie_Wind - wind_act).clip(lower=0)
c["actual_solar_short"] = (r.omie_Solar - pv_act).clip(lower=0)

ok = need.notna() & c.notna().all(axis=1)
hit = need > 0
print(f"hours used {int(ok.sum())}; need published in {int(hit[ok].sum())}")
print("\nsignal vs REE's need (1880): correlation hourly/daily, and how often the signal is higher in need hours")
rows = []
for k in c.columns:
    x, y = c.loc[ok, k], need[ok]
    d = pd.DataFrame({"x": x, "y": y}).resample("D").mean()
    auc = (x[hit[ok]].values[:, None] > x[~hit[ok]].sample(2000, random_state=1).values[None, :]).mean()
    rows.append((k, x.corr(y), d.x.corr(d.y), auc, x[hit[ok]].mean(), x[~hit[ok]].mean()))
print(pd.DataFrame(rows, columns=["signal", "corr h", "corr day", "P(higher when need)", "mean need h", "mean other h"]).set_index("signal").round(2).to_string())

# the rule as a yes/no: shortfall > 0 vs need published
for k in ("short_H3", "short_D1"):
    s = c.loc[ok, k] > 0; h = hit[ok]
    print(f"{k}: rule says short in {int(s.sum())} h; REE need in {int(h.sum())} h; both {int((s & h).sum())}; "
          f"recall {(s & h).sum() / h.sum():.2f}, precision {(s & h).sum() / max(1, s.sum()):.2f}; "
          f"volume rule/REE {c.loc[ok, k].sum() / need[ok].sum():.2f}")
print("\nmean MW: tertiary", round(tert.mean()), "| secondary", round(sec.mean()), "| supp H3", round(c.supp_H3.mean()),
      "| headroom running CCGT+coal", round(head_th.mean()), "| largest unit", round(big.mean()))
print("supp_H3 parts (mean of positive part):", {k: round(c[f"{k}_H3"].clip(lower=0).mean()) for k in ("dem", "wind", "solar")})
m = pd.DataFrame({"need": need, "supp_H3": c.supp_H3, "short_H3": c.short_H3, "headroom": head_th}).resample("MS").mean().round(0)
print(m.to_string())
