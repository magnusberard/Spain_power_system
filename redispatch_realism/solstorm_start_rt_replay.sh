#!/usr/bin/env bash
# Rerun only real time on a finished in-chain year run, week by week, in parallel (10 Nov 2026).
#
# Real time does not feed back: it starts every hour from the saved balancing schedule plus phase I's saved effects and
# changes nothing the markets, phase I or the next week use. So a year's real time can be rerun without the markets:
# each week of <src> is copied to <out> (without branch_flows.csv and ipopt_logs, which real time rewrites), its own
# config_inchain.toml is turned into a replay config (make_rt_replay_config.jl: from_saved = "BAL", phase I replayed
# from rd_phase1*.csv; fix A on unless UNDELIVERABLE=1), and run_market_chain.jl solves real time only.
#
# Start the same command on N nodes with k = 1..N; weeks are dealt round-robin over all N × LANES lanes.
#
#   redispatch_realism/solstorm_start_rt_replay.sh <src year folder> <out folder> k/N
#   LANES (6 per node), IPOPT (ma57), UNDELIVERABLE=1 (fix A off), DRY=1 (plan only)
# Watch:   tail -qn 1 <out>/lane-*.log ; ls <out>/*/summary.csv | wc -l (weeks done) ; ls <out>/*/FAILED
# Restart: the same command; weeks with summary.csv are skipped.
set -u
[ $# -ge 3 ] || { sed -n '2,17p' "$0"; exit 1; }
SRC="$1"; OUT="$2"; PART="$3"
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
LANES="${LANES:-6}"; IPOPT="${IPOPT:-ma57}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DELIV="--deliverable"; FIX=on; [ -n "${UNDELIVERABLE:-}" ] && { DELIV=""; FIX=off; }
mkdir -p "$OUT"
weeks=()
for d in "$SRC"/2024-*_2024-*; do [ -f "$d/bal_dispatch.csv" ] && [ -f "$d/rd_phase1.csv" ] && weeks+=("$(basename "$d")"); done
G=$(( N * LANES ))
echo "${#weeks[@]} weeks in $SRC over $G lanes ($N nodes × $LANES); part $K/$N on $(hostname); fix A $FIX"
[ "${#weeks[@]}" -gt 0 ] || { echo "no saved in-chain weeks (bal_dispatch.csv + rd_phase1.csv) in $SRC"; exit 1; }
[ "$K" -eq 1 ] && echo "src $SRC | fix A $FIX | $(git -C "$REPO" log -1 --oneline)" > "$OUT/settings.txt"

if [ -n "${DRY:-}" ]; then
    for lane in $(seq 1 "$LANES"); do
        g=$(( (K - 1) * LANES + lane - 1 )); mine=()
        for i in "${!weeks[@]}"; do [ $(( i % G )) -eq "$g" ] && mine+=("${weeks[$i]}"); done
        echo "  lane p$K-l$lane: ${mine[*]:-none}"
    done
    exit 0
fi

for lane in $(seq 1 "$LANES"); do
    g=$(( (K - 1) * LANES + lane - 1 ))
    name="p$K-l$lane"
    launcher="nohup"; command -v setsid >/dev/null 2>&1 && launcher="setsid nohup"
    $launcher bash -c '
        SRC="$1"; OUT="$2"; REPO="$3"; IPOPT="$4"; DELIV="$5"; G="$6"; g="$7"; shift 7; weeks=("$@")
        cd "$REPO" && source scripts/solstorm_env.sh "$IPOPT"
        for i in "${!weeks[@]}"; do
            [ $(( i % G )) -eq "$g" ] || continue
            w="${weeks[$i]}"; dir="$OUT/$w"
            if [ -f "$dir/summary.csv" ]; then echo "[$w] done already, skipping"; continue; fi
            rm -rf "$dir"; mkdir -p "$OUT"
            ( cd "$SRC" && tar cf - --exclude=branch_flows.csv --exclude=ipopt_logs "$w" ) | ( cd "$OUT" && tar xf - ) \
                || { echo "[$w] copy FAILED"; continue; }
            rm -f "$dir/summary.csv" "$dir/rd_reserve.csv" "$dir/FAILED"      # rewritten by the replay
            t0=$(date +%s); echo "[$w] $(date +%H:%M) start"
            julia redispatch_realism/make_rt_replay_config.jl "$dir/config_inchain.toml" "$dir/config_replay.toml" $DELIV \
                > "$dir/make_config_replay.log" 2>&1 || { echo "[$w] replay config FAILED"; touch "$dir/FAILED"; continue; }
            from="${w%%_*}"; to="${w##*_}"
            SPAIN_DAYS="$from:$to" SPAIN_CONFIG="$dir/config_replay.toml" SPAIN_RESULTS="$dir" IPOPT_LINEAR_SOLVER="$IPOPT" \
                julia --project=. run_market_chain.jl > "$dir/run_replay.log" 2>&1
            code=$?; mins=$(( ($(date +%s) - t0 + 30) / 60 ))
            if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
                echo "[$w] finished in $mins min ($(grep -o "Solved [0-9]* / [0-9]* hours" "$dir/run_replay.log" | tail -n1))"
            else
                echo "[$w] FAILED (exit code $code) after $mins min - see $dir/run_replay.log"; touch "$dir/FAILED"
            fi
        done
        echo "lane done"
    ' _ "$SRC" "$OUT" "$REPO" "$IPOPT" "$DELIV" "$G" "$g" "${weeks[@]}" > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  lane $name started (log $OUT/lane-$name.log)"
done
