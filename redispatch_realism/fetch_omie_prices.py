"""Download OMIE's hourly day-ahead marginal prices (Spain) for a date range from OMIE's public daily files.

    python redispatch_realism/fetch_omie_prices.py 2023-01-01 2023-12-31

Writes <ESIOS_DIR or ../esios_download>/omie_prices_<year>.csv: date, hour (0-23; period - 1), price (Spain, EUR/MWh).
OMIE file: marginalpdbc_YYYYMMDD.1, rows "YYYY;MM;DD;period;price PT;price ES;". No token.
"""
import os, sys, time, datetime as dt, urllib.request, urllib.error
from pathlib import Path
import pandas as pd
URL = "https://www.omie.es/es/file-download?parents%5B0%5D=marginalpdbc&filename=marginalpdbc_{d}.1"
REPO = Path(__file__).resolve().parents[1]
if ".claude" in REPO.parts:
    REPO = Path(*REPO.parts[:REPO.parts.index(".claude")])
OUT = Path(os.environ.get("ESIOS_DIR") or REPO.parent / "esios_download")

def main(a, b):
    rows, d = [], dt.date.fromisoformat(a)
    while d <= dt.date.fromisoformat(b):
        txt = ""
        for ver in (1, 2, 3):                              # OMIE re-publishes corrected days as .2, .3
            try:
                txt = urllib.request.urlopen(URL.format(d=d.strftime("%Y%m%d"))[:-1] + str(ver), timeout=60).read().decode("latin-1")
                break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    time.sleep(5)
            except Exception:
                time.sleep(5)
        if not txt:
            print(f"  {d}: no file found (.1-.3)")
        for line in txt.splitlines():
            p = line.strip().strip(";").split(";")
            if len(p) >= 6 and p[0].isdigit():
                rows.append((d.isoformat(), int(p[3]) - 1, float(p[5])))
        d += dt.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["date", "hour", "price"])
    f = OUT / f"omie_prices_{a[:4]}.csv"
    df.to_csv(f, index=False)
    print(f"wrote {f}: {len(df)} rows, {df.date.nunique()} days, mean {df.price.mean():.1f} EUR/MWh")

if __name__ == "__main__":
    main(*sys.argv[1:3])
