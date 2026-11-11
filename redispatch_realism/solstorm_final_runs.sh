#!/usr/bin/env bash
# The final year runs (11 Nov 2026), started from the login node with no editing: it finds free compute nodes itself
# (cores minus load >= NEED_CORES, available memory >= NEED_GB), gives each run its own node and starts it there with
# redispatch_realism/solstorm_start_year_pipeline.sh, in this repo copy (the ly9b copy: border ties over Data/).
#
#   bash redispatch_realism/solstorm_final_runs.sh plan1     show which node would get which run (starts nothing)
#   bash redispatch_realism/solstorm_final_runs.sh start1    2024 Partial + Passive, NTC precompute for Trinity + NECP
#   bash redispatch_realism/solstorm_final_runs.sh plan2     the six 2035 runs (needs the NTC of their scenario: 52/52)
#   bash redispatch_realism/solstorm_final_runs.sh start2
#   bash redispatch_realism/solstorm_final_runs.sh status    progress of every run
#
# A run whose folder already has lane logs is never started twice. Node choices go to $RES/final_runs_nodes.txt.
# NODES (default compute-5-1 .. compute-5-40), NEED_CORES (8), NEED_GB (30) can be set in front.
set -u
RES="${RES:-/storage/users/magnurbe/results}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
NEED_CORES="${NEED_CORES:-8}"; NEED_GB="${NEED_GB:-30}"
NODES="${NODES:-$(for i in $(seq 1 40); do printf "compute-5-%d " "$i"; done)}"

E24="--ac-check --hydro-budget --dedup-ab --sync-q 0.15 --no-rt-zones --down-only --zone-rule --sweep-a --offers redispatch_realism/data/phase2_offers_2024_tail.csv --rt-reserve-e2"
E35="--ac-check --hydro-budget --dedup-ab --sync-q 0.15 --no-rt-zones --down-only --zone-rule --sweep-a --offer-rule redispatch_realism/data/phase2_offer_rule.csv --rt-reserve-e2 --rt-reserve-po15 --p1-time-limit 1800"
M24="GAS=on MARKUP=on HYDRO=aligned_rc_observed RES=offered PUMPING=removed PUMPLIMIT=on IDSTARTS=on HYDROTOPUP=on BALANCING=qualified"
M35="BESS=on IDSTARTS=on HYDROTOPUP=on BALANCING=qualified"

# name | environment in front of the runner | EXTRA | out folder
STAGE1=(
  "2024 Partial|$M24 PARTICIPATION=measured_all LANES=6|$E24|$RES/y24rule_part"
  "2024 Passive|$M24 PARTICIPATION=passive LANES=6|$E24|$RES/y24rule_pas"
  "NTC Trinity|NTC_ONLY=1 SCENARIO=trinity $M35 LANES=8|$E35|$RES/ntc35tri"
  "NTC NECP|NTC_ONLY=1 SCENARIO=necp $M35 LANES=8|$E35|$RES/ntc35necp"
)
STAGE2=(
  "2035 Trinity Active|NTC_FROM=$RES/ntc35tri SCENARIO=trinity $M35 LANES=3|$E35|$RES/y35tri_act"
  "2035 Trinity Partial|NTC_FROM=$RES/ntc35tri SCENARIO=trinity $M35 PARTICIPATION=measured_all LANES=3|$E35|$RES/y35tri_part"
  "2035 Trinity Passive|NTC_FROM=$RES/ntc35tri SCENARIO=trinity $M35 PARTICIPATION=passive LANES=3|$E35|$RES/y35tri_pas"
  "2035 NECP Active|NTC_FROM=$RES/ntc35necp SCENARIO=necp $M35 LANES=3|$E35|$RES/y35necp_act"
  "2035 NECP Partial|NTC_FROM=$RES/ntc35necp SCENARIO=necp $M35 PARTICIPATION=measured_all LANES=3|$E35|$RES/y35necp_part"
  "2035 NECP Passive|NTC_FROM=$RES/ntc35necp SCENARIO=necp $M35 PARTICIPATION=passive LANES=3|$E35|$RES/y35necp_pas"
)

free_nodes() {   # "node free_cores avail_gb", most free first, only nodes that meet the needs
    for n in $NODES; do
        ssh -o BatchMode=yes -o ConnectTimeout=3 "$n" \
            'echo "$(hostname -s) $(nproc) $(cut -d" " -f1 /proc/loadavg) $(free -g | awk "/Mem/{print \$7}")"' 2>/dev/null
    done | awk -v c="$NEED_CORES" -v g="$NEED_GB" '{f = $2 - $3; if (f >= c && $4 >= g) printf "%s %d %d\n", $1, f, $4}' | sort -k2,2nr
}

