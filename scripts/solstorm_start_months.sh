#!/usr/bin/env bash
# Start several 2024 months at once on one Solstorm compute node, each in its
# own detached screen session (m01, m02, ...), so they keep running after you
# log out. Run it on the compute node, from the repo root:
#
#     scripts/solstorm_start_months.sh offered /storage/users/$USER/results/2024_offered 01 02 03
#
#   1st argument : [run].res_input for these runs ("accepted" or "offered");
#                  the script writes scripts/config_<res_input>.toml (a copy of
#                  config.toml with that setting; git ignores it)
#   2nd argument : parent folder for the month folders (<folder>/2024-01/ ...)
#   then         : the months to run (01 .. 12); December stops on the 29th,
#                  the last day with inputs
#
# Optional: IPOPT=ma57 scripts/solstorm_start_months.sh ...  (default mumps).
# Watch a month:  screen -r m01   (leave again with Ctrl+A, then D)
# List them:      screen -ls
# Progress:       tail -f <folder>/2024-01/run.log
set -eu

[ $# -ge 3 ] || { sed -n '2,20p' "$0"; exit 1; }
RES="$1"; OUT="$2"; shift 2
case "$RES" in accepted|offered) ;; *) echo "res_input must be accepted or offered"; exit 1 ;; esac

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$REPO/scripts/config_$RES.toml"
sed "s/^res_input = \"[a-z]*\"/res_input = \"$RES\"/" "$REPO/config.toml" > "$CFG"
grep -q "^res_input = \"$RES\"" "$CFG" || { echo "could not set res_input in $CFG"; exit 1; }
mkdir -p "$OUT"

for m in "$@"; do
    from="2024-$m-01"
    to="$(date -d "$from +1 month -1 day" +%Y-%m-%d)"
    [ "$m" = "12" ] && to="2024-12-29"
    # bash -l: a login shell, so the `module` command is defined
    screen -dmS "m$m" bash -lc "cd '$REPO' && source scripts/solstorm_env.sh '${IPOPT:-mumps}' \
        && SPAIN_CONFIG='$CFG' OUT_ROOT='$OUT' scripts/run_2024_by_month.sh $from $to; exec bash"
    echo "started m$m: $from .. $to ($RES) -> $OUT/2024-$m/run.log"
done
echo "screen sessions on $(hostname):"
screen -ls | grep -E "\.m[0-9]{2}" || true
