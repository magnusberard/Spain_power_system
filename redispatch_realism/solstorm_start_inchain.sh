#!/usr/bin/env bash
# Start one week (or any day range) of the whole chain with phase I inside it (level 1): the market
# stages run with the source run's market settings, phase I's unit commitment between DA and ID2, the
# AC check after the markets, then real time — one background process, days in order. Run on a compute
# node (never the login node), from the repo root, on branch redispatch-realism:
#
#     FROM=2024-12-02 TO=2024-12-08 redispatch_realism/solstorm_start_inchain.sh <source config> <out>
#
#   <source config>  a market config of the run whose settings to copy, e.g. a chunk's
#                    config_used_market.toml of Lars Erik's run 4
#   <out>            new folder for this run
#   options          IPOPT (default ma57), EXTRA = more make_config flags (default: the realism set
#                    --ac-check --hydro-budget --dedup-ab --sync-q 0.15 --no-rt-zones --down-only --unit-req)
#
# Watch:  tail -n 5 <out>/run.log   (buffered: mostly Gurobi lines until the end); ls <out>/*.csv
set -eu
[ $# -ge 2 ] || { sed -n '2,17p' "$0"; exit 1; }
SRCCFG="$1"; OUT="$2"
: "${FROM:?set FROM=YYYY-MM-DD}"; : "${TO:?set TO=YYYY-MM-DD}"
EXTRA="${EXTRA:---ac-check --hydro-budget --dedup-ab --sync-q 0.15 --no-rt-zones --down-only --unit-req}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$SRCCFG" ] || { echo "source config $SRCCFG not found"; exit 1; }
mkdir -p "$OUT"
if command -v module >/dev/null 2>&1 || [ -n "${MODULESHOME:-}" ]; then
    source "$REPO/scripts/solstorm_env.sh" "${IPOPT:-ma57}"
fi
( cd "$REPO" && julia redispatch_realism/make_config.jl "$OUT/config_inchain.toml" --source "$SRCCFG" $EXTRA --in-chain )
launcher="nohup"; command -v setsid >/dev/null 2>&1 && launcher="setsid nohup"
( cd "$REPO" && SPAIN_DAYS="$FROM:$TO" SPAIN_CONFIG="$OUT/config_inchain.toml" SPAIN_RESULTS="$OUT" \
    IPOPT_LINEAR_SOLVER="${IPOPT:-ma57}" $launcher julia --project=. run_market_chain.jl > "$OUT/run.log" 2>&1 < /dev/null & )
sleep 2
echo "started $FROM .. $TO on $(hostname) -> $OUT (in-chain; log $OUT/run.log)"
