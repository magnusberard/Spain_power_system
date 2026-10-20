# Logic test for step RD7 (upward reserve): builds the Spanish network for one
# hour with a made-up schedule and requirement, applies the reserve rule and
# checks what was started.  No solver; ~1 minute.
#
#     julia --project redispatch_realism/test_rd7.jl
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
using Test, Printf, JuMP, PowerModels
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))

net0 = prepare_network(30_000.0, 5_000.0, 8_000.0)
units = [g for (_, g) in net0.gens if startswith(g["name"], "G")]
ccgt = sort([g for g in units if g["fuel"] == "Gas" && g["technology"] == "Combined_cycle" && g["installed_mw"] > 150];
            by = g -> g["name"])
sched = Dict{String,Float64}(g["name"] => 0.0 for g in units)
for g in ccgt[1:2]                                   # two CCGTs at full output: no headroom
    sched[g["name"]] = g["installed_mw"]
end
sched[ccgt[3]["name"]] = 0.5 * ccgt[3]["installed_mw"]  # one at half: headroom = half its size
head3 = 0.5 * ccgt[3]["installed_mw"]

tmp = mktempdir()
rf = joinpath(tmp, "req.csv")
open(rf, "w") do io
    println(io, "date,hour,afrr_up_mw,afrr_down_mw")
    println(io, "2024-12-02,3,$(round(head3 - 10; digits = 1)),0")     # covered by the running unit
    println(io, "2024-12-02,4,$(round(head3 + 300; digits = 1)),0")    # needs start-ups
end
cfg = Dict("redispatch" => Dict("reserve" => Dict("enabled" => true, "requirement_file" => rf)), "unit_commitment" => Dict())
su = load_rd_startups(cfg)
build() = prepare_network(30_000.0, 5_000.0, 8_000.0; da_dispatch = sched, q_requires_online = true)
headroom(net) = sum(((g["pmax"] - g["pg"]) * BASEMVA for (_, g) in net["gen"] if rd_provider_on(su.reserve, g)); init = 0.0)

@testset "RD7 upward reserve" begin
    @test su !== nothing && su.reserve !== nothing && !su.startups

    net = build().network
    h0 = headroom(net)
    @test h0 >= head3 - 1                                              # the half-loaded CCGT (+ any hydro on)
    @test commit_for_reserve!(net, su, "2024-12-02", 2) == 0          # no requirement this hour
    @test RD_CURRENT_RESERVE[] == 0.0
    @test commit_for_reserve!(net, su, "2024-12-02", 3) == 0 || h0 < head3 - 10   # covered already

    net2 = build().network
    empty!(RD_STARTUP_ROWS)
    n = commit_for_reserve!(net2, su, "2024-12-02", 4)
    @test n >= 1 || headroom(net2) >= head3 + 300
    @test RD_CURRENT_RESERVE[] ≈ head3 + 300 atol = 0.2
    @test headroom(net2) >= head3 + 300 - 1                            # covered after the starts
    @test all(r.zone == "reserve" && r.round == -1 for r in RD_STARTUP_ROWS)
    started = [first(g for (_, g) in net2["gen"] if g["name"] == r.unit) for r in RD_STARTUP_ROWS]
    @test all(g["pmin"] > 0 && g["qmax"] > 0 for g in started)         # committed at minimum load
    @test !any(g["name"] in (ccgt[1]["name"], ccgt[2]["name"]) for g in started)   # running ones not restarted
end
