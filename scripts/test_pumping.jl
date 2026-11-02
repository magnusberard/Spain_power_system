# Tests for pumping.jl ([run].remove_pumping), on the real 2024 files.
#     julia --project=. scripts/test_pumping.jl
using Test, CSV, DataFrames
include(joinpath(@__DIR__, "..", "pumping.jl"))

const ES_OLD = joinpath(@__DIR__, "..", "Data", "ES_old", "load")
es_file(d) = joinpath(ES_OLD, "$(parse(Int, d[9:10]))_$(parse(Int, d[6:7]))_$(d[1:4]).csv")
"Stage table (date, hour, load_mw) of one day, from the 2024 load as run_market_chain.jl reads it."
function day_table(d; factor = 1.0)
    base = sort(CSV.read(es_file(d), DataFrame), :delivery_time)
    DataFrame(date = fill(d, 24), hour = 0:23, load_mw = Float64.(base[!, "-12"]) .* factor,
              solar_mw = zeros(24), wind_mw = zeros(24))
end
cfg(on) = Dict("run" => Dict{String,Any}("remove_pumping" => on))

@testset "pumping" begin
    # off (also when the key is missing): no pumping table, the load is not touched
    @test load_pumping(cfg(false), false) === nothing
    @test load_pumping(Dict{String,Any}(), false) === nothing
    @test load_pumping(cfg(false), true) === nothing

    # on: refused in scenario (2035) runs, a non-Bool is an error
    @test_throws ErrorException load_pumping(cfg(true), true)
    @test_throws ErrorException load_pumping(cfg("yes"), false)

    pump = load_pumping(cfg(true), false)
    @test length(pump) == 366 && all(length(v) == 24 for v in values(pump))
    @test 6.1e6 < sum(sum, values(pump)) < 6.3e6            # 6.21 TWh in 2024 (e·sios 25)
    @test all(v -> all(>=(0), v), values(pump))

    # on: every stage's load minus exactly the hour's pumping; nothing else changes
    d = "2024-05-01"
    da, cid = day_table(d), day_table(d; factor = 1.02)
    ref_da, ref_cid = deepcopy(da), deepcopy(cid)
    remove_pumping!(pump, da, cid)
    @test da.load_mw == ref_da.load_mw .- pump[d]
    @test cid.load_mw == ref_cid.load_mw .- pump[d]
    @test cid.load_mw .- da.load_mw ≈ ref_cid.load_mw .- ref_da.load_mw   # stage-to-stage change kept
    @test da[:, Not(:load_mw)] == ref_da[:, Not(:load_mw)]
    @test pump[d][14] > 1000                                 # 13:00 on 1 May: real pumping

    # a day without pumping data is an error, not a silent zero
    @test_throws ErrorException remove_pumping!(Dict{String,Vector{Float64}}(), day_table(d))

    # every 2024 load day: the load stays well above zero after the subtraction
    days = filter(dd -> isfile(es_file(dd)), sort(collect(keys(pump))))
    @test length(days) >= 362
    low = minimum(minimum(day_table(dd).load_mw .- pump[dd]) for dd in days)
    @test low > 10_000
    println("lowest 2024 load after removing pumping: $(round(Int, low)) MW over $(length(days)) days")
end

include(joinpath(@__DIR__, "..", "data_preparation.jl"))
dacfg(on) = Dict("da" => Dict{String,Any}("pump_limits" => on))
"(pmin, pmax) in MW of every pumped-storage unit, by unit_id."
function pumped_limits(net)
    gen_df = CSV.read(joinpath(@__DIR__, "..", "Data", "generations.csv"), DataFrame)
    ids = Set(String.(gen_df.unit_id[(gen_df.primary_fuel .== "Hydro") .& (gen_df.technology .== "pumped_storage")]))
    Dict(g["name"] => (g["pmin"] * BASEMVA, g["pmax"] * BASEMVA)
         for g in values(net.gens) if get(g, "name", "") in ids)
end

@testset "pump limits" begin
    # off (also when the key is missing): no table
    @test load_pump_limits(dacfg(false), false) === nothing
    @test load_pump_limits(Dict{String,Any}(), false) === nothing
    # on: refused in scenario (2035) runs, a non-Bool is an error
    @test_throws ErrorException load_pump_limits(dacfg(true), true)
    @test_throws ErrorException load_pump_limits(dacfg(1), false)

    pm = load_pump_limits(dacfg(true), false)
    @test length(pm) == 15
    @test 4900 < sum(values(pm)) < 5300                      # 5.1 GW (JRC + ratio)

    # off: every plant pumps down to −capacity (as before); on: down to −pump_mw,
    # turbining (pmax) unchanged
    off = pumped_limits(prepare_network(30000.0))
    on  = pumped_limits(prepare_network(30000.0; pump_mw = pm))
    @test length(off) == 15 && keys(off) == keys(on)
    @test all(isapprox(off[u][1], -off[u][2]) for u in keys(off))
    @test all(isapprox(on[u][1], -min(pm[u], on[u][2])) for u in keys(on))
    @test all(on[u][2] == off[u][2] for u in keys(on))
    @test isapprox(on["G0155"][1], -pm["G0155"])               # La Muela II: −808 instead of −1338
    @test sum(-v[1] for v in values(on)) < 0.65 * sum(-v[1] for v in values(off))

    # a pumped plant missing from the table is an error, not a silent full capacity
    @test_throws ErrorException prepare_network(30000.0; pump_mw = Dict("G0019" => 225.0))
end
