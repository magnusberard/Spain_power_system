"""Download ENTSO-E actual (realized) physical cross-border flows for Spain,
to test whether they explain the "International Import (without MIBEL)" term
missing from a pure day-ahead OMIE per-unit reconstruction of Spanish load.

Usage (token is read from the environment, never from a file):
    export ENTSOE_TOKEN='...'
    python3 fetch_crossborder_flows.py 2024-07-08

Prints, for each hour, the net actual physical import into Spain from France
and from Portugal (import direction minus export direction), plus the total,
so it can be compared by hand against the ~2400 MW gap found in the OMIE
per-unit reconstruction of load.
"""
import os
import sys

# Reuse the existing helpers rather than duplicating the ENTSO-E plumbing.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_entsoe import call, parse, utc_window, local_day_bounds, to_24  # noqa: E402

ES = "10YES-REE------0"
FR = "10YFR-RTE------C"
PT = "10YPT-REN------W"
TZ = "Europe/Madrid"


def net_flow(day, token, other_zone, other_name):
    """Actual physical flow (documentType A11), net into Spain, for one border."""
    a, b = utc_window(day)
    into_es = call(dict(documentType="A11", in_Domain=ES, out_Domain=other_zone,
                         periodStart=a, periodEnd=b),
                    token, f"flow_into_ES_from_{other_name}_{day}")
    out_es = call(dict(documentType="A11", in_Domain=other_zone, out_Domain=ES,
                        periodStart=a, periodEnd=b),
                   token, f"flow_from_ES_to_{other_name}_{day}")
    s_in = parse(into_es)
    try:
        s_out = parse(out_es)
    except ValueError:
        s_out = s_in * 0  # no export series at all this day
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

    fr = to_24(net_flow(day, token, FR, "FR"))
    pt = to_24(net_flow(day, token, PT, "PT"))

    print(f"{'hour':>4} {'net FR->ES':>11} {'net PT->ES':>11} {'total':>9}")
    for h in range(24):
        total = fr[h] + pt[h]
        print(f"{h:4d} {fr[h]:11.1f} {pt[h]:11.1f} {total:9.1f}")


if __name__ == "__main__":
    main()
