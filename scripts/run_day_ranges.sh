#!/usr/bin/env bash
# Run the 2024 market chain for several day ranges, one after another. Each range
# gets its own Julia process and results folder, <out>/<from>_<to>/, with its own
# run.log. A range whose summary.csv already exists is skipped, so after an
# interruption just start it again.
#
# Usage (from anywhere; normally started by solstorm_start_weeks.sh):
#     scripts/run_day_ranges.sh <out> 2024-07-01:2024-07-07 2024-07-08:2024-07-14 ...
#
# Uses config.toml (or $SPAIN_CONFIG if set) and the current environment
# (IPOPT_LINEAR_SOLVER etc.). Join the folders afterwards with merge_runs.py.
set -u

OUT="$1"; shift
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

done_ranges=()
failed_ranges=()
for range in "$@"; do
    from="${range%%:*}"; to="${range##*:}"
    dir="$OUT/${from}_${to}"
    if [ -f "$dir/summary.csv" ]; then
        echo "[$from..$to] already done ($dir), skipping"
        continue
    fi
    mkdir -p "$dir"
    t0=$(date +%s)
    echo "[$from..$to] $(date +%H:%M)  running ..."
    ( cd "$REPO" && SPAIN_DAYS="$from:$to" SPAIN_RESULTS="$dir" \
          julia --project=. run_market_chain.jl ) 2>&1 | tee "$dir/run.log"
    code=${PIPESTATUS[0]}
    mins=$(( ($(date +%s) - t0 + 30) / 60 ))
    if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
        echo "[$from..$to] finished in $mins min"
        done_ranges+=("$from..$to")
    else
        echo "[$from..$to] FAILED (exit code $code) after $mins min - see $dir/run.log"
        failed_ranges+=("$from..$to")
    fi
done

echo ""
echo "Done this run: ${done_ranges[*]:-none}"
[ ${#failed_ranges[@]} -gt 0 ] && echo "Failed: ${failed_ranges[*]}"
exit 0
