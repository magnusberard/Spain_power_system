# Test for the real-time reserve rule E2 ([redispatch.reserve].rule = "e2", redispatch_reserve.jl): available reserve
# from the schedule (running CCGT/coal capacity − output, pumped-storage turbine headroom, stoppable pumping; island
# units, reservoir hydro and off units do not count), the ±1 h window over the day's shortfalls, the starts (cheapest
# per MW of headroom, at minimum load) and the hours without a requirement or a neighbouring day. No solver; seconds.
#
#     julia --project redispatch_realism/test_rt_reserve_e2.jl
using Test, Printf, JuMP, PowerModels, CSV, DataFrames, Dates
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))

# Stubs for the chain's globals the rule reads
const RD_STARTUPS = nothing                       # no phase I: the schedule is the balancing schedule
const ISLAND_BUSES = Set(["ISL"])
const D = "2024-12-02"
sched_of(h) = Dict("CC_ON" => 300.0, "COAL_ON" => 350.0, "PUMP_P" => -150.0, "PUMP_T" => 50.0,
                   "CC_ISL" => 100.0, "RES" => 500.0)
rd_sched_for(d, h) = d == D ? sched_of(h) : nothing           # neighbouring days not in the run

unit(name, fuel, tech, mw, bus; on, cost = 70.0) = Dict{String,Any}("name" => name, "fuel" => fuel,
    "technology" => tech, "installed_mw" => mw, "pmax" => mw / BASEMVA, "pmin" => tech == "pumped_storage" ? -mw / BASEMVA : 0.0,
    "pg" => 0.0, "gen_bus" => bus, "index" => 0,
    "qmax" => on ? mw / BASEMVA : 0.0, "qmin" => on ? -mw / BASEMVA : 0.0, "cost" => [cost * BASEMVA, 0.0])
net() = Dict{String,Any}("bus" => Dict("1" => Dict("name" => "B1"), "2" => Dict("name" => "ISL")),
    "gen" => Dict(
    "1" => unit("CC_ON", "Gas", "Combined_cycle", 400.0, 1; on = true),        # headroom 100
    "2" => unit("COAL_ON", "Coal", "Coal", 350.0, 1; on = true),               # at maximum: 0
    "3" => unit("PUMP_P", "Hydro", "pumped_storage", 200.0, 1; on = true),     # pumping 150: 150
    "4" => unit("PUMP_T", "Hydro", "pumped_storage", 200.0, 1; on = true),     # turbine 50: 150
    "5" => unit("CC_ISL", "Gas", "Combined_cycle", 300.0, 2; on = true),       # island: not counted
    "6" => unit("RES", "Hydro", "reservoir", 900.0, 1; on = true),             # reservoir: not counted
    "7" => unit("CC_CHEAP", "Gas", "Combined_cycle", 400.0, 1; on = false, cost = 60.0),
    "8" => unit("CC_DEAR", "Gas", "Combined_cycle", 400.0, 1; on = false, cost = 90.0)))

req = Dict((D, h) => 300.0 for h in 0:23)
req[(D, 10)] = 600.0                                # shortfall 200 in h10 only
delete!(req, (D, 20))                               # no requirement in h20
rs = (req = req, scale = 1.0, extra_mw = 0.0, rule = :e2, window_ahead = 1, window_back = 1, tertiary = false)
su = (enforce_min_load = true, min_load_floor_running = false, candidates = Set(["gas:combined_cycle", "coal"]),
      candidate_min_mw = 100.0, gas_min_load_1x1 = 0.39, gas_min_load_2x1 = 0.18, gas_two_by_one_mw = 700.0,
      gas_wear_eur_per_mw = 57.4, gas_start_fuel = 1.5, gas_eta = 0.55,
      coal_large_mw = 300.0, coal_min_load_large = 0.4, coal_min_load_small = 0.4,
      coal_wear_large = 110.0, coal_wear_small = 110.0, coal_start_fuel = 3.0, coal_eta = 0.36, reserve = rs)

function run_hour(h)
    n = net()
    e2_prepare_hour!(n, su, D, sched_of(h))
    su_apply_min_load!(n, su)
    k = commit_for_reserve!(n, su, D, h)
    return n, k
end

@testset "real-time reserve rule E2" begin
    n, k = run_hour(0)
    @test sort(collect(keys(E2_UNITS))) == ["CC_CHEAP", "CC_DEAR", "CC_ON", "COAL_ON", "PUMP_P", "PUMP_T"]
    @test E2_AVAIL[(D, 0)] ≈ 400.0                                  # 100 + 0 + 150 + 150
    @test E2_WINDOW[(D, 10)] ≈ 200.0
    @test E2_WINDOW[(D, 9)] ≈ 200.0 && E2_WINDOW[(D, 11)] ≈ 200.0   # one hour ahead and one back
    @test E2_WINDOW[(D, 8)] == 0.0 && E2_WINDOW[(D, 12)] == 0.0
    @test !haskey(E2_WINDOW, (D, 20))                               # no requirement: no rule
    @test E2_WINDOW[(D, 0)] == 0.0 && E2_WINDOW[(D, 23)] == 0.0     # missing neighbouring days are skipped
    @test k == 0 && RD_CURRENT_RESERVE[] == 0.0
    for h in (9, 10, 11)
        n, k = run_hour(h)
        g = Dict(x["name"] => x for (_, x) in n["gen"])
        @test k == 1                                                # 400 + 200 needed; one start adds 244
        @test g["CC_CHEAP"]["pmin"] ≈ 0.39 * 4.0                    # the cheaper one, at minimum load
        @test g["CC_DEAR"]["pmax"] == 0.0                           # held off
        @test RD_CURRENT_RESERVE[] ≈ 600.0
        @test RD_RESERVE_ROWS[end].headroom_after_mw ≈ 400.0 + 0.61 * 400.0
    end
    @test RD_RESERVE_ROWS[end - 1].shortfall_mw ≈ 200.0             # h10's own shortfall
    @test count(r -> r.zone == "reserve", RD_STARTUP_ROWS) == 1           # started once in h9 ...
    @test count(r -> r.zone == "reserve_held", RD_STARTUP_ROWS) == 2      # ... held in h10 and h11, no new start
    @test all(r.start_cost_eur == 0.0 for r in RD_STARTUP_ROWS if r.zone == "reserve_held")
    @test RD_STARTUP_ROWS[1].start_cost_eur > 0
    n, k = run_hour(12)
    @test k == 0
end
