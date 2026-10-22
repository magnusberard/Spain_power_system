# Logic test for step RD7 (upward reserve): builds the Spanish network for one
# hour with a made-up schedule and requirement, applies the reserve rule and
# checks what was started.  No solver; ~1 minute.
#
#     julia --project redispatch_realism/test_rd7.jl
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
using Test, Printf, JuMP, PowerModels
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))
include(joinpath(@__DIR__, "..", "redispatch_phase1.jl"))

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

@testset "E1 tertiary reserve (P.O. 1.5 §4.3)" begin
    cfg_t = Dict("redispatch" => Dict("reserve" => Dict("enabled" => true, "requirement_file" => rf, "tertiary" => true)),
                 "unit_commitment" => Dict())
    su_t = load_rd_startups(cfg_t)
    rs = su_t.reserve
    @test rs.tertiary && rs.ramp15 !== nothing && rs.tertiary_share == 0.02
    net = build().network
    loss, demand = rd_tertiary_parts(net)
    largest = maximum(v for (k, v) in sched)
    @test loss ≈ largest atol = 1.0                                     # the largest scheduled unit
    @test demand > 20_000                                               # the hour's load (30 GW less the islands' part)
    empty!(RD_RESERVE_ROWS)
    commit_for_reserve!(net, su_t, "2024-12-02", 3)
    r = RD_RESERVE_ROWS[end]
    @test r.need_mw ≈ r.afrr_mw + r.largest_loss_mw + r.demand_part_mw atol = 0.2
    @test RD_CURRENT_RESERVE[] ≈ r.need_mw atol = 0.2
    # 15-minute rule: the half-loaded CCGT counts at most a quarter of its hourly ramp; hydro is not limited
    g3 = first(g for (_, g) in build().network["gen"] if g["name"] == ccgt[3]["name"])
    rr = rs.ramp15[("Gas", "Combined_cycle")]
    @test rd_head15(rs, g3) * BASEMVA ≈ min(head3, rr * ccgt[3]["installed_mw"] / 4) atol = 0.5
    hyd = first(g for (_, g) in build().network["gen"] if g["fuel"] == "Hydro" && g["technology"] == "reservoir")
    @test rd_head15(rs, hyd) ≈ hyd["pmax"] - hyd["pg"]
end
