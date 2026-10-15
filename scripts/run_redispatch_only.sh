#!/usr/bin/env bash
# Step 2 of a split run: the network redispatch of chunks whose market stages
# are done (scripts/run_markets_sequential.sh). Each chunk runs on its own with
# [redispatch] from_saved = "BAL" (it reads the chunk's bal_dispatch.csv) and
# writes the redispatch outputs into the SAME folder, so the chunk then holds
# market and network results and merge_runs.py can join the chunks. The
# redispatch of one hour does not depend on another, so chunks can run in any
# order and in parallel.
#
#     scripts/run_redispatch_only.sh <out> <chunk> [<chunk> ...]
#
#   <out>     the parent folder of step 1 (holds config_redispatch.toml)
#   <chunk>   chunk folder names, e.g. 2024-01-01_2024-01-07
#
# A chunk whose markets are not finished yet is waited for (checked every
# minute), so this can start while step 1 is still running. A chunk that already
# has summary.csv is skipped. Log per chunk: run.log.
set -u

[ $# -ge 2 ] || { sed -n '2,19p' "$0"; exit 1; }
OUT="$1"; shift
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$OUT/config_redispatch.toml"
[ -f "$CFG" ] || { echo "$CFG not found - run scripts/run_markets_sequential.sh first"; exit 1; }

done_c=(); failed_c=()
for c in "$@"; do
    dir="$OUT/$c"
    from="${c%%_*}"; to="${c##*_}"
    if [ -f "$dir/summary.csv" ]; then
        echo "[$c] redispatch already done, skipping"; continue
    fi
    until [ -f "$dir/market_done" ]; do sleep 60; done
    t0=$(date +%s)
    echo "[$c] $(date +%H:%M)  redispatch ..."
    ( cd "$REPO" && SPAIN_DAYS="$from:$to" SPAIN_RESULTS="$dir" SPAIN_CONFIG="$CFG" \
          julia --project=. run_market_chain.jl ) > "$dir/run.log" 2>&1
    code=$?
    mins=$(( ($(date +%s) - t0 + 30) / 60 ))
    if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
        echo "[$c] redispatch finished in $mins min"; done_c+=("$c")
    else
        echo "[$c] redispatch FAILED (exit code $code) after $mins min - see $dir/run.log"; failed_c+=("$c")
    fi
done
echo ""
echo "Done this run: ${done_c[*]:-none}"
[ ${#failed_c[@]} -gt 0 ] && echo "Failed: ${failed_c[*]}"
exit 0
