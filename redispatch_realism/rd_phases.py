"""The model's redispatch split by phase, for the results website's "Redispatch vs REE" tab (6 Nov 2026).

REE reports phase I/II (technical constraints on the day-ahead schedule) and real time apart, each as an extra
cost over the market (P.O. 14.4). The website's package so far pooled the model's two phases and valued them at
marginal cost. This builds, per hour:
  ph1  phase I/II: rd_phase1_summary.csv (up_mwh, down_mwh, extra_cost_eur: the model's own objective, start-ups
       included), solved hours only
  rt   real time: settle.py's extra cost with the run's own bids, refund rule and storage rule (P.O. 14.4: up at the
       bid, down refunded, against the day-ahead price; start-ups added), solved AC hours only
Used by scripts/publish_run.py (package key redispatch.phases) and by add_rd_phases.py (adds it to a published
package without republishing it).
"""
import sys
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import settle                                                     # noqa: E402


def run_bid_rules(rdir):
    """The run's own pricing ([redispatch.bids] and objective in config_used.toml) for settle.py."""
    f = Path(rdir) / "config_used.toml"
    c = tomllib.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    rd = c.get("redispatch", {})
    b = rd.get("bids", {})
    markups = {}
    for row in b.get("by_type", []):
        k = tuple(str(row["type"]).split(":", 1))
        if len(k) == 2:
            markups[k] = (float(row.get("up_markup", 0.0)), float(row.get("down_markup", 0.0)))
    return dict(bids=markups, down_refund=str(b.get("down_refund", "da")).lower(),
                storage_at_da=str(rd.get("objective", "")).lower() == "ree")


def phase_frames(rdir):
    """(ph1, rt): per-hour frames date, hour, up, down, cost for one run folder; None where a part is missing."""
    rdir = Path(rdir)
    ph1 = rt = None
    f = rdir / "rd_phase1_summary.csv"
    if f.exists():
        p = pd.read_csv(f)
        if "status" in p:
            p = p[p.status.astype(str).str.contains("SOLVED")]
        ph1 = pd.DataFrame({"date": p.date, "hour": p.hour, "up": p.up_mwh, "down": p.down_mwh, "cost": p.extra_cost_eur})
    if (rdir / "summary.csv").exists() and (rdir / "gen_dispatch.csv").exists():
        h, *_ = settle.settle(rdir, **run_bid_rules(rdir))
        rt = pd.DataFrame({"date": h.date, "hour": h.hour, "up": h.up_mwh, "down": h.down_mwh, "cost": h.extra_cost_eur})
    return ph1, rt


def phase_series(ph1, rt, hours):
    """{'ph1': {up, down, cost}, 'rt': {...}} as lists over hours.H (None where not solved); hours: publish_run.Hours."""
    out = {}
    for name, fr in (("ph1", ph1), ("rt", rt)):
        if fr is None or fr.empty:
            continue
        fr = fr[fr.date.isin(hours.day_i)]
        idx = hours.of(fr)
        block = {}
        for col in ("up", "down", "cost"):
            a = np.full(hours.H, np.nan)
            a[idx] = fr[col].to_numpy(dtype=float)
            block[col] = [None if not np.isfinite(v) else round(float(v), 1) for v in a]
        out[name] = block
    return out
