# Logic test for steps RD10/RD11 (objective = "ree"): bid prices and settings.
# Pure functions only — no network, no solver; seconds.
#
#     julia --project redispatch_realism/test_rd10.jl
using Test, JuMP          # JuMP: its macros in rd_ree_objective! expand when the file loads
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))

unit(fuel, tech, c) = Dict{String,Any}("fuel" => fuel, "technology" => tech, "cost" => [c * BASEMVA, 0.0])
cfg(b) = Dict("redispatch" => Dict("bids" => b))
p_da = 100.0

@testset "RD10/RD11 bid prices" begin
    b0 = load_rd_bids(cfg(Dict()))
    @test b0.down_refund == "da" && b0.up_markup == 0.0 && b0.tie_break == 0.5

    # a unit left out of the market (cost above the day-ahead price) bids its cost
    @test rd_bid_prices(b0, unit("Gas", "Combined_cycle", 130.0), p_da) == (130.0, 100.0)
    # a cheaper unit with headroom bids at least the day-ahead price: no profitable swaps
    up, dn = rd_bid_prices(b0, unit("Gas", "Combined_cycle", 60.0), p_da)
    @test up == 100.0 && up - p_da >= 0 && p_da - dn >= 0

    # RD11: storage bids the day-ahead price, not its ~0 marginal cost
    @test rd_bid_prices(b0, unit("Hydro", "pumped_storage", 0.036), p_da) == (100.0, 100.0)
    @test rd_bid_prices(b0, unit("Hydro", "reservoir", 40.0), p_da) == (100.0, 100.0)
    @test rd_bid_prices(b0, unit("Battery", "Li-Ion", 0.0), p_da) == (100.0, 100.0)

    # mark-ups, global and by type (fuel:technology beats fuel beats default)
    b1 = load_rd_bids(cfg(Dict("up_markup" => 0.1, "down_refund" => "bid", "down_markup" => 0.2,
                               "by_type" => [Dict("type" => "Coal", "up_markup" => 0.5),
                                             Dict("type" => "Gas:Combined_cycle", "up_markup" => 0.75, "down_markup" => 0.1)])))
    @test rd_bid_prices(b1, unit("Gas", "Combined_cycle", 120.0), p_da) == (120.0 * 1.75, 120.0 * 0.9)
    @test rd_bid_prices(b1, unit("Coal", "Coal", 110.0), p_da) == (110.0 * 1.5, 110.0)
    @test rd_bid_prices(b1, unit("Gas", "Gas_turbine", 150.0), p_da) == (150.0 * 1.1, 150.0 * 0.8)

    # every swap costs money under the phase I rule: (up − p_DA) + (p_DA − refund) ≥ 0 for any pair
    for cu in (40.0, 100.0, 180.0), cd in (20.0, 90.0, 150.0)
        up, _ = rd_bid_prices(b0, unit("Gas", "Combined_cycle", cu), p_da)
        _, dn = rd_bid_prices(b0, unit("Gas", "Combined_cycle", cd), p_da)
        @test (up - p_da) + (p_da - dn) >= 0
    end
end
