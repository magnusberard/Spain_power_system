# Logic test for the connection-network shunts ([reactors].res_connection_mvar): shares and sign
# on a made-up network, then the real grid's shunt total.  No solver.
#
#     julia --project redispatch_realism/test_resmvar.jl
using Test
include(joinpath(@__DIR__, "..", "data_preparation.jl"))

g(i, bus, fuel, mw) = string(i) => Dict{String,Any}("index" => i, "gen_bus" => bus, "fuel" => fuel,
                                                     "installed_mw" => mw, "pmax" => mw / 100)
@testset "connection-network shunts" begin
    net = Dict{String,Any}("baseMVA" => 100.0, "shunt" => Dict{String,Any}(),
                           "gen" => Dict(g(1, 10, "Wind", 300.0), g(2, 10, "Solar", 100.0),
                                         g(3, 20, "Solar", 600.0), g(4, 30, "Gas", 800.0)))
    @test add_res_connection_shunts!(net, 0.0) == 0 && isempty(net["shunt"])     # off by default
    @test add_res_connection_shunts!(net, 1000.0) == 2                            # buses 10 and 20
    b = Dict(s["shunt_bus"] => s["bs"] * 100 for (_, s) in net["shunt"])
    @test b[10] ≈ 400 && b[20] ≈ 600 && !haskey(b, 30)                            # by installed MW
    @test all(s["bs"] > 0 for (_, s) in net["shunt"])                             # capacitive
end

@testset "on the real grid" begin
    RES_CONNECTION_MVAR[] = 0.0
    n0 = prepare_network().network
    RES_CONNECTION_MVAR[] = 2000.0
    n1 = prepare_network().network
    q(n) = sum(s["bs"] for (_, s) in n["shunt"]) * n["baseMVA"]
    @test q(n1) - q(n0) ≈ 2000 atol = 1e-6
    @info "real grid: $(length(n1["shunt"]) - length(n0["shunt"])) wind/solar buses get a shunt"
end
