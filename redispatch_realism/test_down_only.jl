# Test for [redispatch].down_only on the real network: with a redispatch anchor, nuclear and CHP blocks
# may go down (pmin < schedule = pmax), not up; without the switch, and in market builds (no anchor),
# they stay frozen.  No solver; ~1 min.
#
#     julia --project redispatch_realism/test_down_only.jl
using Test
include(joinpath(@__DIR__, "..", "data_preparation.jl"))

n0 = prepare_network().network                                       # find nuclear units and their size
nuc = [g for (_, g) in n0["gen"] if g["fuel"] == "Nuclear"]
sched = Dict(g["name"] => 0.9 * g["installed_mw"] for g in nuc)     # schedule at 90 %
build(on) = (DOWN_ONLY[] = on ? Set(["Nuclear", "CHP", "CHP_Waste"]) : Set{String}();
             r = prepare_network(da_dispatch = sched, frozen_fuels = ["Nuclear"]).network; DOWN_ONLY[] = Set{String}(); r)
@testset "down-only units" begin
    off, on = build(false), build(true)
    byname(n) = Dict(g["name"] => g for (_, g) in n["gen"])
    a, b = byname(off), byname(on)
    for g in nuc
        k = g["name"]
        @test a[k]["pmin"] ≈ a[k]["pmax"]                                   # frozen without the switch
        @test b[k]["pmax"] ≈ 0.9 * g["installed_mw"] / 100                  # never above the schedule
        @test b[k]["pmin"] ≈ 0.5 * g["installed_mw"] / 100                  # down to 50 % of installed
    end
    DOWN_ONLY[] = Set(["Nuclear"])
    m = prepare_network(nuclear_da_dispatch = sched).network                # a market build: no anchor
    DOWN_ONLY[] = Set{String}()
    for (_, g) in m["gen"]
        g["fuel"] == "Nuclear" && haskey(sched, g["name"]) && @test g["pmin"] ≈ g["pmax"]
    end
end
