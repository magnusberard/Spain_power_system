"""Download REE's demand, wind and solar forecasts and the matching actuals from the e·sios API.

Step E2 (real-time reserve from forecast errors, P.O. 1.5 §4.4): REE checks the schedules against
its own forecasts and buys upward reserve in real time when they fall short. This keeps, for the
Spanish peninsula, one row per indicator and time step (15 min or hour, as published):

  forecasts   460 demand D+1 · 544 demand forecast (updated) · 1775/1776 demand D+1 / H+3
              541 wind · 1777/1778 wind D+1 / H+3 · 542 PV · 1779/1780 PV D+1 / H+3
              543 solar thermal · 10249 residual demand
  actuals     1293 demand · 551 wind · 1295 PV · 1294 solar thermal
  reserve     626/627/628 additional upward reserve (P.O. 3.9): requirement, assigned, price
              672 tertiary need up · 1788 mFRR upward reserve requirement

Columns: indicator, name, datetime_utc, value (MW), geo_id, geo_name. Peninsular rows only where an
indicator has several geographies. Every month is first written to <out>/months/ (so an
interrupted download resumes), then everything is combined into <out>/esios_forecasts_<year>.csv.gz.

    python redispatch_realism/fetch_esios_forecasts.py 2024-01-01 2024-12-31

The API needs a personal token (https://www.esios.ree.es/es/token), read from $ESIOS_TOKEN or the
file ~/.esios_token; it is never printed or written out. Default <out>: $ESIOS_DIR/forecasts, else
esios_download/forecasts next to the repo (as fetch_i90.py).
"""
import argparse
import datetime as dt
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

INDICATORS = {
    460: "forecast", 544: "forecast", 1775: "forecast", 1776: "forecast",
    541: "forecast", 1777: "forecast", 1778: "forecast",
    542: "forecast", 1779: "forecast", 1780: "forecast",
    543: "forecast", 10249: "forecast",
    1293: "actual", 551: "actual", 1295: "actual", 1294: "actual",
    626: "reserve", 627: "reserve", 628: "reserve", 672: "reserve", 1788: "reserve",
}
PENINSULA = (8741, "Península")       # e·sios geo id of the peninsular system
API = "https://api.esios.ree.es/indicators/{}"


def token():
    t = os.environ.get("ESIOS_TOKEN")
    if not t:
        p = Path.home() / ".esios_token"
        if not p.exists():
            raise SystemExit("no e·sios token: set ESIOS_TOKEN or save it in ~/.esios_token")
        t = p.read_text(encoding="utf-8-sig")
    return t.strip()


def fetch(ind, start, end, tok, tries=4):
    q = urllib.parse.urlencode({"start_date": start.strftime("%Y-%m-%dT00:00"),
                                "end_date": end.strftime("%Y-%m-%dT23:59")})
    req = urllib.request.Request(API.format(ind) + "?" + q, headers={
        "Accept": "application/json; application/vnd.esios-api-v1+json", "x-api-key": tok})
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["indicator"]
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                raise SystemExit(f"e·sios refused the token (HTTP {e.code})")
            if k == tries - 1:
                raise
            time.sleep(5 * (k + 1))


def month_rows(ind, start, end, tok):
    d = fetch(ind, start, end, tok)
    v = pd.DataFrame(d.get("values", []))
    if v.empty:
        return v
    if "geo_id" in v and v.geo_id.nunique() > 1:
        v = v[v.geo_id == PENINSULA[0]]
    return pd.DataFrame({"indicator": ind, "name": d["name"], "datetime_utc": v["datetime_utc"],
                         "value": v["value"], "geo_id": v.get("geo_id"), "geo_name": v.get("geo_name")})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("start"); ap.add_argument("end")
    here = Path(__file__).resolve().parents[1]
    dflt = Path(os.environ["ESIOS_DIR"]) / "forecasts" if "ESIOS_DIR" in os.environ else here.parent / "esios_download" / "forecasts"
    ap.add_argument("--out", type=Path, default=dflt)
    a = ap.parse_args()
    start, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    (a.out / "months").mkdir(parents=True, exist_ok=True)
    tok = token()
    m = start.replace(day=1)
    parts = []
    while m <= end:
        nxt = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        s, e = max(m, start), min(nxt - dt.timedelta(days=1), end)
        f = a.out / "months" / f"{s:%Y-%m}.csv.gz"
        if not f.exists():
            rows = []
            for ind in INDICATORS:
                rows.append(month_rows(ind, s, e, tok))
                time.sleep(0.3)
            df = pd.concat([r for r in rows if not r.empty], ignore_index=True)
            df.to_csv(f, index=False)
            print(f"{s:%Y-%m}: {len(df):,} rows, {df.indicator.nunique()} of {len(INDICATORS)} indicators")
        else:
            print(f"{s:%Y-%m}: done already")
        parts.append(pd.read_csv(f))
        m = nxt
    allr = pd.concat(parts, ignore_index=True)
    out = a.out / f"esios_forecasts_{start:%Y}.csv.gz"
    allr.to_csv(out, index=False)
    print(f"\nwrote {out}: {len(allr):,} rows")
    print(allr.groupby(["indicator", "name"]).agg(rows=("value", "size"), first=("datetime_utc", "min"),
                                                  last=("datetime_utc", "max")).to_string())


if __name__ == "__main__":
    main()
