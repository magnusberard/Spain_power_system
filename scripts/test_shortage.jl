# Tests for the shortage switches: [participation].left_for_balancing
# (participation.jl) and [balancing].hydro_budget_soft (da.jl), on the real fleet.
#     julia --project=. scripts/test_shortage.jl
using Test, CSV, DataFrames, JuMP, HiGHS
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
include(joinpath(@__DIR__, "..", "participation.jl"))
include(joinpath(@__DIR__, "..", "da.jl"))

resv_ids(nets) = sort([parse(Int, k) for (k, g) in nets[1].gens
                       if g["fuel"] == "Hydro" && lowercase(g["technology"]) == "reservoir"])
slack_mw(r) = sum(get(r.sched[h], "SLACK", 0.0) for h in eachindex(r.sched))

@testset "left for balancing" begin
    nets = [prepare_network(30000.0) for _ in 1:2]
    real_top = maximum(Float64(g["cost"][1]) for g in values(nets[1].gens)
                       if !(g["fuel"] in ("Slack", "LoadShed")))
    ls_cost = [Float64(g["cost"][1]) for g in values(nets[1].gens) if g["fuel"] == "LoadShed"]
    @test left_for_balancing!(nets, BASEMVA) == 2                     # one slack per hour
    for net in nets
        s = only(g for g in values(net.gens) if g["fuel"] == "Slack")
        @test s["cost"][1] ≈ real_top + BASEMVA                       # 1 EUR/MWh above the top offer
        @test s["cost"][1] < 1000.0 * BASEMVA
        @test s["technology"] == "Left_for_balancing"
    end
    # load shedding and the real units are untouched
    @test [Float64(g["cost"][1]) for g in values(nets[1].gens) if g["fuel"] == "LoadShed"] == ls_cost
end

@testset "soft hydro budget" begin
    # a load the fleet without reservoir hydro cannot meet (no sun, no wind), so
    # hydro must cover 3 GW in every hour; the day's budget only allows 1 GW
    probe = prepare_network(30000.0, 0.0, 0.0)
    nonhydro = sum(Float64(g["pmax"]) * BASEMVA for g in values(probe.gens)
                   if !(g["fuel"] in ("Slack", "LoadShed")) && !haskey(g, "energy_mwh") &&
                      !(g["fuel"] == "Hydro" && lowercase(g["technology"]) == "reservoir"))
    # water dearer than every other offer, so hydro only covers what nothing else can
    top = maximum(Float64(g["cost"][1]) / BASEMVA for g in values(probe.gens)
                  if !(g["fuel"] in ("Slack", "LoadShed")))
    wv  = round(top + 10.0)
    nets = [prepare_network(nonhydro + 3000.0, 0.0, 0.0; hydro_reservoir_cost = wv) for _ in 1:24]
    ids = resv_ids(nets)
    @test sum(Float64(nets[1].gens[string(k)]["pmax"]) * BASEMVA for k in ids) > 3000.0
    # a full reservoir (1 TWh) so only the budget limits hydro
    solve(budget, pen) = solve_da(nets, ids, [], 1.0e6, HiGHS.Optimizer;
                                  hydro_budget_mwh = budget, hydro_budget_penalty = pen)

    # hard budget (as before): the slack covers the rest at 1000 EUR/MWh, every hour
    hard = solve(24_000.0, nothing)
    @test hard.status == "OPTIMAL" && hard.hydro_over_mwh == 0.0
    @test slack_mw(hard) > 40_000.0
    @test all(isapprox(p, 1000.0; atol = 1.0) for p in values(hard.es_price))
    # soft budget: hydro goes over it (48 GWh), no slack, price = water cost + penalty
    soft = solve(24_000.0, 20.0)
    @test soft.status == "OPTIMAL" && slack_mw(soft) < 1.0
    @test isapprox(soft.hydro_over_mwh, 48_000.0; rtol = 0.05)
    @test all(isapprox(p, wv + 20.0; atol = 1.0) for p in values(soft.es_price))
    # a budget that does not bind: soft and hard give the same day
    big_hard = solve(200_000.0, nothing); big_soft = solve(200_000.0, 20.0)
    @test big_soft.hydro_over_mwh == 0.0
    @test isapprox(big_soft.objective, big_hard.objective; rtol = 1e-6)
    @test all(isapprox(big_soft.es_price[h], big_hard.es_price[h]; atol = 1e-3) for h in keys(big_hard.es_price))
end
