"""E2: choose the episode window on 2024 (training year), to be tested once on 2023 (fixed 4 Nov, before 2023 is seen).

Single-hour shortfall as in e2_test_ccgt_pumped.py (mFRR + aFRR + P.O. 1.5 §4.4 gaps against PHFC − CCGT/coal and
pumped-storage headroom). Window: an hour needs reserve if the shortfall is positive in [t − B, t + A] (A hours
ahead: REE starts the period before the shortfall; B hours back: REE keeps it after). Amount in a flagged hour:
"own" = the hour's own shortfall where positive, else the window's mean positive shortfall; "max" = window max.
Grid: A in 0..4, B in 0..4, amount in {own, max}. Choice on all of 2024: among the variants that pass the three
marks (>= 70 % of REE's need hours, hourly corr >= 0.5, volume 0.5-2x), the highest hourly correlation; if none
passes, the highest number of marks passed, then the highest correlation. The chosen (A, B, amount) is written to
data/e2_window_2024.json and is then tested on 2023 without change (e2_window_test_2023.py).

    python redispatch_realism/e2_window_select_2024.py
"""
import json, os, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import shortfall, need_series, window_need, score

YEAR = 2024
idx = pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31 23:00", freq="h")
short, ok = shortfall(YEAR, idx)
need = need_series(YEAR, idx)
rows = []
for A in range(5):
    for B in range(5):
        for amount in ("own", "max"):
            x = window_need(short, A, B, amount)
            sc = score(x, need, ok)
            marks = (sc["recall"] >= 0.7) + (sc["corr"] >= 0.5) + (0.5 <= sc["volume"] <= 2)
            rows.append(dict(A=A, B=B, amount=amount, marks=int(marks), **sc))
g = pd.DataFrame(rows).sort_values(["marks", "corr"], ascending=False)
print(g.head(12).to_string(index=False))
best = g.iloc[0]
choice = dict(A=int(best.A), B=int(best.B), amount=str(best.amount), chosen_on="all of 2024",
              score_2024={k: float(best[k]) for k in ("corr", "corr_day", "recall", "precision", "volume")},
              marks_2024=int(best.marks))
(HERE / "data" / "e2_window_2024.json").write_text(json.dumps(choice, indent=2), encoding="utf-8")
print("\nchosen on 2024:", choice)
