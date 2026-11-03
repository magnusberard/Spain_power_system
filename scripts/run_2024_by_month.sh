#!/usr/bin/env bash
# Run the 2024 market chain one calendar month at a time (Linux/macOS twin of
# run_2024_by_month.ps1).
#
# Each month is a separate Julia process (memory is released in between) with
# its own results folder, <out>/<yyyy-mm>/, and its own log (run.log there). A
# month whose summary.csv already exists is skipped, so after an interruption
# just start the script again; --force re-runs them.
#
# Usage (from the repo root):
#     scripts/run_2024_by_month.sh                              # 2024-01-01 .. 2024-12-31
#     scripts/run_2024_by_month.sh 2024-04-01 2024-06-30        # April .. June
#     scripts/run_2024_by_month.sh 2024-04-01 2024-06-30 --force
#
# Uses config.toml as it stands (or $SPAIN_CONFIG if set), except for the study
# days (SPAIN_DAYS) and the results folder (SPAIN_RESULTS), which this script
# sets per month. OUT_ROOT sets the parent folder of the month folders
# (default results/2024_by_month in the repo).
set -u

FROM="${1:-2024-01-01}"
TO="${2:-2024-12-31}"
FORCE=0
[ "${3:-}" = "--force" ] && FORCE=1

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT_ROOT="${OUT_ROOT:-$REPO/results/2024_by_month}"
mkdir -p "$OUT_ROOT"

echo "Months         : $FROM .. $TO -> $OUT_ROOT"
echo "Config         : ${SPAIN_CONFIG:-$REPO/config.toml}"
echo "Linear solver  : ${IPOPT_LINEAR_SOLVER:-ma57}"

done_months=()
failed_months=()
month_start="$FROM"
while [ "$(date -d "$month_start" +%s)" -le "$(date -d "$TO" +%s)" ]; do
    month_end="$(date -d "$(date -d "$month_start" +%Y-%m-01) +1 month -1 day" +%Y-%m-%d)"
    [ "$(date -d "$month_end" +%s)" -gt "$(date -d "$TO" +%s)" ] && month_end="$TO"
    tag="$(date -d "$month_start" +%Y-%m)"
    dir="$OUT_ROOT/$tag"

    if [ -f "$dir/summary.csv" ] && [ "$FORCE" -eq 0 ]; then
        echo "[$tag] already done ($dir), skipping"
    else
        mkdir -p "$dir"
        t0=$(date +%s)
        echo "[$tag] $(date +%H:%M)  running $month_start:$month_end ..."
        ( cd "$REPO" && SPAIN_DAYS="$month_start:$month_end" SPAIN_RESULTS="$dir" \
              julia --project=. run_market_chain.jl ) 2>&1 | tee "$dir/run.log"
        code=${PIPESTATUS[0]}
        mins=$(( ($(date +%s) - t0 + 30) / 60 ))
        if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
            echo "[$tag] finished in $mins min"
            done_months+=("$tag")
        else
            echo "[$tag] FAILED (exit code $code) after $mins min - see $dir/run.log"
            failed_months+=("$tag")
        fi
    fi
    month_start="$(date -d "$month_end +1 day" +%Y-%m-%d)"
done

echo ""
echo "Done this run: ${done_months[*]:-none}"
[ ${#failed_months[@]} -gt 0 ] && echo "Failed: ${failed_months[*]}"
exit 0
