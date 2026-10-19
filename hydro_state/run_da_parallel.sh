#!/usr/bin/env bash
# Day-ahead-only 2024 run, split over parallel processes — the quick price test.
#
#   bash hydro_state/run_da_parallel.sh <chain config> <out folder> [n_procs] [first] [last]
#
# Writes a day-ahead-only copy of <chain config> (ID2, ID3, CID, balancing and the redispatch
# switched off, res_input = "offered" to match the published "2024, offered solar/wind" run),
# then runs [first, last] (default 2024-01-01 .. 2024-12-29) in n_procs contiguous day ranges at
# once. Days are independent in the 2024 path (each reads its start volume from the volume
# file), so the split does not change results. Parts land in <out>/part_<k>/market_prices.csv;
# hydro_state/compare_prices.py reads them all.
set -euo pipefail
cfg_in=$1; out=$2; n=${3:-7}; first=${4:-2024-01-01}; last=${5:-2024-12-29}
mkdir -p "$out"
cfg_da="$out/config_da.toml"
julia -e '
using TOML
c = TOML.parsefile(ARGS[1])
c["run"]["res_input"] = "offered"
for s in ("id2", "id3", "cid", "balancing", "redispatch"); c[s]["enabled"] = false; end
open(io -> TOML.print(io, c), ARGS[2], "w")' "$cfg_in" "$cfg_da"

days=$(julia -e 'using Dates; for d in Date(ARGS[1]):Day(1):Date(ARGS[2]); println(d); end' "$first" "$last")
total=$(echo "$days" | wc -l)
per=$(( (total + n - 1) / n ))
k=0
while [ $(( k * per )) -lt "$total" ]; do
  a=$(echo "$days" | sed -n "$(( k * per + 1 ))p")
  b=$(echo "$days" | sed -n "$(( (k + 1) * per < total ? (k + 1) * per : total ))p")
  SPAIN_CONFIG="$cfg_da" SPAIN_DAYS="$a:$b" SPAIN_RESULTS="$out/part_$k" \
    julia --project=. run_market_chain.jl > "$out/part_$k.log" 2>&1 &
  echo "part $k: $a .. $b"
  k=$(( k + 1 ))
done
wait
echo "done: $k parts in $out"
