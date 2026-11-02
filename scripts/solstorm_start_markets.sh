#!/usr/bin/env bash
# Start step 1 of a split run on NTNU's Solstorm cluster: the market stages for
# the whole period, chunk after chunk in order (scripts/run_markets_sequential.sh),
# as one background process that keeps running after you log out (setsid +
# nohup; the compute nodes have no `screen`). Run it on a compute node, from the
# repo root:
#
#     GAS=on IPOPT=ma57 scripts/solstorm_start_markets.sh /storage/users/$USER/results/2024_gas
#
#   argument : parent folder for the chunk folders (<folder>/<from>_<to>/)
#   optional : FROM (2024-01-01), TO (2024-12-31), DAYS (7), GAS (off), MARKUP (off), HYDRO, RES,
#              PARTICIPATION (active/measured/passive), BALANCING (all/qualified), PUMPING (removed), PUMPLIMIT (on)
#              (accepted/offered, default: as in config.toml) and IPOPT (mumps;
#              ma57 once HSL is set up), as environment variables in front
#
# Then start step 2 on other nodes right away (it waits for each chunk):
#     scripts/solstorm_start_redispatch.sh <folder> k/N
#
# Watch:   tail -n 5 <folder>/markets.log
# Stop:    pkill -u $USER -f run_markets_sequential.sh; pkill -u $USER julia   (this node only)
# A rerun with the same folder skips the chunks that are done (market_done).
set -eu

[ $# -ge 1 ] || { sed -n '2,20p' "$0"; exit 1; }
OUT="$1"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"

setsid nohup bash -lc "cd '$REPO' && source scripts/solstorm_env.sh '${IPOPT:-mumps}' \
    && FROM='${FROM:-2024-01-01}' TO='${TO:-2024-12-31}' DAYS='${DAYS:-7}' GAS='${GAS:-off}' MARKUP='${MARKUP:-off}' HYDRO='${HYDRO:-}' RES='${RES:-}' \
       PARTICIPATION='${PARTICIPATION:-}' BALANCING='${BALANCING:-}' PUMPING='${PUMPING:-}' PUMPLIMIT='${PUMPLIMIT:-}' \
       scripts/run_markets_sequential.sh '$OUT'" \
    >> "$OUT/markets.log" 2>&1 < /dev/null &
echo "markets chain started on $(hostname) (pid $!); log: $OUT/markets.log"
