#!/usr/bin/env bash
# Step 1 of a split run: clear the MARKET stages (DA, ID2, ID3, CID, BAL — no
# network redispatch) for a period, chunk after chunk IN ORDER, so the gas/coal
# unit-commitment state carries over exactly between chunks: each chunk ends by
# writing <chunk>/uc_state.json and the next one starts from it
# (SPAIN_UC_STATE_IN). Step 2, the redispatch of each finished chunk, runs in
# parallel with scripts/run_redispatch_only.sh (on Solstorm:
# solstorm_start_redispatch.sh); step 3 joins the chunks with merge_runs.py.
#
#     scripts/run_markets_sequential.sh <out>
#     GAS=on FROM=2024-01-01 TO=2024-12-31 DAYS=7 scripts/run_markets_sequential.sh <out>
#
#   <out>     parent folder; one folder per chunk, <out>/<from>_<to>/
#   FROM, TO  first and last study day (default 2024-01-01 .. 2024-12-31)
#   DAYS      chunk length in days (default 7)
#   GAS       on: the gas/coal switches on (scripts/make_run_config.jl); off
#             (default): config.toml as it is
#   MARKUP    on: [costs.markup] on as well (generation tax + RSI mark-ups); off (default)
#   HYDRO     optional hydro_state variant for [bellman] (e.g. aligned_rc_observed)
#   RES       optional [run].res_input (accepted or offered)
#
# Writes <out>/config_markets.toml, <out>/config_redispatch.toml and
# <out>/chunks.txt (the chunk list step 2 reads). A finished chunk gets a file
# market_done; on a rerun finished chunks are skipped and the chain continues
# from the last uc_state.json. A failed chunk stops the chain (the next chunk
# would lose its starting state). Per chunk: run_market.log, the market
# run_info_market.json and config_used_market.toml (renamed so the redispatch
# run does not overwrite them).
#
# First day of the period: free initial state (units the model runs in hour 1
# count as already on); every later day starts from the day before.
set -u

[ $# -ge 1 ] || { sed -n '2,30p' "$0"; exit 1; }
OUT="$1"
FROM="${FROM:-2024-01-01}"; TO="${TO:-2024-12-31}"; DAYS="${DAYS:-7}"; GAS="${GAS:-off}"; MARKUP="${MARKUP:-off}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

RES_ARG=()
[ -n "${RES:-}" ] && RES_ARG=(--res-input "$RES")
[ -n "${HYDRO:-}" ] && RES_ARG+=(--hydro "$HYDRO")
julia --startup-file=no "$REPO/scripts/make_run_config.jl" "$OUT/config_markets.toml" --stage markets --gas "$GAS" --markup "$MARKUP" ${RES_ARG[@]+"${RES_ARG[@]}"} || exit 1
julia --startup-file=no "$REPO/scripts/make_run_config.jl" "$OUT/config_redispatch.toml" --stage redispatch --gas "$GAS" --markup "$MARKUP" ${RES_ARG[@]+"${RES_ARG[@]}"} || exit 1

# chunks of DAYS days in FROM .. TO
chunks=()
start="$FROM"
while [ "$(date -d "$start" +%s)" -le "$(date -d "$TO" +%s)" ]; do
    end="$(date -d "$start +$((DAYS - 1)) day" +%Y-%m-%d)"
    [ "$(date -d "$end" +%s)" -gt "$(date -d "$TO" +%s)" ] && end="$TO"
    chunks+=("${start}_${end}")
    start="$(date -d "$end +1 day" +%Y-%m-%d)"
done
printf "%s\n" "${chunks[@]}" > "$OUT/chunks.txt"
echo "${#chunks[@]} chunks of $DAYS days in $FROM .. $TO (gas $GAS) → $OUT"

prev=""
for c in "${chunks[@]}"; do
    dir="$OUT/$c"
    from="${c%%_*}"; to="${c##*_}"
    if [ -f "$dir/market_done" ]; then
        echo "[$c] markets already done, skipping"
        prev="$dir"; continue
    fi
    mkdir -p "$dir"
    state_in=""
    [ -n "$prev" ] && [ -f "$prev/uc_state.json" ] && state_in="$prev/uc_state.json"
    t0=$(date +%s)
    echo "[$c] $(date +%H:%M)  markets ...${state_in:+ (state from $(basename "$prev"))}"
    ( cd "$REPO" && SPAIN_DAYS="$from:$to" SPAIN_RESULTS="$dir" SPAIN_CONFIG="$OUT/config_markets.toml" \
          SPAIN_UC_STATE_IN="$state_in" julia --project=. run_market_chain.jl ) > "$dir/run_market.log" 2>&1
    code=$?
    mins=$(( ($(date +%s) - t0 + 30) / 60 ))
    if [ "$code" -ne 0 ] || [ ! -f "$dir/bal_dispatch.csv" ]; then
        echo "[$c] FAILED (exit code $code) after $mins min - see $dir/run_market.log; stopping the chain"
        exit 1
    fi
    mv -f "$dir/run_info.json" "$dir/run_info_market.json"
    mv -f "$dir/config_used.toml" "$dir/config_used_market.toml"
    [ -f "$dir/run_info_diff.patch" ] && mv -f "$dir/run_info_diff.patch" "$dir/run_info_diff_market.patch"
    touch "$dir/market_done"
    echo "[$c] markets finished in $mins min"
    prev="$dir"
done
echo "All ${#chunks[@]} chunks: markets done."
