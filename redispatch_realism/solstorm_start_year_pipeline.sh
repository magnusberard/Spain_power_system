#!/usr/bin/env bash
# A sequential in-chain year (phase I inside the market chain), pipelined over lanes and nodes on NTNU's Solstorm.
#
# Why sequential: the gas/coal unit-commitment state carries from day to day, and with IDSTARTS=on the intraday
# auctions (after phase I, under its security limits) may start units, so phase I's effects reach the next day.
# Each week therefore starts from the state of the week before (SPAIN_UC_STATE_IN), as in Lars Erik's
# scripts/run_markets_sequential.sh. Why pipelined: run_market_chain.jl writes <week>/uc_state.json right after the
# week's market stages and phase I (~15 min); the week's AC check and real time (~75 min) never change it. So week
# k+1 starts as soon as week k's state file exists, while week k's AC check and real time still run: about
# 53 × 15 min + 1.5 h for the year, if enough lanes are free (≈ 7 per run).
#
# Market settings: the same run options as scripts/run_markets_sequential.sh (GAS, MARKUP, HYDRO, RES, PUMPING,
# PUMPLIMIT, IDSTARTS, HYDROTOPUP, PARTICIPATION, BALANCING), turned into <out>/config_markets.toml by
# scripts/make_run_config.jl; our redispatch is laid on top per week by redispatch_realism/make_config.jl
# ($EXTRA --in-chain). REDISPATCH=ree (the website's placeholder) is not needed here.
#
# Start the same command on N free compute nodes, with k = 1..N (part 1 writes the shared config and chunk list).
# Weeks are dealt round-robin over all N × LANES lanes; each lane runs its weeks in order, waiting for the
# previous week's uc_state.json. Run from the repo copy whose Data/ the run should use (e.g. the border-tie copy).
#
#   GAS=on MARKUP=on HYDRO=aligned_rc_observed RES=offered PUMPING=removed PUMPLIMIT=on IDSTARTS=on HYDROTOPUP=on \
#   BALANCING=qualified [PARTICIPATION=measured_all|passive] \
#   EXTRA="--ac-check ... --offers redispatch_realism/data/phase2_offers_2024_tail.csv" \
#   redispatch_realism/solstorm_start_year_pipeline.sh <out> k/N
#
#   FROM, TO (default 2024-01-01 .. 2024-12-31), DAYS (7), LANES (4 per node), IPOPT (ma57), DRY=1 (plan only)
#   SCENARIO=trinity|necp: a 2035 run (scripts/make_run_config.jl --scenario: EMPIRE fleet, 52 study weeks on the
#     2024 calendar with weather year 2015, TO defaults to 2024-12-29). Leave GAS, MARKUP and HYDRO out (the scenario
#     sets its own switches) and PUMPING too (2024's real pumping). EXTRA for 2035: no --offers (REE's 2024 offers),
#     --offer-rule redispatch_realism/data/phase2_offer_rule.csv instead; --zone-rule; --rt-reserve-e2 --rt-reserve-po15.
#     And BESS=on (batteries with losses and wear, decided 2 Nov); --p1-time-limit 1800 (phase I without a solution on 8 Jan).
#   NTC_ONLY=1: only the weeks' hourly NTC caches (hourly_ntc.csv), every week at once (no chaining; 2035 runs: the
#     NTC depends on the DA profiles only, not on the previous week); NTC_FROM=<folder of such a run>: each week copies
#     its precomputed hourly_ntc.csv before it starts (the chain reuses a cache only if its inputs match exactly).
# Watch:   tail -n 2 <out>/lane-*.log ; ls <out>/*/uc_state.json | wc -l (weeks through the markets) ;
#          ls <out>/*/summary.csv | wc -l (weeks finished)
# Restart: the same command; finished weeks are skipped, a week with no summary.csv is run again.
set -u
[ $# -ge 2 ] || { sed -n '2,32p' "$0"; exit 1; }
OUT="$1"; PART="$2"
K="${PART%%/*}"; N="${PART##*/}"
[ "$K" -ge 1 ] && [ "$K" -le "$N" ] || { echo "part must be k/N with 1 <= k <= N"; exit 1; }
SCENARIO="${SCENARIO:-}"
case "$SCENARIO" in ""|trinity|necp) ;; *) echo "SCENARIO must be trinity or necp"; exit 1 ;; esac
if [ -n "$SCENARIO" ]; then
    for v in HYDRO PUMPING PUMPLIMIT; do [ -n "${!v:-}" ] && { echo "SCENARIO=$SCENARIO: leave $v out (2024 only)"; exit 1; }; done
    for v in GAS MARKUP; do [ "${!v:-off}" = "off" ] || { echo "SCENARIO=$SCENARIO: leave $v out (the scenario sets it)"; exit 1; }; done
    case " ${EXTRA:-} " in *" --offers "*|*" --unit-req "*) echo "SCENARIO=$SCENARIO: --offers / --unit-req are REE's 2024 data"; exit 1 ;; esac
