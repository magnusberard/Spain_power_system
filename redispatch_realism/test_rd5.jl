# Logic test for step RD5 (must-run by voltage zone): builds the Spanish network
# for one hour with a made-up schedule and a made-up zone, applies the zone rule
# and checks what was started.  No solver; ~1 minute.
#
#     julia --project redispatch_realism/test_rd5.jl
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
using Test, Printf, JuMP, PowerModels
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))
include(joinpath(@__DIR__, "..", "redispatch_phase1.jl"))

net0 = prepare_network(30_000.0, 5_000.0, 8_000.0)
units = [g for (_, g) in net0.gens if startswith(g["name"], "G")]
ccgt = sort([g for g in units if g["fuel"] == "Gas" && g["technology"] == "Combined_cycle" && g["installed_mw"] > 150];
            by = g -> g["name"])[1:4]
nuc = first(g for g in units if g["fuel"] == "Nuclear")
sched = Dict{String,Float64}(g["name"] => 0.0 for g in units)
sched[ccgt[1]["name"]] = 0.6 * ccgt[1]["installed_mw"]          # one zone CCGT already running

tmp = mktempdir()
zf, rf = joinpath(tmp, "zones.csv"), joinpath(tmp, "req.csv")
open(zf, "w") do io
    println(io, "zone,unit_id")
    foreach(g -> println(io, "Z,", g["name"]), [ccgt; nuc])
end
open(rf, "w") do io
    println(io, "date,hour,zone,n_raised,n_online")
    println(io, "2024-12-02,3,Z,1,2")      # hour 3: two thermal units must run
    println(io, "2024-12-02,4,Z,1,6")      # hour 4: more than the zone has
end
cfg = Dict("redispatch" => Dict("mustrun" => Dict("enabled" => true, "zones_file" => zf, "requirement_file" => rf)),
           "unit_commitment" => Dict())
su = load_rd_startups(cfg)
build() = prepare_network(30_000.0, 5_000.0, 8_000.0; da_dispatch = sched, q_requires_online = true)

@testset "RD5 must-run by zone" begin
    @test su !== nothing && !su.startups && su.mustrun !== nothing

    empty!(RD_STARTUP_ROWS)
    net = build().network
    @test apply_zone_mustrun!(net, su, "2024-12-02", 2) == 0          # no requirement this hour
    @test apply_zone_mustrun!(net, su, "2024-12-02", 3) == 1          # 1 running, 2 needed
    started = RD_STARTUP_ROWS[end]
    g = first(x for (_, x) in net["gen"] if x["name"] == started.unit)
    @test started.unit in [c["name"] for c in ccgt[2:4]]               # a zone CCGT, not nuclear
    @test g["pmin"] > 0 && g["qmax"] > 0                               # committed: min load, reactive power
    cost(x) = su_terms(su, x)[3]
    others = [first(y for (_, y) in net["gen"] if y["name"] == c["name"]) for c in ccgt[2:4] if c["name"] != started.unit]
    @test all(cost(g) <= cost(o) for o in others)                       # the cheapest one
    @test started.zone == "Z" && started.zone_need == 2 && started.zone_online == 1
    @test apply_zone_mustrun!(net, su, "2024-12-02", 3) == 0          # now satisfied

    net2 = build().network
    @test apply_zone_mustrun!(net2, su, "2024-12-02", 4) == 3         # needs 6: starts every CCGT left
    nucg = first(x for (_, x) in net2["gen"] if x["name"] == nuc["name"])
    @test nucg["qmax"] == 0.0                                           # nuclear never started
end
