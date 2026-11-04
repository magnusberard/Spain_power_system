"""E2: test the window rule chosen on 2024 (data/e2_window_2024.json) once on 2023, unchanged (fixed 4 Nov, before 2023
is seen). Marks as in every E2 test: >= 70 % of REE's need hours, hourly correlation >= 0.5, volume 0.5-2x.
Also printed for 2023: the single-hour rule, and the result by half-year.

    python redispatch_realism/e2_window_test_2023.py
"""
import json, sys
from pathlib import Path
import pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from e2_rule import shortfall, need_series, window_need, score

c = json.loads((HERE / "data" / "e2_window_2024.json").read_text(encoding="utf-8"))
idx = pd.date_range("2023-01-01", "2023-12-31 23:00", freq="h")
short, ok = shortfall(2023, idx)
need = need_series(2023, idx)
x = window_need(short, c["A"], c["B"], c["amount"])
print(f"rule chosen on 2024: A = {c['A']} h ahead, B = {c['B']} h back, amount = {c['amount']}; 2024: {c['score_2024']}")
print(f"hours used {int(ok.sum())}, REE need hours {int((need[ok] > 0).sum())}, mean need {need[ok].mean():.0f} MW")
print("single hour, 2023:", score(short, need, ok))
for name, m in (("Jan-Jun", ok & (idx < "2023-07-01")), ("Jul-Dec", ok & (idx >= "2023-07-01"))):
    print(f"window, 2023 {name}:", score(x, need, m))
res = score(x, need, ok)
print("window, 2023 full year:", res)
marks = {"need hours caught >= 70 %": res["recall"] >= 0.7, "hourly corr >= 0.5": res["corr"] >= 0.5,
         "volume 0.5-2x": 0.5 <= res["volume"] <= 2}
for k, v in marks.items():
    print(f"  {'PASS' if v else 'FAIL'}  {k}")
print("RESULT (2023, out of year):", "PASS" if all(marks.values()) else "FAIL")
