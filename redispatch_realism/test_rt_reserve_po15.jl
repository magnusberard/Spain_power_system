# Test for the real-time reserve requirement from P.O. 1.5's terms ([redispatch.reserve] e2_requirement = "po15",
# 9 Nov 2026). No network, no solver (~20 s):
#   1. load_rd_reserve reads data/rt_reserve_formula.csv (aFRR by hour, demand share, gap ratios)
#   2. rd_reserve_po15_base! gives build_rt_reserve_formula.py's formula without the largest unit, for every hour of a
#      2024 year run's DA profiles (ARGS[1], a year-run folder; checked against the formula written out here)
#   3. e2_req adds the largest scheduled nuclear/CCGT/coal unit (E2_BIG), and only those
#
#     julia --project redispatch_realism/test_rt_reserve_po15.jl ../solstorm_results/y24rtact
using CSV, DataFrames, Dates, Printf, Test, JuMP, PowerModels
const ISLAND_BUSES = nothing
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))
include(joinpath(@__DIR__, "..", "redispatch_reserve.jl"))

cfg = Dict("redispatch" => Dict("reserve" => Dict("enabled" => true, "rule" => "e2", "e2_requirement" => "po15")))
rs = load_rd_reserve(cfg)
t = CSV.read(joinpath(@__DIR__, "data", "rt_reserve_formula.csv"), DataFrame)
par(p) = only(t.value[t.part .== p])
prof = vcat([CSV.read(joinpath(ARGS[1], d, "da_profiles.csv"), DataFrame) for d in readdir(ARGS[1])
             if isfile(joinpath(ARGS[1], d, "da_profiles.csv"))]...)
prof = unique(prof, [:date, :hour])

@testset "P.O. 1.5 requirement" begin
    @test rs.po15 !== nothing && length(rs.po15.afrr) == 24 && minimum(rs.po15.afrr) >= 500.0
    maxdiff = 0.0
    for r in eachrow(prof)
        got = rd_reserve_po15_base!(rs, string(r.date), Int(r.hour), r.load_mw, r.wind_mw, r.solar_mw)
        want = only(t.value[(t.part .== "afrr") .& (t.hour .== r.hour)]) + (par("demand_share") + par("gap_demand")) * r.load_mw +
               par("gap_wind") * r.wind_mw + par("gap_solar") * r.solar_mw
        maxdiff = max(maxdiff, abs(got - want))
    end
    @printf "  %d hours, largest difference to the formula %.2e MW; mean requirement without the largest unit %.0f MW\n" nrow(prof) maxdiff sum(values(rs.req)) / length(rs.req)
    @test maxdiff < 1e-6 && length(rs.req) == nrow(prof)

    empty!(E2_BIG); push!(E2_BIG, "G_NUC", "G_CCGT")
    d, h = string(prof.date[1]), Int(prof.hour[1])
    s = Dict("G_NUC" => 1011.0, "G_CCGT" => 400.0, "H_BIG" => 3000.0)    # a hydro aggregate does not count
    @test e2_req(rs, d, h, s) ≈ rs.req[(d, h)] + 1011.0
    @test e2_req(rs, d, h, nothing) ≈ rs.req[(d, h)]
    @test e2_req(rs, "1999-01-01", 0, s) === nothing                   # no requirement row: no requirement
    old = (req = Dict((d, h) => 3000.0), scale = 1.0, extra_mw = 0.0, rule = :e2)   # a tuple without po15: file mode
    @test e2_req(old, d, h, s) == 3000.0
end
