# Tests for the hydro top-up ([bellman].hydro_budget_topup): a stage that needs the
# slack is solved again with the day's hydro budget raised by the slack's MWh.
# The re-solve itself is in run_market_chain.jl; here the same two solves on the
# real fleet (HiGHS).
#     julia --project=. scripts/test_shortage.jl
using Test, CSV, DataFrames, JuMP, HiGHS
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
include(joinpath(@__DIR__, "..", "da.jl"))

resv_ids(nets) = sort([parse(Int, k) for (k, g) in nets[1].gens
                       if g["fuel"] == "Hydro" && lowercase(g["technology"]) == "reservoir"])

@testset "helpers" begin
    s = Dict(1 => Dict("SLACK" => 100.0, "G1" => 5.0), 2 => Dict("G1" => 5.0), 3 => Dict("SLACK" => 50.0))
    @test slack_mwh(s, nothing) == 150.0
    @test slack_mwh(s, Set([2, 3])) == 50.0                 # only the tradable hours count
    @test slack_mwh(s, 3:5) == 50.0                         # hours outside the schedule are skipped
    @test slack_mwh(Dict{Int,Dict{String,Float64}}(), nothing) == 0.0
    @test topped_budget((budget = 1000.0,), 250.0) == 1250.0
    @test topped_budget((cuts = [],), 250.0) === nothing     # no budget: stays without one
end

@testset "hydro top-up" begin
    # a load the fleet without reservoir hydro cannot meet (no sun, no wind), so
    # hydro must cover the rest; water dearer than every other offer, so hydro
    # only covers what nothing else can
    probe = prepare_network(30000.0, 0.0, 0.0)
    nonhydro = sum(Float64(g["pmax"]) * BASEMVA for g in values(probe.gens)
                   if !(g["fuel"] in ("Slack", "LoadShed")) && !haskey(g, "energy_mwh") &&
                      !(g["fuel"] == "Hydro" && lowercase(g["technology"]) == "reservoir"))
    top = maximum(Float64(g["cost"][1]) / BASEMVA for g in values(probe.gens)
                  if !(g["fuel"] in ("Slack", "LoadShed")))
    wv  = round(top + 10.0)
    nets = [prepare_network(nonhydro + 3000.0, 0.0, 0.0; hydro_reservoir_cost = wv) for _ in 1:24]
    ids = resv_ids(nets)
    @test sum(Float64(nets[1].gens[string(k)]["pmax"]) * BASEMVA for k in ids) > 3000.0
    # a full reservoir (1 TWh) so only the budget limits hydro
    solve(budget) = solve_da(nets, ids, [], 1.0e6, HiGHS.Optimizer; hydro_budget_mwh = budget)

    # budget 24 GWh, need 72: 48 GWh short, the slack covers it at 1000 EUR/MWh
    first_solve = solve(24_000.0)
    short = slack_mwh(first_solve.sched, nothing)
    @test first_solve.status == "OPTIMAL" && isapprox(short, 48_000.0; rtol = 0.01)
    @test all(isapprox(p, 1000.0; atol = 1.0) for p in values(first_solve.es_price))
    # top-up: the budget raised by exactly that, solved again: no slack, the
    # price falls to the water's own cost
    topped = solve(topped_budget((budget = 24_000.0,), short))
    @test topped.status == "OPTIMAL" && slack_mwh(topped.sched, nothing) < 1.0
    @test all(isapprox(p, wv; atol = 1.0) for p in values(topped.es_price))

    # one short hour (as on 20 May 2024): 1.5 GW missing at 18 h prices every
    # hour of the day at 1000 through the budget; the top-up gives just that hour's
    # MWh and every price falls back
    nets2 = [prepare_network(nonhydro + (h == 18 ? 3000.0 : 500.0), 0.0, 0.0; hydro_reservoir_cost = wv) for h in 1:24]
    ids2 = resv_ids(nets2)
    solve2(b) = solve_da(nets2, ids2, [], 1.0e6, HiGHS.Optimizer; hydro_budget_mwh = b)
    a  = solve2(23 * 500.0 + 1500.0)
    s2 = slack_mwh(a.sched, nothing)
    @test isapprox(s2, 1500.0; rtol = 0.01)
    @test count(p -> p > 999.0, values(a.es_price)) == 24
    b = solve2(23 * 500.0 + 1500.0 + s2)
    @test slack_mwh(b.sched, nothing) < 1.0 && all(p < 999.0 for p in values(b.es_price))
end
