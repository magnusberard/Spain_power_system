#!/usr/bin/env bash
# Start this node's share of a redispatch-realism run on NTNU's Solstorm cluster:
# the standalone network redispatch (RD1-RD11, see redispatch_realism/README.md)
# of every day from FROM to TO, reusing the market results of an existing run.
# Days are independent here, so they are dealt out over N nodes (part k of N gets
# days k, k+N, k+2N, ...) and on this node over LANES background lanes, each a
# run_days.sh loop logging to <out>/lane-p<k>-l<lane>.log. Run it on a compute
# node (never the login node), from the repo root, on branch redispatch-realism:
#
#     FROM=2024-12-01 TO=2024-12-31 IPOPT=ma57 \
#       redispatch_realism/solstorm_start_realism.sh <src> <out> 1/1
#
#   <src>   the run whose market results are reused: a split-run parent folder
#           (chunks.txt + FROM_TO/ chunk folders, e.g. Lars Erik's full-year runs)
#           or one run folder with bal_dispatch.csv, da_dispatch.csv, market_prices.csv
#   <out>   new folder for this run (one subfolder per day)
#   k/N     this node's part (run k = 1 .. N on N different free nodes; at most 5)
#   options FROM, TO (default 2024-01-01 .. 2024-12-29), LANES (default 12 —
#           compute-5-* has 20 cores and 96 GB; each lane needs ~3 GB),
#           IPOPT (ma57 once HSL is set up, else mumps), N1=on (add RD6),
#           AC=on (step C), ZONES=off (RD5 off), HB=on (RD13 water budget),
#           RESMVAR=<Mvar> (renewables' connection networks, capacitive, in total),
#           DEDUP=on (count the a/b duplicate rows of Data/lines.csv once),
#           SYNCQ=<frac> (synchronous units |Q| <= frac x installed MW; P.O. 7.4: 0.15),
#           DRY=1 (write the config and print the plan only)
#           Local week runs: C4 = AC=on HB=on; C2b = AC=on ZONES=off HB=on
#
# The config is written once (by the first node to get there):
#     <out>/config_realism.toml = config.toml + the source run's config + realism switches
#
# Watch:   tail -n 3 <out>/lane-*.log
#          ls <out>/*/summary.csv | wc -l      (finished days, all nodes)
# Stop:    pkill -u $USER -f run_days.sh; pkill -u $USER julia   (this node only)
# Join:    python3 scripts/merge_runs.py <merged folder> <out>
# Check:   python3 redispatch_realism/compare_ree.py <out> --bids ... (see README)
set -eu

[ $# -ge 3 ] || { sed -n '2,32p' "$0"; exit 1; }
SRC="$1"; OUT="$2"; PART="$3"
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
FROM="${FROM:-2024-01-01}"; TO="${TO:-2024-12-29}"; LANES="${LANES:-12}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -d "$SRC" ] || { echo "source folder $SRC not found"; exit 1; }
mkdir -p "$OUT"

# Solstorm modules and depot (skipped where there is no `module`, e.g. a local test)
if command -v module >/dev/null 2>&1 || [ -n "${MODULESHOME:-}" ]; then
    source "$REPO/scripts/solstorm_env.sh" "${IPOPT:-mumps}"
fi

# config: config.toml + the source run's config + the realism switches
CFG="$OUT/config_realism.toml"
if [ ! -f "$CFG" ]; then
    srccfg=""
    for c in "$SRC/config_redispatch.toml" "$SRC/config_used.toml"; do [ -f "$c" ] && { srccfg="$c"; break; }; done
    if [ -z "$srccfg" ] && [ -f "$SRC/chunks.txt" ]; then
        first="$(head -n1 "$SRC/chunks.txt")"; [ -f "$SRC/$first/config_used.toml" ] && srccfg="$SRC/$first/config_used.toml"
    fi
    [ -n "$srccfg" ] || echo "warning: no config of the source run found - using config.toml's market settings"
    flags=()
    [ "${AC:-}" = on ] && flags+=(--ac-check)
    [ "${ZONES:-}" = off ] && flags+=(--no-zones)
    [ "${HB:-}" = on ] && flags+=(--hydro-budget)
    [ -n "${RESMVAR:-}" ] && flags+=(--res-mvar "$RESMVAR")
    [ "${DEDUP:-}" = on ] && flags+=(--dedup-ab)
    [ -n "${SYNCQ:-}" ] && flags+=(--sync-q "$SYNCQ")
    ( cd "$REPO" && julia redispatch_realism/make_config.jl "$CFG" ${srccfg:+--source "$srccfg"} ${N1:+--n1 "$N1"} ${flags[@]+"${flags[@]}"} )
fi

# the days, dealt out over nodes and lanes
days=()
d="$FROM"
while [[ ! "$d" > "$TO" ]]; do days+=("$d"); d="$(date -I -d "$d + 1 day")"; done
mine=()
for i in "${!days[@]}"; do [ $(( i % N )) -eq $(( K - 1 )) ] && mine+=("${days[$i]}"); done
echo "${#days[@]} days $FROM .. $TO; part $K/$N runs ${#mine[@]} of them in up to $LANES lanes; source $SRC"

for lane in $(seq 1 "$LANES"); do
    list=()
    for j in "${!mine[@]}"; do [ $(( j % LANES )) -eq $(( lane - 1 )) ] && list+=("${mine[$j]}"); done
    [ ${#list[@]} -eq 0 ] && continue
    name="p$K-l$lane"
    if [ -n "${DRY:-}" ]; then echo "  $name: ${list[*]}"; continue; fi
    launcher="nohup"; command -v setsid >/dev/null 2>&1 && launcher="setsid nohup"
    $launcher bash -c "cd '$REPO' && redispatch_realism/run_days.sh '$SRC' '$OUT' ${list[*]}" \
        > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  $name (pid $!): ${list[*]}"
done
[ -n "${DRY:-}" ] && exit 0
sleep 2
echo "lanes started on $(hostname)"
