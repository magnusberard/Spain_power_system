# Test for [network].dedup_ab_lines on the real Data/lines.csv: which rows are duplicates, and what
# the switch does to the AC network (line charging, impedance, rating).  No solver; ~30 s.
#
#     julia --project redispatch_realism/test_dedup_ab.jl
using Test
include(joinpath(@__DIR__, "..", "data_preparation.jl"))

@testset "a/b duplicate lines" begin
    ldf = CSV.read(joinpath(DATA, "lines.csv"), DataFrame)
    dup = ab_duplicate_ids(ldf)
    @test length(dup) == 2 * 692                               # 692 identical pairs, both rows flagged
    @test all(endswith(i, "a") || endswith(i, "b") for i in dup)

    charging(n) = sum((b["b_fr"] + b["b_to"]) for (_, b) in n["branch"] if !startswith(b["name"], "TR_")) * n["baseMVA"]
    DEDUP_AB_LINES[] = false
    n0 = prepare_network().network                             # off by default: as on main
    DEDUP_AB_LINES[] = true
    n1 = prepare_network().network
    DEDUP_AB_LINES[] = false
    q0, q1 = charging(n0), charging(n1)
    @info "line charging at 1.0 pu: $(round(q0 / 1e3; digits = 1)) → $(round(q1 / 1e3; digits = 1)) Gvar"
    @test 33e3 < q0 < 37e3                                     # as built: ~35 Gvar
    @test 19e3 < q1 < 23e3                                     # README: "roughly 21 GVAr"
    byname(n) = Dict(b["name"] => b for (_, b) in n["branch"])
    b0, b1 = byname(n0), byname(n1)
    d = first(dup)
    @test b1[d]["br_x"] ≈ 2 * b0[d]["br_x"] && b1[d]["rate_a"] ≈ b0[d]["rate_a"] / 2
    other = first(k for k in keys(b0) if !(k in dup) && !startswith(k, "TR_"))
    @test b1[other]["br_x"] ≈ b0[other]["br_x"]               # other lines untouched
end
