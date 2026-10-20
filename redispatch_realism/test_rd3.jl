# Logic test for step RD3 ([redispatch].q_requires_online): builds the Spanish
# network for one hour with a made-up anchor schedule and checks the reactive
# limits unit by unit.  No solver, no market run; ~1 minute, < 1 GB.
#
#     julia --project redispatch_realism/test_rd3.jl
#
# Schedule: one combined cycle at half load, one nuclear unit at full load, one
# pumped-storage unit pumping, every other unit at 0 MW.
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
using Test

const LOAD, SOLAR, WIND = 30_000.0, 5_000.0, 8_000.0
build(; kw...) = prepare_network(LOAD, SOLAR, WIND; load_power_factor = 0.98, kw...)

base = build()
units = [g for (_, g) in base.gens if startswith(g["name"], "G")]
pick(f, t) = first(g for g in units if g["fuel"] == f && lowercase(g["technology"]) == t && g["installed_mw"] > 50)
ccgt_on  = pick("Gas", "combined_cycle")
nuc_on   = pick("Nuclear", "nuclear")
ps_pump  = pick("Hydro", "pumped_storage")
sched = Dict{String,Float64}(g["name"] => 0.0 for g in units)
sched[ccgt_on["name"]] = 0.5 * ccgt_on["installed_mw"]
sched[nuc_on["name"]]  = nuc_on["installed_mw"]
sched[ps_pump["name"]] = -0.5 * ps_pump["installed_mw"]

off = build(da_dispatch = sched)
on  = build(da_dispatch = sched, q_requires_online = true)
cnd = build(da_dispatch = sched, q_requires_online = true, q_condenser_ok = ["Hydro:pumped_storage", "Hydro:reservoir"])
byname(net) = Dict(g["name"] => g for (_, g) in net.gens)
O, N, C = byname(off), byname(on), byname(cnd)
sync = [n for (n, g) in N if startswith(n, "G") && !(g["fuel"] in ("Wind", "Solar"))]
ls   = [n for n in keys(N) if startswith(n, "LS_")]
k    = tan(acos(0.98))

@testset "RD3 q_requires_online" begin
    @testset "switch off changes nothing" begin
        @test all(O[n]["qmax"] == byname(build(da_dispatch = sched))[n]["qmax"] for n in sync)
        @test all(O[n]["qmax"] > 0 for n in sync)                       # today: every unit gives Q
        @test all(O[n]["qmax"] ≈ O[n]["pmax"] for n in ls if O[n]["pmax"] > 0)   # today: LS ±pd free
        @test all(!isfinite(O[n]["qp_ratio"]) for n in ls)
    end
    @testset "running units keep their reactive power" begin
        @test N[ccgt_on["name"]]["qmax"] ≈ O[ccgt_on["name"]]["qmax"] > 0
        @test N[nuc_on["name"]]["qmax"]  ≈ O[nuc_on["name"]]["qmax"] > 0
        @test N[ps_pump["name"]]["qmax"] ≈ O[ps_pump["name"]]["qmax"] > 0   # pumping = synchronised
    end
    @testset "units scheduled at 0 MW give none" begin
        idle = [n for n in sync if n ∉ (ccgt_on["name"], nuc_on["name"], ps_pump["name"])]
        @test !isempty(idle)
        @test all(N[n]["qmax"] == 0.0 && N[n]["qmin"] == 0.0 for n in idle)
        @test all(N[n]["pmax"] == O[n]["pmax"] && N[n]["pmin"] == O[n]["pmin"] for n in sync)  # P untouched
    end
    @testset "wind and solar untouched (that is RD4)" begin
        res = [n for (n, g) in N if g["fuel"] in ("Wind", "Solar")]
        @test all(N[n]["qmax"] == O[n]["qmax"] && N[n]["qp_ratio"] == O[n]["qp_ratio"] for n in res)
    end
    @testset "load shedding: reactive only in proportion to shed load" begin
        @test all(N[n]["qp_ratio"] ≈ k for n in ls)
        @test all(N[n]["qmax"] ≈ k * N[n]["pmax"] for n in ls)
    end
    @testset "condenser exemption" begin
        hyd = [n for n in sync if C[n]["fuel"] == "Hydro" && lowercase(C[n]["technology"]) in ("pumped_storage", "reservoir")]
        @test all(C[n]["qmax"] ≈ O[n]["qmax"] for n in hyd)
        gas_idle = [n for n in sync if C[n]["fuel"] == "Gas" && n != ccgt_on["name"]]
        @test all(C[n]["qmax"] == 0.0 for n in gas_idle)
    end
end
