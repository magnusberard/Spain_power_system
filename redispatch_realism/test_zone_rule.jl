# Test for RD5's zone rule in the model ([redispatch.mustrun].rule_file, 9 Nov 2026): load_rd_mustrun reads the rule,
# rd_mustrun_from_rule! fills the zone needs from an hour's DA demand. Checks (no network, no solver, ~20 s):
#   1. every hour of 2024 (the model's own demand, data/model_load_2024.csv) gives exactly the zone needs of
#      build_zone_need_rule.py's apply_rule (--apply-out file, passed as ARGS[1])
#   2. load beyond the fitted range falls in the end bins (2035 demand is higher than 2024's)
#   3. an hour whose bin has no need clears an earlier need for that hour
#
#     python redispatch_realism/build_zone_need_rule.py --load redispatch_realism/data/model_load_2024.csv \
#         --out redispatch_realism/data/zone_need_rule_model_load.csv --apply redispatch_realism/data/model_load_2024.csv \
#         --apply-out <py.csv>
#     julia --project redispatch_realism/test_zone_rule.jl <py.csv>
using CSV, DataFrames, Printf, Test, JuMP, PowerModels
include(joinpath(@__DIR__, "..", "redispatch_startups.jl"))

py = CSV.read(ARGS[1], DataFrame)
cfg = Dict("redispatch" => Dict("mustrun" => Dict("enabled" => true,
        "zones_file" => "redispatch_realism/data/voltage_zone_units.csv",
        "rule_file" => "redispatch_realism/data/zone_need_rule_model_load.csv", "rule_p_min" => 0.4)))
mr = load_rd_mustrun(cfg)
load = CSV.read(joinpath(@__DIR__, "data", "model_load_2024.csv"), DataFrame)

@testset "zone rule in the model" begin
    @test mr.rule !== nothing
    for r in eachrow(load)
        rd_mustrun_from_rule!(mr, string(r.date), Int(r.hour), Float64(r.load_mw))
    end
    jl = Set((d, h, z, n) for ((d, h), v) in mr.need for (z, n) in v)
    pyset = Set((string(r.date), Int(r.hour), String(r.zone), Int(r.n_online)) for r in eachrow(py) if r.n_online > 0)
    @printf "  2024: model %d zone-hours, Python %d, in both %d\n" length(jl) length(pyset) length(intersect(jl, pyset))
    @test jl == pyset

    lo, hi = minimum(load.load_mw), maximum(load.load_mw)
    n_hi = rd_mustrun_from_rule!(mr, "2024-07-01", 0, 2.0 * hi)       # far above 2024's peak
    n_top = rd_mustrun_from_rule!(mr, "2024-07-01", 1, hi)
    @test n_hi == n_top
    n_lo = rd_mustrun_from_rule!(mr, "2024-07-01", 2, 0.5 * lo)
    @test n_lo == rd_mustrun_from_rule!(mr, "2024-07-01", 3, lo)
    @printf "  zones with a need: at 2x 2024's peak %d, at the peak %d, at half the minimum %d\n" n_hi n_top n_lo

    # an hour first in a need bin, then set to a no-need load, has no need left
    rd_mustrun_from_rule!(mr, "2024-07-02", 5, lo)
    @test haskey(mr.need, ("2024-07-02", 5))
    rd_mustrun_from_rule!(mr, "2024-07-02", 5, 2.0 * hi)
    @test n_hi > 0 || !haskey(mr.need, ("2024-07-02", 5))
end
