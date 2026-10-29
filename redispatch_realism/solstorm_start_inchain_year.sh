#!/usr/bin/env bash
# Start this node's share of an in-chain run (level 1) over many weeks on NTNU's Solstorm cluster:
# markets with the source run's settings, phase I inside the chain, the AC check and real time.
# Chunks follow the source run's own weekly chunks (chunks.txt), so every chunk starts from the same
# market config and state as the source; a chunk's days run in order inside one process. Chunks are
# dealt out over N nodes (part k of N gets chunks k, k+N, ...) and on this node over LANES lanes,
# each a run_inchain_chunks.sh loop logging to <out>/lane-p<k>-l<lane>.log. Run it on a compute node
# (never the login node), from the repo root, on branch redispatch-realism:
#
#     FROM=2024-12-02 TO=2024-12-29 redispatch_realism/solstorm_start_inchain_year.sh <src> <out> 1/1
#
#   <src>   split-run parent folder of the source run (chunks.txt + FROM_TO/ chunk folders, each with
#           config_used_market.toml), e.g. /storage/users/larseeid/results/2024_r4_hydro_offered
#   <out>   new folder for this run (one subfolder per chunk)
#   k/N     this node's part (k = 1 .. N on N different free nodes; at most 5)
#   options FROM, TO (default 2024-01-01 .. 2024-12-29; chunks are clipped to them),
#           LANES (default 4 — one week per lane takes 2-3 h; measure memory on the month test first),
#           IPOPT (default ma57), EXTRA (make_config flags; default the realism set, as
#           solstorm_start_inchain.sh), DRY=1 (print the plan only)
#
# Watch:   tail -n 3 <out>/lane-*.log
#          ls <out>/*/summary.csv | wc -l        (finished chunks, all nodes)
#          free -g; top -u $USER                 (memory per lane, on the month test)
# Stop:    pkill -u $USER -f run_inchain_chunks.sh; pkill -u $USER julia   (this node only)
# Check:   python3 redispatch_realism/compare_ree.py <out>/<chunk> ... (one chunk = one in-chain run)
set -eu

[ $# -ge 3 ] || { sed -n '2,25p' "$0"; exit 1; }
SRC="$1"; OUT="$2"; PART="$3"
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
export FROM="${FROM:-2024-01-01}" TO="${TO:-2024-12-29}" IPOPT="${IPOPT:-ma57}"
LANES="${LANES:-4}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$SRC/chunks.txt" ] || { echo "$SRC/chunks.txt not found (need a split-run parent folder)"; exit 1; }
mkdir -p "$OUT"

if [ -z "${DRY:-}" ] && { command -v module >/dev/null 2>&1 || [ -n "${MODULESHOME:-}" ]; }; then
    source "$REPO/scripts/solstorm_env.sh" "$IPOPT"
fi

# the source run's chunks that overlap FROM .. TO
chunks=()
while read -r c; do
    [ -z "$c" ] && continue
    from="${c%%_*}"; to="${c##*_}"
    [[ "$to" < "$FROM" || "$from" > "$TO" ]] && continue
    chunks+=("$c")
done < "$SRC/chunks.txt"
[ ${#chunks[@]} -gt 0 ] || { echo "no chunk of $SRC overlaps $FROM .. $TO"; exit 1; }
mine=()
for i in "${!chunks[@]}"; do [ $(( i % N )) -eq $(( K - 1 )) ] && mine+=("${chunks[$i]}"); done
echo "${#chunks[@]} chunks in $FROM .. $TO; part $K/$N runs ${#mine[@]} of them in up to $LANES lanes; source $SRC"

for lane in $(seq 1 "$LANES"); do
    list=()
    for j in "${!mine[@]}"; do [ $(( j % LANES )) -eq $(( lane - 1 )) ] && list+=("${mine[$j]}"); done
    [ ${#list[@]} -eq 0 ] && continue
    name="p$K-l$lane"
    if [ -n "${DRY:-}" ]; then echo "  $name: ${list[*]}"; continue; fi
    launcher="nohup"; command -v setsid >/dev/null 2>&1 && launcher="setsid nohup"
    $launcher bash -c "cd '$REPO' && redispatch_realism/run_inchain_chunks.sh '$SRC' '$OUT' ${list[*]}" \
        > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  $name (pid $!): ${list[*]}"
done
[ -n "${DRY:-}" ] && exit 0
sleep 2
echo "lanes started on $(hostname)"