fi
FROM="${FROM:-2024-01-01}"; TO="${TO:-$([ -n "$SCENARIO" ] && echo 2024-12-29 || echo 2024-12-31)}"; DAYS="${DAYS:-7}"; LANES="${LANES:-4}"; IPOPT="${IPOPT:-ma57}"
GAS="${GAS:-off}"; MARKUP="${MARKUP:-off}"
EXTRA="${EXTRA:?set EXTRA to the redispatch flags (make_config.jl), e.g. the combined December setup}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

# market options, exactly as scripts/run_markets_sequential.sh passes them
ARGS=()
[ -n "${RES:-}" ] && ARGS+=(--res-input "$RES")
[ -n "${HYDRO:-}" ] && ARGS+=(--hydro "$HYDRO")
[ -n "${PARTICIPATION:-}" ] && ARGS+=(--participation "$PARTICIPATION")
[ -n "${BALANCING:-}" ] && ARGS+=(--balancing "$BALANCING")
[ -n "${PUMPING:-}" ] && ARGS+=(--pumping "$PUMPING")
[ -n "${PUMPLIMIT:-}" ] && ARGS+=(--pump-limits "$PUMPLIMIT")
[ -n "${HYDROTOPUP:-}" ] && ARGS+=(--hydro-topup "$HYDROTOPUP")
[ -n "${IDSTARTS:-}" ] && ARGS+=(--intraday-starts "$IDSTARTS")
[ -n "${BESS:-}" ] && ARGS+=(--bess "$BESS")          # 2035: BESS=on (decisions 2026-11-02, the six 2035 main runs)
[ -n "$SCENARIO" ] && ARGS+=(--scenario "$SCENARIO")

# chunks of DAYS days in FROM .. TO (every part computes the same list)
chunks=()
start="$FROM"
while [ "$(date -d "$start" +%s)" -le "$(date -d "$TO" +%s)" ]; do
    end="$(date -d "$start +$((DAYS - 1)) day" +%Y-%m-%d)"
    [ "$(date -d "$end" +%s)" -gt "$(date -d "$TO" +%s)" ] && end="$TO"
    chunks+=("${start}_${end}")
    start="$(date -d "$end +1 day" +%Y-%m-%d)"
done
G=$(( N * LANES ))
echo "${#chunks[@]} weeks in $FROM .. $TO over $G lanes ($N nodes × $LANES); part $K/$N on $(hostname); repo $REPO"

if [ -n "${DRY:-}" ]; then
    for lane in $(seq 1 "$LANES"); do
        g=$(( (K - 1) * LANES + lane - 1 )); mine=()
        for i in "${!chunks[@]}"; do [ $(( i % G )) -eq "$g" ] && mine+=("${chunks[$i]}"); done
        echo "  lane p$K-l$lane: ${mine[*]:-none}"
    done
    echo "  market options: --gas $GAS --markup $MARKUP ${ARGS[*]:-}"; echo "  EXTRA: $EXTRA"; exit 0
fi

if [ "$K" -eq 1 ]; then
    if [ ! -f "$OUT/config_markets.toml" ]; then
        source "$REPO/scripts/solstorm_env.sh" "$IPOPT"
        ( cd "$REPO" && julia --startup-file=no scripts/make_run_config.jl "$OUT/config_markets.toml.tmp" --stage markets \
              --gas "$GAS" --markup "$MARKUP" ${ARGS[@]+"${ARGS[@]}"} ) || { echo "make_run_config FAILED"; exit 1; }
        mv "$OUT/config_markets.toml.tmp" "$OUT/config_markets.toml"
        printf "%s\n" "${chunks[@]}" > "$OUT/chunks.txt"
        echo "GAS=$GAS MARKUP=$MARKUP ${ARGS[*]:-} | EXTRA=$EXTRA" > "$OUT/settings.txt"
    fi
else
    while [ ! -f "$OUT/config_markets.toml" ]; do sleep 20; done      # part 1 writes it
fi

