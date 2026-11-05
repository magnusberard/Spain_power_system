# Test for [redispatch.bids].offers_rule (build_offer_rule.py): without REE's offers a unit gets its technology's rule
# curve at the hour's day-ahead price (price = ratio × p_DA, highest first, shares summing to 1); pumped storage, real
# time (no key) and an unknown technology get none; the cost follows rd_down_cost_eur. No solver; seconds.
#
#     julia --project redispatch_realism/test_offer_rule.jl
using Test, Printf, JuMP, CSV, DataFrames
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))
load_rd_offer_rule!(joinpath(@__DIR__, "data", "phase2_offer_rule.csv"))
rule = CSV.read(joinpath(@__DIR__, "data", "phase2_offer_rule.csv"), DataFrame)
unit(f, t) = Dict{String,Any}("name" => "X", "fuel" => f, "technology" => t)
key = ("2035-04-10", 12)
@testset "phase II offer rule" begin
    w = rd_down_curve(unit("Wind", "Onshore"), key, 100.0)
    @test w !== nothing
    @test sum(first.(w)) ≈ 1.0 atol = 1e-6
    @test issorted(last.(w); rev = true)                                   # highest buy-back price first
    r = rule[rule.technology .== "Wind:Onshore", :]
    @test maximum(last.(w)) ≈ 100 * maximum(r.ratio)
    @test rd_down_curve(unit("Hydro", "pumped_storage"), key, 100.0) === nothing
    @test rd_down_curve(unit("Wind", "Onshore"), nothing, 100.0) === nothing     # real time: no key
    @test rd_down_curve(unit("Wind", "Onshore"), key) === nothing                # no p_DA given
    @test rd_down_curve(unit("Unobtainium", "X"), key, 100.0) === nothing
    @test all(p >= 0 for (_, p) in rd_down_curve(unit("Wind", "Onshore"), key, -20.0))   # negative p_DA: no negative price
    g = unit("Wind", "Onshore")
    c = rd_down_curve(g, key, 100.0)
    first_share, first_price = c[1]
    @test rd_down_cost_eur(g, first_share * 50.0, 50.0, 100.0, 90.0, key) ≈ first_share * 50.0 * (100 - first_price)
end
