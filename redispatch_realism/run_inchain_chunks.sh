#!/usr/bin/env bash
# One lane of an in-chain year run (level 1): the whole chain for each given chunk of the source run,
# one after another, into <out>/<chunk>/. Each chunk gets its own config: config.toml + that chunk's
# market config + the realism switches + --in-chain. Started by solstorm_start_inchain_year.sh; can
# also be run by hand:
#
#     redispatch_realism/run_inchain_chunks.sh <src> <out> 2024-12-02_2024-12-08 2024-12-09_2024-12-15 ...
#
# <src>: a split-run parent folder (chunks.txt + FROM_TO/ chunk folders, e.g. Lars Erik's run 4)
# FROM, TO (optional): clip each chunk's days to this range
# EXTRA: make_config flags (default: the realism set, as solstorm_start_inchain.sh)
# A chunk that already has summary.csv is skipped, so a lane can be restarted.
set -u
[ $# -ge 3 ] || { sed -n '2,13p' "$0"; exit 1; }
SRC="$1"; OUT="$2"; shift 2
REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXTRA="${EXTRA:---ac-check --hydro-budget --dedup-ab --sync-q 0.15 --no-rt-zones --down-only --unit-req}"
FROM="${FROM:-2024-01-01}"; TO="${TO:-2024-12-31}"

done_c=(); failed_c=()
for c in "$@"; do
    dir="$OUT/$c"
    if [ -f "$dir/summary.csv" ]; then echo "[$c] done already, skipping"; continue; fi
    from="${c%%_*}"; to="${c##*_}"
    [[ "$from" < "$FROM" ]] && from="$FROM"
    [[ "$to" > "$TO" ]] && to="$TO"
    srccfg=""
    for f in "$SRC/$c/config_used_market.toml" "$SRC/$c/config_used.toml"; do [ -f "$f" ] && { srccfg="$f"; break; }; done
    if [ -z "$srccfg" ]; then echo "[$c] no market config in $SRC/$c - skipped"; failed_c+=("$c"); continue; fi
    mkdir -p "$dir"
    t0=$(date +%s)
    echo "[$c] $(date +%H:%M)  days $from .. $to, config from $(basename "$srccfg") ..."
    ( cd "$REPO" && julia redispatch_realism/make_config.jl "$dir/config_inchain.toml" --source "$srccfg" $EXTRA --in-chain ) \
        > "$dir/make_config.log" 2>&1 || { echo "[$c] make_config FAILED - see $dir/make_config.log"; failed_c+=("$c"); continue; }
    ( cd "$REPO" && SPAIN_DAYS="$from:$to" SPAIN_CONFIG="$dir/config_inchain.toml" SPAIN_RESULTS="$dir" \
          IPOPT_LINEAR_SOLVER="${IPOPT:-ma57}" julia --project=. run_market_chain.jl ) > "$dir/run.log" 2>&1
    code=$?
    mins=$(( ($(date +%s) - t0 + 30) / 60 ))
    if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
        echo "[$c] finished in $mins min ($(grep -o 'Solved [0-9]* / [0-9]* hours' "$dir/run.log" | tail -n1))"; done_c+=("$c")
    else
        echo "[$c] FAILED (exit code $code) after $mins min - see $dir/run.log"; failed_c+=("$c")
    fi
done
echo ""
echo "Done this lane: ${done_c[*]:-none}"
echo "Failed this lane: ${failed_c[*]:-none}"
