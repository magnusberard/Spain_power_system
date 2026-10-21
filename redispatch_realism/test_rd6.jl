# Logic test for step RD6 (N-1 in phase I): DC transfer and outage distribution
# factors on small networks with known answers.  No solver; seconds.
#
#     julia --project redispatch_realism/test_rd6.jl
using Test, JuMP, PowerModels, Printf, CSV, DataFrames
const BASEMVA = 100.0
include(joinpath(@__DIR__, "..", "redispatch_objective.jl"))
include(joinpath(@__DIR__, "..", "redispatch_phase1.jl"))

bus(i, t) = string(i) => Dict{String,Any}("index" => i, "bus_type" => t, "base_kv" => 400.0)
br(i, f, t, x) = string(i) => Dict{String,Any}("index" => i, "f_bus" => f, "t_bus" => t, "br_x" => x, "br_status" => 1, "rate_a" => 1.0)
lodf(ptdf, ids, col, net, l, c) = begin
    b = net["branch"][string(ids[c])]
    phi = ptdf[:, col[b["f_bus"]]] - ptdf[:, col[b["t_bus"]]]
    phi[l] / (1 - phi[c])
end

@testset "RD6 transfer and outage factors" begin
    # triangle 1-2-3, equal reactances, slack at bus 1
    tri = Dict("bus" => Dict(bus(1, 3), bus(2, 1), bus(3, 1)),
               "branch" => Dict(br(1, 1, 2, 0.1), br(2, 2, 3, 0.1), br(3, 3, 1, 0.1)))
    ptdf, ids, col = rd_ptdf(tri)
    @test ids == [1, 2, 3]
    # 1 MW in at bus 2, out at the slack: 2/3 directly on 1-2 (as flow 2→1, i.e. −2/3 from 1 to 2), 1/3 via 2-3-1
    @test ptdf[1, col[2]] ≈ -2 / 3
    @test ptdf[2, col[2]] ≈ 1 / 3
    @test ptdf[3, col[2]] ≈ 1 / 3
    @test all(ptdf[:, col[1]] .== 0)                         # injection at the slack moves nothing
    # losing line 1-2: all its flow goes round 2-3-1, so LODF = ±1 on both
    @test abs(lodf(ptdf, ids, col, tri, 2, 1)) ≈ 1
    @test abs(lodf(ptdf, ids, col, tri, 3, 1)) ≈ 1
    # post-outage flow: 2/3 + 1/3 = 1 MW on 2-3 for the 1 MW injection
    f = ptdf[:, col[2]]
    @test abs(f[2] + lodf(ptdf, ids, col, tri, 2, 1) * f[1]) ≈ 1

    # radial branch 3-4 added: its outage islands bus 4 (1 − φ_cc = 0, skipped by add_n1_cuts!)
    rad = Dict("bus" => Dict(bus(1, 3), bus(2, 1), bus(3, 1), bus(4, 1)),
               "branch" => Dict(br(1, 1, 2, 0.1), br(2, 2, 3, 0.1), br(3, 3, 1, 0.1), br(4, 3, 4, 0.05)))
    p2, ids2, col2 = rd_ptdf(rad)
    b4 = rad["branch"]["4"]
    phi4 = p2[:, col2[b4["f_bus"]]] - p2[:, col2[b4["t_bus"]]]
    @test abs(1 - phi4[4]) < 1e-9
    # unequal reactances: a stiffer path takes more
    tri2 = Dict("bus" => Dict(bus(1, 3), bus(2, 1), bus(3, 1)),
                "branch" => Dict(br(1, 1, 2, 0.2), br(2, 2, 3, 0.05), br(3, 3, 1, 0.05)))
    p3, _, c3 = rd_ptdf(tri2)
    @test abs(p3[1, c3[2]]) ≈ 1 / 3 && abs(p3[2, c3[2]]) ≈ 2 / 3   # x 0.2 direct vs 0.1 round: round takes 2/3
end

@testset "RD6 n1_outage = element: trip one of n parallel circuits" begin
    # triangle where branch 1 (1-2) stands for two parallel circuits of x = 0.2 (merged x = 0.1);
    # 1 MW injected at bus 2, taken at the slack (bus 1)
    tri = Dict("bus" => Dict(bus(1, 3), bus(2, 1), bus(3, 1)),
               "branch" => Dict(br(1, 1, 2, 0.1), br(2, 2, 3, 0.1), br(3, 3, 1, 0.1)))
    ptdf, ids, col = rd_ptdf(tri)
    f = ptdf[:, col[2]]                                      # pre-outage flows
    ne = 2
    phi = ptdf[:, col[1]] - ptdf[:, col[2]]                  # transfer bus 1 → bus 2 (branch 1's ends)
    den = 1 - phi[1] / ne
    post = f .+ (phi ./ (den * ne)) .* f[1]                  # add_n1_cuts!, other branches
    rest = (1 + (phi[1] - 1) / (den * ne)) * f[1]            # add_n1_cuts!, the circuit left in branch 1
    # exact: the network after the outage, branch 1 with one circuit (x = 0.2)
    after = Dict("bus" => tri["bus"], "branch" => Dict(br(1, 1, 2, 0.2), br(2, 2, 3, 0.1), br(3, 3, 1, 0.1)))
    pa, ida, cola = rd_ptdf(after)
    fa = pa[:, cola[2]]
    @test post[2] ≈ fa[2] && post[3] ≈ fa[3]
    @test rest ≈ fa[1]
    # with one element the formula is the whole-branch LODF of before
    @test (f .+ (phi ./ (1 - phi[1])) .* f[1])[2] ≈ f[2] + lodf(ptdf, ids, col, tri, 2, 1) * f[1]
end
