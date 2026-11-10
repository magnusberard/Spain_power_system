# Test for fix A (10 Nov 2026): e2_bus_room gives what a bus can still export, ratings of its in-service branches minus
# (scheduled generation − load). Toy network, no solver (~10 s):
#   bus 1: one 393 MW line, Besós-like (3 + 4 scheduled at 300 MW, load 50 MW) -> room 393 − 250 = 143 MW
#   bus 2: two lines of 1,000 MW, no generation, load 200 MW                 -> room 2,200 MW
#   an out-of-service branch does not count; a unit started at 335 MW minimum load fits on bus 2, not on bus 1
#
#     julia --project redispatch_realism/test_rt_deliverable.jl
using CSV, DataFrames, Dates, Printf, Test, JuMP, PowerModels
const BASEMVA = 100.0
const ISLAND_BUSES = nothing
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))

net = Dict{String,Any}(
    "branch" => Dict("1" => Dict("f_bus" => 1, "t_bus" => 3, "rate_a" => 3.93, "br_status" => 1),
                     "2" => Dict("f_bus" => 2, "t_bus" => 3, "rate_a" => 10.0, "br_status" => 1),
                     "3" => Dict("f_bus" => 2, "t_bus" => 4, "rate_a" => 10.0, "br_status" => 1),
                     "4" => Dict("f_bus" => 1, "t_bus" => 4, "rate_a" => 10.0, "br_status" => 0)),
    "gen" => Dict("1" => Dict("name" => "B3", "gen_bus" => 1, "pmax" => 4.12, "pmin" => 0.0, "pg" => 0.0, "qmin" => 0.0, "qmax" => 0.0),
                  "2" => Dict("name" => "B5", "gen_bus" => 1, "pmax" => 8.59, "pmin" => 0.0, "pg" => 0.0, "qmin" => 0.0, "qmax" => 0.0),
                  "3" => Dict("name" => "X", "gen_bus" => 2, "pmax" => 8.59, "pmin" => 0.0, "pg" => 0.0, "qmin" => 0.0, "qmax" => 0.0)),
    "load" => Dict("1" => Dict("load_bus" => 1, "pd" => 0.5), "2" => Dict("load_bus" => 2, "pd" => 2.0)))
s = Dict("B3" => 300.0, "B5" => 0.0, "X" => 0.0)

@testset "fix A: bus room" begin
    room = e2_bus_room(net, s)
    @printf "  room: bus 1 %.0f MW, bus 2 %.0f MW\n" room[1] room[2]
    @test room[1] ≈ 393.0 - (300.0 - 50.0)          # the out-of-service 1,000 MW branch does not count
    @test room[2] ≈ 2000.0 + 200.0
    @test room[1] < 335.0 && room[2] >= 335.0       # a 335 MW minimum load fits on bus 2 only
end
