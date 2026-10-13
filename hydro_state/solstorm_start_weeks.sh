#!/usr/bin/env bash
# Start this node's share of a full-chain 2024 week run on Solstorm with a given config — the
# hydro-state counterpart of scripts/solstorm_start_weeks.sh, which always starts from the
# tracked config.toml. Same splitting (weeks dealt over N nodes, then over lanes), same
# per-week runner (scripts/run_day_ranges.sh), same joining (scripts/merge_runs.py).
#
#     IPOPT=ma57 hydro_state/solstorm_start_weeks.sh hydro_state/config_observed.toml offered \
#         /storage/users/$USER/results/2024_offered_hydro_observed 1/5
#
#   1st argument : the config to run (normally hydro_state/config_<label>.toml)
#   2nd argument : [run].res_input, "accepted" or "offered"; written into a copy
#                  hydro_state/run_<label>_<res>.toml (git ignores it)
#   3rd argument : parent folder for the week folders (<folder>/<from>_<to>/)
#   4th argument : this node's part, k/N
#   optional     : LANES (6), FROM (2024-01-01), TO (2024-12-29), DAYS (7), IPOPT (mumps)
set -eu

[ $# -ge 4 ] || { sed -n '2,17p' "$0"; exit 1; }
CFG_IN="$1"; RES="$2"; OUT="$3"; PART="$4"
case "$RES" in accepted|offered) ;; *) echo "res_input must be accepted or offered"; exit 1 ;; esac
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
LANES="${LANES:-6}"; FROM="${FROM:-2024-01-01}"; TO="${TO:-2024-12-29}"; DAYS="${DAYS:-7}"

REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$REPO/$CFG_IN" ] || [ -f "$CFG_IN" ] || { echo "config $CFG_IN not found"; exit 1; }
[ -f "$REPO/$CFG_IN" ] && CFG_IN="$REPO/$CFG_IN"
label="$(basename "$CFG_IN" .toml)"
CFG="$REPO/hydro_state/run_${label}_$RES.toml"
TMP="$CFG.$$.${HOSTNAME:-node}"
# res_input sits under [run], possibly indented by TOML.print
sed -E "s/^([[:space:]]*)res_input = \"[a-z]*\"/\1res_input = \"$RES\"/" "$CFG_IN" > "$TMP"
grep -Eq "^[[:space:]]*res_input = \"$RES\"" "$TMP" || { rm -f "$TMP"; echo "could not set res_input"; exit 1; }
mv -f "$TMP" "$CFG"
mkdir -p "$OUT"

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
echo "${#chunks[@]} chunks of $DAYS days; part $K/$N runs ${#mine[@]} in up to $LANES lanes ($label, $RES)"

for lane in $(seq 1 "$LANES"); do
    ranges=()
    for j in "${!mine[@]}"; do
        [ $(( j % LANES )) -eq $(( lane - 1 )) ] && ranges+=("${mine[$j]}")
    done
    [ ${#ranges[@]} -eq 0 ] && continue
    name="hs-p$K-l$lane"
    setsid nohup bash -lc "cd '$REPO' && source scripts/solstorm_env.sh '${IPOPT:-mumps}' \
        && SPAIN_CONFIG='$CFG' scripts/run_day_ranges.sh '$OUT' ${ranges[*]}" \
        > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  $name (pid $!): ${ranges[*]}"
done
sleep 2
echo "lanes running on $(hostname): $(ps -u "${USER:-$(id -un)}" -o args | grep -c '[r]un_day_ranges' || true)"