ntc_count() { grep -l "NTC-only run complete" "$1"/*/run_ntc.log 2>/dev/null | wc -l; }   # weeks whose NTC finished
ntc_done() { [ "$(ntc_count "$1")" -ge 52 ]; }

run_stage() {   # $1 = plan|start, rest = job lines
    local mode="$1"; shift
    local jobs=() j
    for j in "$@"; do
        IFS='|' read -r name env extra out <<< "$j"
        if ls "$out"/lane-*.log >/dev/null 2>&1; then echo "  $name: already started ($out), skipped"; continue; fi
        if [[ "$env" == *NTC_FROM=* ]]; then
            src="${env#*NTC_FROM=}"; src="${src%% *}"
            ntc_done "$src" || { echo "  $name: NTC in $src not complete yet ($(ntc_count "$src")/52), skipped"; continue; }
        fi
        jobs+=("$j")
    done
    [ "${#jobs[@]}" -gt 0 ] || { echo "nothing to start"; return 0; }
    echo "checking nodes (need $NEED_CORES free cores and $NEED_GB GB available) ..."
    mapfile -t nodes < <(free_nodes)
    echo "  ${#nodes[@]} suitable node(s): $(printf "%s " "${nodes[@]%% *}")"
    [ "${#nodes[@]}" -ge "${#jobs[@]}" ] || echo "  WARNING: ${#jobs[@]} runs but only ${#nodes[@]} suitable nodes; the rest are not started (run again later)"
    local i=0
    for j in "${jobs[@]}"; do
        IFS='|' read -r name env extra out <<< "$j"
        [ "$i" -lt "${#nodes[@]}" ] || { echo "  $name: no free node left, not started"; continue; }
        node="${nodes[$i]%% *}"; i=$((i + 1))
        echo "  $name -> $node   ($out)"
        [ "$mode" = start ] || continue
        ssh -o BatchMode=yes "$node" "cd '$REPO' && $env EXTRA='$extra' bash redispatch_realism/solstorm_start_year_pipeline.sh '$out' 1/1" \
            > "$RES/final_runs_start_$(basename "$out").log" 2>&1
        if ls "$out"/lane-*.log >/dev/null 2>&1; then
            echo "$(date '+%Y-%m-%d %H:%M') $name $node $out" >> "$RES/final_runs_nodes.txt"; echo "     started"
        else
            echo "     NOT started - see $RES/final_runs_start_$(basename "$out").log"
        fi
    done
}

status() {
    for j in "${STAGE1[@]}" "${STAGE2[@]}"; do
        IFS='|' read -r name env extra out <<< "$j"
        if ! ls "$out"/lane-*.log >/dev/null 2>&1; then printf "%-22s not started\n" "$name"; continue; fi
        if [[ "$name" == NTC* ]]; then
            printf "%-22s NTC %s/52 | failed %s\n" "$name" "$(ntc_count "$out")" "$(grep -h "NTC FAILED" "$out"/lane-*.log 2>/dev/null | wc -l)"
        else
            n=53; [[ "$name" == 2035* ]] && n=52
            printf "%-22s markets %s/%s | done %s/%s | failed %s | lanes finished %s/%s\n" "$name" \
                "$(ls "$out"/*/uc_state.json 2>/dev/null | wc -l)" "$n" "$(ls "$out"/*/summary.csv 2>/dev/null | wc -l)" "$n" \
                "$(ls "$out"/*/FAILED 2>/dev/null | wc -l)" "$(grep -l "lane done" "$out"/lane-*.log 2>/dev/null | wc -l)" "$(ls "$out"/lane-*.log | wc -l)"
        fi
    done
    [ -f "$RES/final_runs_nodes.txt" ] && { echo "nodes:"; cat "$RES/final_runs_nodes.txt"; }
}

case "${1:-}" in
    plan1)  run_stage plan  "${STAGE1[@]}" ;;
    start1) run_stage start "${STAGE1[@]}" ;;
    plan2)  run_stage plan  "${STAGE2[@]}" ;;
    start2) run_stage start "${STAGE2[@]}" ;;
    status) status ;;
    *) sed -n '2,15p' "$0" ;;
esac
