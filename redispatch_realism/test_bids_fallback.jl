# Logic test: a technology missing from [redispatch.bids].by_type takes its fuel's mark-ups, not the
# global default (26 Oct: solar thermal fell back to down_markup = 0 and was turned down for free).
#
#     julia --project redispatch_realism/test_bids_fallback.jl
using Test, JuMP, PowerModels, CSV, DataFrames
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))

cfg = Dict("redispatch" => Dict("bids" => Dict("up_markup" => 0.0, "down_markup" => 0.0, "down_refund" => "bid_da",
           "by_type" => [Dict("type" => "Solar:PV", "up_markup" => 0.0, "down_markup" => 0.031),
                         Dict("type" => "Gas:Combined_cycle", "up_markup" => 0.46, "down_markup" => 0.023),
                         Dict("type" => "Gas:Gas_turbine", "up_markup" => 0.46, "down_markup" => 0.047)])))
b = load_rd_bids(cfg)
g(f, t) = Dict{String,Any}("fuel" => f, "technology" => t, "cost" => [5000.0, 0.0])
@testset "bid table fallback" begin
    @test rd_markups(b, g("Solar", "PV")) == (0.0, 0.031)                     # listed
    @test rd_markups(b, g("Solar", "Solar Thermal")) == (0.0, 0.031)          # missing → its fuel's
    @test all(rd_markups(b, g("Gas", "CHP")) .≈ (0.46, 0.035))                # missing → mean of the fuel's rows
    @test rd_markups(b, g("Battery", "Li-ion")) == (0.0, 0.0)                 # no row for the fuel → global default
    up, dn = rd_bid_prices(b, g("Solar", "Solar Thermal"), 100.0)
    @test dn ≈ 96.9                                                           # refund below p_DA: turning down costs
end
let t = CSV.read(joinpath(@__DIR__, "bids_fitted.csv"), DataFrame)            # the real table covers solar thermal
    @test any((t.fuel .== "Solar") .& (t.technology .== "Solar Thermal"))
end
