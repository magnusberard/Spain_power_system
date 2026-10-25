# Test for [generators].sync_q_frac on the real network: synchronous units' reactive box shrinks to
# ±frac × installed MW, wind/solar and the full-circle default are untouched.  No solver; ~40 s.
#
#     julia --project redispatch_realism/test_syncq.jl
using Test
include(joinpath(@__DIR__, "..", "data_preparation.jl"))

@testset "synchronous reactive band" begin
    SYNC_Q_FRAC[] = 0.0
    n0 = prepare_network().network
    SYNC_Q_FRAC[] = 0.15
    n1 = prepare_network().network
    SYNC_Q_FRAC[] = 0.0
    byname(n) = Dict(g["name"] => g for (_, g) in n["gen"])
    g0, g1 = byname(n0), byname(n1)
    sync = [k for (k, g) in g1 if get(g, "fuel", "") in ("Gas", "Coal", "Nuclear", "Hydro") && get(g, "installed_mw", 0.0) > 0]
    res  = [k for (k, g) in g1 if get(g, "fuel", "") in ("Wind", "Solar")]
    @test !isempty(sync) && !isempty(res)
    @test all(g1[k]["qmax"] <= 0.15 * g1[k]["installed_mw"] / 100 + 1e-9 for k in sync)
    @test all(g1[k]["qmin"] >= -0.15 * g1[k]["installed_mw"] / 100 - 1e-9 for k in sync)
    @test all(g1[k]["qmax"] ≈ g0[k]["qmax"] for k in res)                       # renewables untouched
    big = argmax(k -> g0[k]["installed_mw"], filter(k -> g0[k]["fuel"] == "Gas", sync))
    @info "largest gas unit $(big): installed $(g0[big]["installed_mw"]) MW, Q box ±$(round(g0[big]["qmax"] * 100)) → ±$(round(g1[big]["qmax"] * 100)) Mvar"
    @test g0[big]["qmax"] > 5 * g1[big]["qmax"]                                  # default is the wide circle
end
