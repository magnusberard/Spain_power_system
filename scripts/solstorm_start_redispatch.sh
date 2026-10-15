#!/usr/bin/env bash
# Start this node's share of step 2 of a split run on NTNU's Solstorm cluster:
# the network redispatch of the chunks in <folder>/chunks.txt (written by step 1,
# solstorm_start_markets.sh). The chunks are dealt out over N nodes (part k of N
# gets chunks k, k+N, k+2N, ...) and on this node over several "lanes", each a
# background process that runs its chunks one after another
# (scripts/run_redispatch_only.sh) and logs to <folder>/lane-rd-p<k>-l<lane>.log.
# A chunk whose markets are not done yet is waited for, so this can be started
# while step 1 is still running. Run it on a compute node, from the repo root:
#
#     IPOPT=ma57 scripts/solstorm_start_redispatch.sh /storage/users/$USER/results/2024_gas 1/4
#
#   1st argument : the parent folder of step 1
#   2nd argument : this node's part, k/N (run k = 1 .. N on N different nodes)
#   optional     : LANES (default 6) and IPOPT (mumps; ma57 once HSL is set up)
#
# Watch:   tail -n 3 <folder>/lane-rd-*.log
#          ls <folder>/*/summary.csv | wc -l    (finished chunks, all nodes)
# Stop:    pkill -u $USER -f run_redispatch_only.sh; pkill -u $USER julia   (this node only)
# Join the chunks afterwards: python3 scripts/merge_runs.py <new folder> <folder>
set -eu

[ $# -ge 2 ] || { sed -n '2,20p' "$0"; exit 1; }
OUT="$1"; PART="$2"
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
LANES="${LANES:-6}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$OUT/chunks.txt" ] || { echo "$OUT/chunks.txt not found - start step 1 (solstorm_start_markets.sh) first"; exit 1; }

mapfile -t chunks < "$OUT/chunks.txt"
mine=()
for i in "${!chunks[@]}"; do
    [ $(( i % N )) -eq $(( K - 1 )) ] && mine+=("${chunks[$i]}")
done
echo "${#chunks[@]} chunks; part $K/$N runs ${#mine[@]} of them in up to $LANES lanes"

for lane in $(seq 1 "$LANES"); do
    list=()
    for j in "${!mine[@]}"; do
        [ $(( j % LANES )) -eq $(( lane - 1 )) ] && list+=("${mine[$j]}")
    done
    [ ${#list[@]} -eq 0 ] && continue
    name="rd-p$K-l$lane"
    setsid nohup bash -lc "cd '$REPO' && source scripts/solstorm_env.sh '${IPOPT:-mumps}' \
        && scripts/run_redispatch_only.sh '$OUT' ${list[*]}" \
        > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  $name (pid $!): ${list[*]}"
done
sleep 2
echo "lanes running on $(hostname): $(ps -u "${USER:-$(id -un)}" -o args | grep -c '[r]un_redispatch_only' || true)"
