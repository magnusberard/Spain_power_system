#!/usr/bin/env bash
# One lane of a redispatch-realism run: the standalone redispatch of each given
# day, one after another, into <out>/<day>/. Started by solstorm_start_realism.sh;
# can also be run by hand:
#
#     redispatch_realism/run_days.sh <src> <out> 2024-12-02 2024-12-03 ...
#
# <src>: the run whose market results are reused — either a split-run parent
#        folder (chunk folders FROM_TO/ listed in chunks.txt) or one run folder.
# <out>: holds config_realism.toml (written by solstorm_start_realism.sh) and
#        gets one folder per day, whose inputs (bal_dispatch.csv, da_dispatch.csv,
#        market_prices.csv) are links to the source chunk's files.
# A day that already has summary.csv is skipped, so a lane can be restarted.
set -u
[ $# -ge 3 ] || { sed -n '2,15p' "$0"; exit 1; }
SRC="$1"; OUT="$2"; shift 2
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$OUT/config_realism.toml"
[ -f "$CFG" ] || { echo "$CFG not found - start with solstorm_start_realism.sh"; exit 1; }

# the folder of <src> that holds <day>'s market results
source_of() {
    local d="$1"
    if [ -f "$SRC/chunks.txt" ]; then
        while read -r c; do
            [ -z "$c" ] && continue
            local from="${c%%_*}" to="${c##*_}"
            if [[ ! "$d" < "$from" && ! "$d" > "$to" ]]; then echo "$SRC/$c"; return; fi
        done < "$SRC/chunks.txt"
    else
        echo "$SRC"
    fi
}

done_d=(); failed_d=()
for d in "$@"; do
    dir="$OUT/$d"
    if [ -f "$dir/summary.csv" ]; then echo "[$d] done already, skipping"; continue; fi
    s="$(source_of "$d")"
    if [ -z "$s" ] || [ ! -f "$s/bal_dispatch.csv" ]; then
        echo "[$d] no market results for this day in $SRC - skipped"; failed_d+=("$d"); continue
    fi
    mkdir -p "$dir"
    for f in bal_dispatch.csv da_dispatch.csv market_prices.csv; do
        [ -e "$dir/$f" ] || ln -s "$s/$f" "$dir/$f"
    done
    t0=$(date +%s)
    echo "[$d] $(date +%H:%M)  redispatch (from $(basename "$s")) ..."
    ( cd "$REPO" && SPAIN_DAYS="$d:$d" SPAIN_RESULTS="$dir" SPAIN_CONFIG="$CFG" \
          julia --project=. run_market_chain.jl ) > "$dir/run.log" 2>&1
    code=$?
    mins=$(( ($(date +%s) - t0 + 30) / 60 ))
    if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
        echo "[$d] finished in $mins min"; done_d+=("$d")
    else
        echo "[$d] FAILED (exit code $code) after $mins min - see $dir/run.log"; failed_d+=("$d")
    fi
done
echo ""
echo "Done this lane: ${done_d[*]:-none}"
[ ${#failed_d[@]} -gt 0 ] && echo "Failed or skipped: ${failed_d[*]}"
exit 0
