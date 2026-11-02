# Tests for the BESS settings ([bess]: round-trip efficiency, wear cost, usable
# range), on the real fleet with one battery added (HiGHS).
#     julia --project=. scripts/test_bess.jl
using Test, CSV, DataFrames, JuMP, HiGHS
include(joinpath(@__DIR__, "..", "data_preparation.jl"))
include(joinpath(@__DIR__, "..", "da.jl"))

bcfg(; kw...) = Dict("bess" => Dict{String,Any}(string(k) => v for (k, v) in kw))

@testset "config" begin
    @test load_bess_params(Dict{String,Any}()) === nothing                 # no section: off
    @test load_bess_params(bcfg(enabled = false)) === nothing
    p = load_bess_params(bcfg(enabled = true))
    @test p == (eta_rt = 0.85, wear = 10.0, soc_min = 0.0, soc_max = 1.0)  # the documented defaults
    p = load_bess_params(bcfg(enabled = true, round_trip_eff = 0.9, wear_eur_mwh = 25.0, soc_min = 0.1, soc_max = 0.9))
    @test p == (eta_rt = 0.9, wear = 25.0, soc_min = 0.1, soc_max = 0.9)
    @test_throws ErrorException load_bess_params(bcfg(enabled = true, round_trip_eff = 1.2))
    @test_throws ErrorException load_bess_params(bcfg(enabled = true, wear_eur_mwh = -1.0))
    @test_throws ErrorException load_bess_params(bcfg(enabled = true, soc_min = 0.6))    # above the half-full start
end

const BUS  = "ES00029"
const BESS = [(bus_id = BUS, power_mw = 2000.0, energy_mwh = 4000.0)]       # one 2-hour battery
const NAME = "BESS_" * BUS
# a sunny day: cheap power at midday, dearer in the evening, so the battery cycles
day_nets() = [prepare_network(30000.0, h in 10:16 ? 25000.0 : 0.0, 3000.0; bess_units = BESS) for h in 1:24]
solve(nets) = solve_da(nets, Int[], [], 0.0, HiGHS.Optimizer)
pg(r)   = [r.sched[h][NAME] for h in 1:24]
dis(r)  = sum(max(x, 0.0) for x in pg(r))
chg(r)  = sum(max(-x, 0.0) for x in pg(r))
# state of charge (MWh) after each hour, from the half-full start
soc(r, eta_rt) = (e = sqrt(eta_rt); 2000.0 .- cumsum([x > 0 ? x / e : x * e for x in pg(r)]))

@testset "battery in the day-ahead" begin
    nets = day_nets()
    @test set_bess_params!(nets, (eta_rt = 1.0, wear = 0.0, soc_min = 0.0, soc_max = 1.0)) == 24
    off = solve(day_nets())                                    # as before: no settings at all
    neutral = solve(nets)                                      # settings that change nothing
    @test off.status == "OPTIMAL" && neutral.status == "OPTIMAL"
    @test isapprox(neutral.objective, off.objective; rtol = 1e-9)
    @test dis(off) > 1000.0                                    # it does cycle on this day
    @test isapprox(dis(off), chg(off); rtol = 1e-6)            # lossless: out = in

    # losses: out = 0.85 × in, and it cycles no more than without losses
    n85 = day_nets(); set_bess_params!(n85, (eta_rt = 0.85, wear = 0.0, soc_min = 0.0, soc_max = 1.0))
    r85 = solve(n85)
    @test r85.status == "OPTIMAL"
    @test isapprox(dis(r85), 0.85 * chg(r85); rtol = 1e-4)
    @test dis(r85) <= dis(off) + 1e-6
    @test all(-1e-6 .<= soc(r85, 0.85) .<= 4000.0 + 1e-6)

    # wear: a cost above any spread of the day stops cycling; a small one does not
    nw = day_nets(); set_bess_params!(nw, (eta_rt = 0.85, wear = 5000.0, soc_min = 0.0, soc_max = 1.0))
    @test dis(solve(nw)) < 1.0
    nw10 = day_nets(); set_bess_params!(nw10, (eta_rt = 0.85, wear = 10.0, soc_min = 0.0, soc_max = 1.0))
    r10 = solve(nw10)
    @test dis(r10) <= dis(r85) + 1e-6
    # the wear is in the cost: objective rises by at least nothing, at most wear × MWh out
    @test r10.objective >= r85.objective - 1e-3

    # usable range 10–90 %: the charge stays inside 400–3,600 MWh
    nr = day_nets(); set_bess_params!(nr, (eta_rt = 0.85, wear = 0.0, soc_min = 0.1, soc_max = 0.9))
    rr = solve(nr)
    @test rr.status == "OPTIMAL"
    @test all(400.0 - 1e-3 .<= soc(rr, 0.85) .<= 3600.0 + 1e-3)
    @test dis(rr) <= dis(r85) + 1e-6
    # each day still ends where it started (half full)
    @test isapprox(soc(rr, 0.85)[end], 2000.0; atol = 1e-3)
end
