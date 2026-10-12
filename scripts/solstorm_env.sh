# Environment for running the model on NTNU's Solstorm cluster. Source it on a
# compute node (never run models on the login node), from the repo root:
#
#     source scripts/solstorm_env.sh            # Ipopt with MUMPS (no licence needed)
#     source scripts/solstorm_env.sh ma57       # Ipopt with HSL, once HSL_jll is set up
#
# Why each line is here (found setting the cluster up, 2026-10-12):
#   - GCCcore: Julia's bundled 7z needs a newer libstdc++ (CXXABI_1.3.8/1.3.9)
#     than the nodes' system one; without it Pkg cannot unpack downloads.
#   - JULIA_DEPOT_PATH is set AFTER `module load Julia`, which resets it to ":".
#     The trailing ":" keeps Julia's own depots (precompiled stdlibs) after ours;
#     packages go to /storage, not $HOME.
#   - gurobi/13.0 matches Gurobi_jll 13.0.2 and sets GRB_LICENSE_FILE (the
#     cluster's token server).
#   - HSL (ma57) is licensed and is not installed by Pkg.instantiate; until its
#     package is copied over and `Pkg.develop`ed, use MUMPS.
#
# First time only, after sourcing:
#     julia --project=. -e 'import Pkg; Pkg.instantiate(); Pkg.precompile()'
# (HSL_jll failing to precompile is expected with MUMPS.)

module load Julia/1.12.2 gurobi/13.0 GCCcore/12.3.0
export JULIA_DEPOT_PATH="/storage/users/$USER/julia_depot:"
export TMPDIR="/storage/users/$USER/tmp"
mkdir -p "/storage/users/$USER/julia_depot" "$TMPDIR"
export IPOPT_LINEAR_SOLVER="${1:-mumps}"

echo "Solstorm env   : Julia $(julia --version | cut -d' ' -f3), Ipopt solver $IPOPT_LINEAR_SOLVER, depot $JULIA_DEPOT_PATH"
