# Test for [redispatch].startups.enforce_min_load (su_apply_min_load!): in an AC stage an off CCGT/coal candidate
# gives 0 MW unless started; with min_load_floor_running a running one stays at or above its minimum load; small units, non-candidates and the
# switch off are untouched; a start (su_commit!) undoes the hold. No solver; seconds.
#
#     julia --project redispatch_realism/test_min_load_rt.jl
using Test, Printf, JuMP, PowerModels, CSV, DataFrames
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))

su(on; floor = true) = (enforce_min_load = on, min_load_floor_running = floor, candidates = Set(["gas:combined_cycle", "coal"]), candidate_min_mw = 100.0,
          gas_min_load_1x1 = 0.39, gas_min_load_2x1 = 0.18, gas_two_by_one_mw = 700.0,
          gas_wear_eur_per_mw = 57.4, gas_start_fuel = 1.5, gas_eta = 0.55,
          coal_large_mw = 300.0, coal_min_load_large = 0.4, coal_min_load_small = 0.4,
          coal_wear_large = 110.0, coal_wear_small = 110.0, coal_start_fuel = 3.0, coal_eta = 0.36)
unit(name, fuel, tech, mw; on) = Dict{String,Any}("name" => name, "fuel" => fuel, "technology" => tech,
    "installed_mw" => mw, "pmax" => mw / BASEMVA, "pmin" => 0.0, "pg" => (on ? 0.6 : 0.0) * mw / BASEMVA,
    "qmax" => on ? mw / BASEMVA : 0.0, "qmin" => on ? -mw / BASEMVA : 0.0, "cost" => [70.0 * BASEMVA, 0.0])
net() = Dict{String,Any}("gen" => Dict(
    "1" => unit("CC_OFF", "Gas", "Combined_cycle", 400.0; on = false),
    "2" => unit("CC_ON", "Gas", "Combined_cycle", 400.0; on = true),
    "3" => unit("CC_2X1", "Gas", "Combined_cycle", 800.0; on = true),
    "4" => unit("COAL_OFF", "Coal", "Coal", 350.0; on = false),
    "5" => unit("CC_SMALL_OFF", "Gas", "Combined_cycle", 50.0; on = false),   # below candidate_min_mw
    "6" => unit("WIND", "Wind", "Onshore", 200.0; on = true)))

@testset "minimum load in AC stages" begin
    n = net(); g = Dict(x["name"] => x for (_, x) in n["gen"])
    @test su_apply_min_load!(n, su(true)) == (2, 2)
    @test g["CC_OFF"]["pmax"] == 0.0 && g["CC_OFF"]["pg"] == 0.0               # off: no output without a start
    @test g["COAL_OFF"]["pmax"] == 0.0
    @test g["CC_ON"]["pmin"] ≈ 0.39 * 4.0                                      # running 1x1: ≥ 39 %
    @test g["CC_2X1"]["pmin"] ≈ 0.18 * 8.0                                     # running 2x1: ≥ 18 %
    @test g["CC_SMALL_OFF"]["pmax"] ≈ 0.5                                      # not a candidate: untouched
    @test g["WIND"]["pmin"] == 0.0
    mw, _ = su_commit!(su(true), g["CC_OFF"])                                  # a start undoes the hold
    @test g["CC_OFF"]["pmax"] ≈ 4.0 && g["CC_OFF"]["pmin"] ≈ 0.39 * 4.0 && mw ≈ 156.0
    n2 = net()
    @test su_apply_min_load!(n2, su(false)) == (0, 0)                          # switch off: nothing changes
    @test all(x["pmin"] == 0.0 for (_, x) in n2["gen"])
    n3 = net(); g3 = Dict(x["name"] => x for (_, x) in n3["gen"])
    @test su_apply_min_load!(n3, su(true; floor = false)) == (2, 0)           # default: off held, running not floored
    @test g3["CC_OFF"]["pmax"] == 0.0 && g3["CC_ON"]["pmin"] == 0.0
end
