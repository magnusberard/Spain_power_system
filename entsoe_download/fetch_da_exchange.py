"""Download ENTSO-E DAY-AHEAD scheduled commercial exchange for Spain
(documentType A09, "Scheduled Commercial Exchanges", filtered to day-ahead
contracts) — the correct like-for-like comparison against OMIE's day-ahead
"International Import (without MIBEL)" figure, unlike actual physical flows
(A11) which are always real-time metered and were the wrong comparison.

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_da_exchange.py 2024-07-08
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import call, parse, utc_window, local_day_bounds, to_24  # noqa: E402

ES = "10YES-REE------0"
FR = "10YFR-RTE------C"
PT = "10YPT-REN------W"
TZ = "Europe/Madrid"
DA_CONTRACT = "A01"  # contract_MarketAgreement.Type: day-ahead


def net_da_flow(day, token, other_zone, other_name):
    a, b = utc_window(day)
    into_es = call(dict(documentType="A09", **{"contract_MarketAgreement.Type": DA_CONTRACT},
                         in_Domain=ES, out_Domain=other_zone, periodStart=a, periodEnd=b),
                    token, f"da_into_ES_from_{other_name}_{day}")
    out_es = call(dict(documentType="A09", **{"contract_MarketAgreement.Type": DA_CONTRACT},
                        in_Domain=other_zone, out_Domain=ES, periodStart=a, periodEnd=b),
                   token, f"da_from_ES_to_{other_name}_{day}")
    s_in = parse(into_es)
    try:
        s_out = parse(out_es)
    except ValueError:
        s_out = s_in * 0
    net = s_in.sub(s_out, fill_value=0.0)
    net.index = net.index.tz_convert(TZ) if net.index.tz else net.index.tz_localize("UTC").tz_convert(TZ)
    hourly = net.resample("h").mean()
    lo, hi = local_day_bounds(day)
    return hourly[(hourly.index >= lo) & (hourly.index < hi)]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    day = sys.argv[1]
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        sys.exit("Set ENTSOE_TOKEN first: export ENTSOE_TOKEN='...'")

    fr = to_24(net_da_flow(day, token, FR, "FR"))
    pt = to_24(net_da_flow(day, token, PT, "PT"))

    print(f"{'hour':>4} {'DA net FR->ES':>14} {'DA net PT->ES':>14} {'total':>9}")
    for h in range(24):
        total = fr[h] + pt[h]
        print(f"{h:4d} {fr[h]:14.1f} {pt[h]:14.1f} {total:9.1f}")


if __name__ == "__main__":
    main()
