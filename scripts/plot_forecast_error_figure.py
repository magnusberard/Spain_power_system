"""Net-demand forecast errors by gate, 2024: data and SVG paths for the model-overview figure.

The model's volume at a stage is OMIE's day-ahead MW times the stage factor in Data/ES
(run_market_chain.jl load_scaled_col; profile scale 1 in 2024). Wind and solar use the
offered baseline of the main runs (Data/ES_old_offered); removing pumping shifts every
stage by the same MW and does not change the errors.

Net-demand error left at gate g, per hour:
    e_g = (L_BE - L_g) - (W_BE - W_g) - (S_BE - S_g)        [MW]
with BE the measured values that balancing clears. The figure shows g = DA (the
day-ahead forecast) and g = CID (one hour before delivery).

Usage (from the repo root):
    python scripts/plot_forecast_error_figure.py [--out results/figures]
Writes forecast_error_hist.csv (bin counts) and forecast_error_paths.svg (the two step
paths and axis labels, in the coordinates of the figure's histogram panel).
"""
import argparse
import csv
import glob
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTORS = os.path.join(ROOT, "Data", "ES")
SOURCES = {  # factor folder -> baseline MW file folder
    "load": os.path.join(ROOT, "Data", "ES_old", "load"),
    "Wind Onshore": os.path.join(ROOT, "Data", "ES_old_offered", "Wind"),
    "Solar": os.path.join(ROOT, "Data", "ES_old_offered", "Solar"),
}
SIGN = {"load": 1.0, "Wind Onshore": -1.0, "Solar": -1.0}
GATES = ["DA", "CID"]

# histogram panel of svg-fig2b (thesis_figures/thesis-figures.html)
X0, X1 = 69.0, 264.0      # plot width inside the panel frame
BASE, TOP = 512.0, 392.0  # baseline and the tallest bar (kept below the legend)
HALF_RANGE_GW = 8.0
BIN_GW = 0.25


def read_col(path, col):
    with open(path, newline="") as fh:
        return [float(r[col]) for r in csv.DictReader(fh)]


def errors():
    out = {g: [] for g in GATES}
    for fpath in sorted(glob.glob(os.path.join(FACTORS, "load", "*_2024.csv"))):
        name = os.path.basename(fpath)
        hourly = {g: [0.0] * 24 for g in GATES}
        for src, base_dir in SOURCES.items():
            base = read_col(os.path.join(base_dir, name), "-12")
            fac = os.path.join(FACTORS, src, name)
            be = read_col(fac, "BE")
            for g in GATES:
                fg = read_col(fac, g)
                for h in range(24):
                    hourly[g][h] += SIGN[src] * base[h] * (be[h] - fg[h])
        for g in GATES:
            out[g].extend(hourly[g])
    return out


def histogram(values):
    n = int(round(2 * HALF_RANGE_GW / BIN_GW))
    counts = [0] * n
    for v in values:
        i = int((v / 1000.0 + HALF_RANGE_GW) // BIN_GW)
        if 0 <= i < n:  # hours beyond the axis are left out (count printed below)
            counts[i] += 1
    return counts


def step_path(counts, peak):
    n = len(counts)
    w = (X1 - X0) / n
    y = lambda c: BASE - (BASE - TOP) * c / peak
    d = [f"M{X0:.1f} {BASE:.1f}"]
    for i, c in enumerate(counts):
        d.append(f"V{y(c):.1f}H{X0 + (i + 1) * w:.1f}")
    d.append(f"V{BASE:.1f}Z")
    return "".join(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "figures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    err = errors()
    hist = {g: histogram(err[g]) for g in GATES}
    peak = max(max(h) for h in hist.values())

    for g in GATES:
        v = sorted(err[g])
        p = lambda q: v[int(q * (len(v) - 1))] / 1000.0
        print(f"{g:4s} hours {len(v)}  mean {statistics.fmean(v) / 1000:+.2f} GW  "
              f"sd {statistics.pstdev(v) / 1000:.2f} GW  p5 {p(0.05):+.2f}  p95 {p(0.95):+.2f}  "
              f"outside +-{HALF_RANGE_GW:g} GW: {sum(abs(x) > HALF_RANGE_GW * 1000 for x in v)}")

    with open(os.path.join(args.out, "forecast_error_hist.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bin_low_gw", "bin_high_gw"] + [f"hours_{g}" for g in GATES])
        for i in range(len(hist["DA"])):
            lo = -HALF_RANGE_GW + i * BIN_GW
            w.writerow([f"{lo:.2f}", f"{lo + BIN_GW:.2f}"] + [hist[g][i] for g in GATES])

    mid = (X0 + X1) / 2
    svg = [
        f'<path d="{step_path(hist["DA"], peak)}" fill="#f2c4c8" stroke="#d62728" stroke-width="0.8"/>',
        f'<path d="{step_path(hist["CID"], peak)}" fill="#7fb2dd" fill-opacity="0.45" stroke="#1f77b4" stroke-width="0.8"/>',
        f'<line x1="{X0:.0f}" y1="{BASE:.0f}" x2="{X1:.0f}" y2="{BASE:.0f}" stroke="#555555" stroke-width="0.8"/>',
    ]
    for x, label in ((X0, f"−{HALF_RANGE_GW:g}"), (mid, "0"), (X1, f"+{HALF_RANGE_GW:g} GW")):
        anchor = "start" if x == X0 else ("end" if x == X1 else "middle")
        svg.append(f'<line x1="{x:.0f}" y1="{BASE:.0f}" x2="{x:.0f}" y2="{BASE + 4:.0f}" stroke="#555555" stroke-width="0.8"/>')
        svg.append(f'<text x="{x:.0f}" y="{BASE + 18:.0f}" font-size="13" text-anchor="{anchor}" fill="#333333">{label}</text>')
    with open(os.path.join(args.out, "forecast_error_paths.svg"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(svg) + "\n")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
