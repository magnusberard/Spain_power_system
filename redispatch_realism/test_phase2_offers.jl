# Test for step 4 (phase II from REE's buy-back offers, redispatch_objective.jl): the curves load, a unit takes its
# own curve, else its technology's, pumped storage none; the reported cost walks the curve with the refund capped at
# p_DA; and in a small LP turning-down follows REE's price order (highest buy-back price first). HiGHS; seconds.
#
#     julia --project redispatch_realism/test_phase2_offers.jl
using Test, JuMP, HiGHS, CSV, DataFrames, Printf
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))

load_rd_offers!(get(ENV, "OFFERS_FILE", "redispatch_realism/data/phase2_offers_dec.csv"), Dict())
key = ("2024-12-02", 3)
@testset "phase II offers" begin
    @test !isempty(RD_OFFERS)
    own  = Dict("name" => "G0058", "fuel" => "Coal", "technology" => "Coal")             # Aboño 2: own REE offers
    wind = Dict("name" => "W_TEST", "fuel" => "Wind", "technology" => "Onshore")          # no own offers: pooled
    pump = Dict("name" => "G0104", "fuel" => "Hydro", "technology" => "pumped_storage")   # kept out
    @test rd_down_curve(own, key) !== nothing
    cw = rd_down_curve(wind, key)
    @test cw !== nothing && isapprox(sum(first, cw), 1.0; atol = 1e-3)
    @test issorted(last.(cw); rev = true)                                                 # highest price first
    @test rd_down_curve(pump, key) === nothing
    @test rd_down_curve(wind, nothing) === nothing                                        # real time: no key
    # reported cost: by hand on a two-segment curve, refund capped at p_DA
    RD_OFFERS[("2099-01-01", 0, "u_test")] = [(0.5, 150.0), (0.5, 20.0)]
    g = Dict("name" => "U_TEST", "fuel" => "Gas", "technology" => "Combined_cycle")
    k2 = ("2099-01-01", 0)
    @test rd_down_cost_eur(g, 50.0, 100.0, 100.0, 90.0, k2) ≈ 0.0                    # 50 MW at min(150, 100): free
    @test rd_down_cost_eur(g, 80.0, 100.0, 100.0, 90.0, k2) ≈ 30 * (100 - 20)        # then 30 MW at 20 €/MWh
    @test rd_down_cost_eur(g, 120.0, 100.0, 100.0, 90.0, k2) ≈ 50 * 0 + 50 * 80 + 20 * 100   # beyond: full p_DA
    @test rd_down_cost_eur(g, 10.0, 100.0, 100.0, 90.0, nothing) ≈ 10 * (100 - 90)    # no key: the bids
    # LP: 60 MW must come down from two units of 100 MW each; A buys back at 80 (cheap to turn down), B at 0
    RD_OFFERS[("2099-01-01", 0, "a_test")] = [(1.0, 80.0)]
    RD_OFFERS[("2099-01-01", 0, "b_test")] = [(1.0, 0.0)]
    m = Model(HiGHS.Optimizer); set_silent(m)
    obj = zero(AffExpr); dns = VariableRef[]
    for nm in ("A_TEST", "B_TEST")
        gg = Dict("name" => nm, "fuel" => "Gas", "technology" => "Combined_cycle")
        dn = @variable(m, lower_bound = 0.0); push!(dns, dn)
        rd_add_down_cost!(m, obj, dn, gg, 1.0, 100.0, 90.0, 5.0, k2)                      # schedule 100 MW = 1 pu
    end
    @constraint(m, sum(dns) == 0.6)
    @objective(m, Min, obj); optimize!(m)
    @test value(dns[1]) ≈ 0.6 atol = 1e-6                                                 # all from A (REE's order)
    @test value(dns[2]) ≈ 0.0 atol = 1e-6
    @test objective_value(m) ≈ 60 * (100 - 80 + 5) atol = 1e-3
end
