"""Phase I up: model (y24act, y24part) vs REE (e·sios rt1_up), 2024, for the comparison page."""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
t = Path(r"C:\Users\magnu\dev\spain-model-runs\reference\esios_2024.js").read_text(encoding="utf-8")
e = json.loads(t[t.index("=") + 1:].rstrip().rstrip(";"))
idx = pd.date_range("2024-01-01", periods=8784, freq="h")
S = lambda k: pd.Series([np.nan if v is None else v for v in e["series"][k]], index=idx)
ree = S("rt1_up")
# REE's phase I up on nuclear units (I90DIA03, UPO*), hourly, to show REE without the nuclear raise the model cannot do
_ph = pd.read_csv(r"C:\Users\magnu\dev\esios_download\i90\i90_tc_phase.csv.gz", encoding="utf-8", encoding_errors="replace")
_ph = _ph.rename(columns={_ph.columns[3]: "unit"})
_tech = pd.read_csv(Path(__file__).resolve().parent.parent / "data" / "ree_unit_technology.csv").set_index("ree_unit").group
_nu = _ph[_ph.Redespacho.str.startswith("UPO") & (_ph.Sentido == "Subir") & (_ph.unit.str.strip().map(_tech) == "nuclear")]
nuc = _nu.groupby(pd.to_datetime(_nu.date) + pd.to_timedelta(_nu.hour, unit="h")).mwh.sum().reindex(idx).fillna(0)
ree_nn = (ree - nuc).clip(lower=0)
causes = {"Voltage (CT)": S("rt1_up_ct"), "N-1 (SCA)": S("rt1_up_sca"), "Distribution (RTD)": S("rt1_up_rtd"),
          "Other": S("rt1_up_scb") + S("rt1_up_rsi") + S("rt1_up_otros")}
print("REE cause series:", list(causes), "sum of causes / total:", round(sum(c.sum() for c in causes.values()) / ree.sum(), 3))

def model(run):
    R = Path(r"C:\Users\magnu\dev\solstorm_results") / run
    ps = pd.concat([pd.read_csv(p, usecols=["date", "hour", "up_mwh", "status"]) for p in sorted(R.glob("2024-*/rd_phase1_summary.csv"))])
    return pd.Series(ps.up_mwh.values, index=pd.to_datetime(ps.date) + pd.to_timedelta(ps.hour, unit="h"))

act, part = model("y24act"), model("y24part")
j = pd.concat([act, part, ree, ree_nn], axis=1, keys=["act", "part", "ree", "reenn"]).dropna()
print("hours", len(j), "totals GWh", (j.sum() / 1e3).round(0).to_dict())
d = j.resample("D").sum() / 1e3
w = j.resample("W-SUN").sum()
m = j.resample("MS").sum() / 1e3
hod = j.groupby(j.index.hour).mean()

def corr(a, b): return round(float(np.corrcoef(a, b)[0, 1]), 2)
stats = {
    "hourly": corr(j.act, j.ree), "daily": corr(d.act, d.ree), "weekly": corr(w.act, w.ree), "monthly": corr(m.act, m.ree),
    "hod": corr(hod.act, hod.ree), "volume": round(100 * j.act.sum() / j.ree.sum()),
    "monthly_err": round(100 * (m.act - m.ree).abs().sum() / m.ree.sum()),
    "model_twh": round(j.act.sum() / 1e6, 2), "ree_twh": round(j.ree.sum() / 1e6, 2),
    "part_twh": round(j.part.sum() / 1e6, 2), "part_daily": corr(d.part, d.ree),
}
stats_nn = {
    "hourly": corr(j.act, j.reenn), "daily": corr(d.act, d.reenn), "weekly": corr(w.act, w.reenn), "monthly": corr(m.act, m.reenn),
    "hod": corr(hod.act, hod.reenn), "volume": round(100 * j.act.sum() / j.reenn.sum()),
    "monthly_err": round(100 * (m.act - m.reenn).abs().sum() / m.reenn.sum()),
    "model_twh": round(j.act.sum() / 1e6, 2), "ree_twh": round(j.reenn.sum() / 1e6, 2), "nuclear_twh": round(nuc.sum() / 1e6, 2),
}
# REE monthly by cause (GWh): CT = N-1/technical, SCA/SCB voltage (a/b), RTD distribution — names as e·sios codes
mc = pd.DataFrame({k: v for k, v in causes.items()}).loc[j.index].resample("MS").sum() / 1e3
out = dict(
    days=[x.strftime("%Y-%m-%d") for x in d.index], d_act=d.act.round(2).tolist(), d_ree=d.ree.round(2).tolist(),
    months=[x.strftime("%b") for x in m.index], m_act=m.act.round(0).tolist(), m_ree=m.ree.round(0).tolist(),
    m_part=m.part.round(0).tolist(),
    m_cause={k: (100 * mc[k] / mc.sum(axis=1)).round(0).tolist() for k in mc.columns},
    y_cause={k: round(100 * mc[k].sum() / mc.values.sum()) for k in mc.columns},
    hod_act=hod.act.round(0).tolist(), hod_ree=hod.ree.round(0).tolist(), stats=stats,
    d_ree_nn=d.reenn.round(2).tolist(), m_ree_nn=m.reenn.round(0).tolist(), hod_ree_nn=hod.reenn.round(0).tolist(),
    m_nuc=(m.ree - m.reenn).round(0).tolist(), stats_nn=stats_nn)
Path(r"C:\Users\magnu\.claude\jobs\c3ee760a\tmp\ph1_data.json").write_text(json.dumps(out), encoding="utf-8")
print(stats)
print("without nuclear:", stats_nn)
print(pd.DataFrame({"model": m.act, "REE": m.ree, "%": 100 * m.act / m.ree}, index=m.index.strftime("%b")).round(0).T.to_string())
print(mc.round(0).T.to_string())