for lane in $(seq 1 "$LANES"); do
    g=$(( (K - 1) * LANES + lane - 1 ))
    name="p$K-l$lane"
    launcher="nohup"; command -v setsid >/dev/null 2>&1 && launcher="setsid nohup"
    $launcher bash -c '
        OUT="$1"; REPO="$2"; IPOPT="$3"; EXTRA="$4"; G="$5"; g="$6"; NTC_ONLY="$7"; NTC_FROM="$8"; shift 8; chunks=("$@")
        cd "$REPO" && source scripts/solstorm_env.sh "$IPOPT"
        for i in "${!chunks[@]}"; do
            [ $(( i % G )) -eq "$g" ] || continue
            c="${chunks[$i]}"; dir="$OUT/$c"
            if [ -n "$NTC_ONLY" ]; then                       # NTC cache only: no chaining, no markets
                from="${c%%_*}"; to="${c##*_}"; mkdir -p "$dir"
                if [ -f "$dir/hourly_ntc.csv" ] && grep -q "NTC-only run complete" "$dir/run_ntc.log" 2>/dev/null; then
                    echo "[$c] NTC done already, skipping"; continue
                fi
                t0=$(date +%s); echo "[$c] $(date +%H:%M) NTC start"
                julia redispatch_realism/make_config.jl "$dir/config_ntc.toml" --source "$OUT/config_markets.toml" $EXTRA --in-chain --ntc-only                     > "$dir/make_config_ntc.log" 2>&1 || { echo "[$c] make_config FAILED"; continue; }
                SPAIN_DAYS="$from:$to" SPAIN_CONFIG="$dir/config_ntc.toml" SPAIN_RESULTS="$dir" IPOPT_LINEAR_SOLVER="$IPOPT"                     julia --project=. run_market_chain.jl > "$dir/run_ntc.log" 2>&1
                mins=$(( ($(date +%s) - t0 + 30) / 60 ))
                if grep -q "NTC-only run complete" "$dir/run_ntc.log" && [ -f "$dir/hourly_ntc.csv" ]; then
                    echo "[$c] NTC finished in $mins min ($(( $(wc -l < "$dir/hourly_ntc.csv") - 1 )) hours)"
                else
                    echo "[$c] NTC FAILED after $mins min - see $dir/run_ntc.log"
                fi
                continue
            fi
            if [ -f "$dir/summary.csv" ]; then echo "[$c] done already, skipping"; continue; fi
            prev=""; state=""
            if [ "$i" -gt 0 ]; then
                prev="$OUT/${chunks[$((i - 1))]}"
                waited=0
                while [ ! -f "$prev/uc_state.json" ]; do
                    [ -f "$prev/FAILED" ] && { echo "[$c] previous week failed ($prev/FAILED): lane stops"; exit 1; }
                    sleep 60; waited=$((waited + 1))
                    [ "$waited" -ge 480 ] && { echo "[$c] waited 8 h for $prev/uc_state.json: lane stops"; exit 1; }
                done
                state="$prev/uc_state.json"
            fi
            from="${c%%_*}"; to="${c##*_}"
            mkdir -p "$dir"; rm -f "$dir/FAILED" "$dir/uc_state.json"
            if [ -n "$NTC_FROM" ] && [ -f "$NTC_FROM/$c/hourly_ntc.csv" ] && [ ! -f "$dir/hourly_ntc.csv" ]; then
                cp "$NTC_FROM/$c/hourly_ntc.csv" "$dir/hourly_ntc.csv"      # precomputed NTC (used only if it matches)
            fi
            t0=$(date +%s)
            echo "[$c] $(date +%H:%M) start${state:+ (state from $(basename "$prev"))}"
            julia redispatch_realism/make_config.jl "$dir/config_inchain.toml" --source "$OUT/config_markets.toml" $EXTRA --in-chain \
                > "$dir/make_config.log" 2>&1 || { echo "[$c] make_config FAILED"; touch "$dir/FAILED"; exit 1; }
            SPAIN_DAYS="$from:$to" SPAIN_CONFIG="$dir/config_inchain.toml" SPAIN_RESULTS="$dir" SPAIN_UC_STATE_IN="$state" \
                IPOPT_LINEAR_SOLVER="$IPOPT" julia --project=. run_market_chain.jl > "$dir/run.log" 2>&1
            code=$?; mins=$(( ($(date +%s) - t0 + 30) / 60 ))
            if [ "$code" -eq 0 ] && [ -f "$dir/summary.csv" ]; then
                echo "[$c] finished in $mins min ($(grep -o "Solved [0-9]* / [0-9]* hours" "$dir/run.log" | tail -n1))"
            else
                echo "[$c] FAILED (exit code $code) after $mins min - see $dir/run.log"
                [ -f "$dir/uc_state.json" ] || touch "$dir/FAILED"     # past the markets, the chain can go on
            fi
        done
        echo "lane done"
    ' _ "$OUT" "$REPO" "$IPOPT" "$EXTRA" "$G" "$g" "${NTC_ONLY:-}" "${NTC_FROM:-}" "${chunks[@]}" > "$OUT/lane-$name.log" 2>&1 < /dev/null &
    echo "  $name (pid $!)"
done
sleep 2
echo "lanes started on $(hostname)"
