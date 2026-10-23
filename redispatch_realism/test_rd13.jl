# Logic test for step RD13 (water budget): the hourly cap and tally on a made-up network.  No solver; seconds.
#
#     julia --project redispatch_realism/test_rd13.jl
using Test, Printf, JuMP, PowerModels, CSV, DataFrames
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))
include(joinpath(@__DIR__, "..", "redispatch_phase1.jl"))

gen(i, name, fuel, pmin, pmax) = string(i) => Dict{String,Any}("index" => i, "name" => name, "fuel" => fuel,
                                                               "pmin" => pmin / BASEMVA, "pmax" => pmax / BASEMVA)
net() = Dict("gen" => Dict(gen(1, "H1", "Hydro", 0, 500), gen(2, "P1", "Hydro", -300, 300),
                           gen(3, "G1", "Gas", 0, 400), gen(4, "HF", "Hydro", 200, 200)))
sched = Dict("H1" => 200.0, "P1" => -100.0, "G1" => 100.0, "HF" => 200.0)
sol(pgs) = Dict("solution" => Dict("gen" => Dict(string(i) => Dict("pg" => p / BASEMVA) for (i, p) in pgs)))

@testset "RD13 water budget" begin
    hb = load_rd_hydro_budget(Dict("redispatch" => Dict("hydro_budget" => Dict("enabled" => true, "tolerance_mwh" => 0.0))))
    @test hb !== nothing && hb.tolerance_mwh == 0.0
    @test load_rd_hydro_budget(Dict()) === nothing                                 # off by default
    empty!(RD_HYDRO_TALLY)
    # hour 1: no water given back yet → hydro capped at its schedule; gas and frozen hydro untouched
    n1 = net()
    @test hydro_budget_cap!(n1, sched, hb, "rt", "2024-12-02") == 2
    @test n1["gen"]["1"]["pmax"] * BASEMVA ≈ 200 && n1["gen"]["2"]["pmax"] * BASEMVA ≈ -100
    @test n1["gen"]["3"]["pmax"] * BASEMVA ≈ 400 && n1["gen"]["4"]["pmax"] * BASEMVA ≈ 200
    # H1 goes 80 MW down in hour 1 → hour 2 may run 80 MW above its schedule
    hydro_budget_record!(sol([(1, 120.0), (2, -100.0), (3, 180.0), (4, 200.0)]), n1, sched, hb, "rt", "2024-12-02")
    @test RD_HYDRO_TALLY[("rt", "2024-12-02", "H1")] ≈ -80
    n2 = net()
    hydro_budget_cap!(n2, sched, hb, "rt", "2024-12-02")
    @test n2["gen"]["1"]["pmax"] * BASEMVA ≈ 280
    # a new day starts with an empty budget; another stage has its own tally
    n3 = net(); hydro_budget_cap!(n3, sched, hb, "rt", "2024-12-03")
    @test n3["gen"]["1"]["pmax"] * BASEMVA ≈ 200
    n4 = net(); hydro_budget_cap!(n4, sched, hb, "phase1_ac", "2024-12-02")
    @test n4["gen"]["1"]["pmax"] * BASEMVA ≈ 200
    # tolerance adds headroom
    hbt = (tolerance_mwh = 50.0,)
    n5 = net(); hydro_budget_cap!(n5, sched, hbt, "rt", "2024-12-04")
    @test n5["gen"]["1"]["pmax"] * BASEMVA ≈ 250
    # never below pmin (pumping unit P1 scheduled at its minimum stays feasible)
    n6 = net(); hydro_budget_cap!(n6, Dict("P1" => -400.0), hb, "rt", "2024-12-05")
    @test n6["gen"]["2"]["pmax"] >= n6["gen"]["2"]["pmin"]
end
