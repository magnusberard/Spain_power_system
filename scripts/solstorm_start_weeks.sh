#!/usr/bin/env bash
# Start this node's share of a period split into weeks, on NTNU's Solstorm
# cluster. The weeks are dealt out over N nodes (part k of N gets weeks k, k+N,
# k+2N, ...); on this node they are spread over several "lanes", each a detached
# screen session that runs its weeks one after another (run_day_ranges.sh).
# Run it on a compute node, from the repo root:
#
#     IPOPT=ma57 scripts/solstorm_start_weeks.sh offered /storage/users/$USER/results/2024_offered_weeks 1/5
#
#   1st argument : [run].res_input ("accepted" or "offered"); the script writes
#                  scripts/config_<res_input>.toml (a copy of config.toml with
#                  that setting; git ignores it)
#   2nd argument : parent folder for the week folders (<folder>/<from>_<to>/)
#   3rd argument : this node's part, k/N (run k = 1 .. N on N different nodes)
#   optional     : LANES (default 6), FROM (2024-01-01), TO (2024-12-29),
#                  DAYS (7) and IPOPT (mumps; ma57 once HSL is set up), as
#                  environment variables in front of the command
#
# Watch:   screen -ls                          (sessions <res>-p<k>-l<lane>)
#          screen -r off-p1-l1                 (leave with Ctrl+A, then D)
#          tail -n 3 <folder>/*/run.log
# Join the weeks afterwards with scripts/merge_runs.py.
set -eu

[ $# -ge 3 ] || { sed -n '2,24p' "$0"; exit 1; }
RES="$1"; OUT="$2"; PART="$3"
case "$RES" in accepted|offered) ;; *) echo "res_input must be accepted or offered"; exit 1 ;; esac
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
LANES="${LANES:-6}"; FROM="${FROM:-2024-01-01}"; TO="${TO:-2024-12-29}"; DAYS="${DAYS:-7}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$REPO/scripts/config_$RES.toml"
# write the config copy atomically: other nodes may write the same file at the same time
TMP="$CFG.$$.${HOSTNAME:-node}"
sed "s/^res_input = \"[a-z]*\"/res_input = \"$RES\"/" "$REPO/config.toml" > "$TMP"
grep -q "^res_input = \"$RES\"" "$TMP" || { rm -f "$TMP"; echo "could not set res_input"; exit 1; }
mv -f "$TMP" "$CFG"
mkdir -p "$OUT"

# all chunks of the period, then this part's share
chunks=()
start="$FROM"
while [ "$(date -d "$start" +%s)" -le "$(date -d "$TO" +%s)" ]; do
    end="$(date -d "$start +$((DAYS - 1)) day" +%Y-%m-%d)"
    [ "$(date -d "$end" +%s)" -gt "$(date -d "$TO" +%s)" ] && end="$TO"
    chunks+=("$start:$end")
    start="$(date -d "$end +1 day" +%Y-%m-%d)"
done
mine=()
for i in "${!chunks[@]}"; do
    [ $(( i % N )) -eq $(( K - 1 )) ] && mine+=("${chunks[$i]}")
done
echo "${#chunks[@]} chunks of $DAYS days in $FROM .. $TO; part $K/$N runs ${#mine[@]} of them in up to $LANES lanes ($RES)"

tag="${RES:0:3}"
for lane in $(seq 1 "$LANES"); do
    ranges=()
    for j in "${!mine[@]}"; do
        [ $(( j % LANES )) -eq $(( lane - 1 )) ] && ranges+=("${mine[$j]}")
    done
    [ ${#ranges[@]} -eq 0 ] && continue
    name="$tag-p$K-l$lane"
    # bash -l: a login shell, so the `module` command is defined
    screen -dmS "$name" bash -lc "cd '$REPO' && source scripts/solstorm_env.sh '${IPOPT:-mumps}' \
        && SPAIN_CONFIG='$CFG' scripts/run_day_ranges.sh '$OUT' ${ranges[*]}; exec bash"
    echo "  $name: ${ranges[*]}"
done
echo "screen sessions on $(hostname):"
screen -ls | grep -E "\.$tag-p$K-l[0-9]+" || true
