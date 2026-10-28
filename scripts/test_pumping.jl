# Tests for pumping.jl ([run].remove_pumping), on the real 2024 files.
#     julia --project=. scripts/test_pumping.jl
using Test, CSV, DataFrames, JSON
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

include(joinpath(@__DIR__, "..", "da.jl"))
using HiGHS
carrycfg(on) = Dict("da" => Dict{String,Any}("pumped_carry" => on))

@testset "pumped carry: config and state" begin
    @test load_pumped_carry(carrycfg(false), false) === nothing
    @test load_pumped_carry(Dict{String,Any}(), false) === nothing
    @test_throws ErrorException load_pumped_carry(carrycfg(true), true)       # 2035 refused
    @test_throws ErrorException load_pumped_carry(carrycfg("yes"), false)
    c = load_pumped_carry(carrycfg(true), false)
    @test c.mixed == Set(["G0070", "G0162", "G0095", "G0323", "G0740"]) && c.days == 7

    # first day: plants start half full and keep that level (no price yet)
    st = PumpedState()
    p1 = pumped_input(c, st, "2024-02-26")
    @test isempty(p1.start) && p1.price === nothing && p1.mixed == c.mixed
    # the next day continues from the end level, valued at the mean of the days so far
    pumped_end_of_day!(c, st, "2024-02-26", Dict("G0019" => 500.0), 40.0)
    p2 = pumped_input(c, st, "2024-02-27")
    @test p2.start == Dict("G0019" => 500.0) && p2.price ≈ 40.0
    for (i, d) in enumerate(Date(2024, 2, 27):Day(1):Date(2024, 3, 5))       # 8 more days
        pumped_end_of_day!(c, st, string(d), Dict("G0019" => 500.0), 40.0 + i)
    end
    @test length(st.prices) == 7 && st.prices[end] == 48.0               # only the last 7 days
    @test pumped_input(c, st, "2024-03-06").price ≈ sum(42.0:48.0) / 7
    # a gap (a day skipped) starts over from half full
    @test isempty(pumped_input(c, st, "2024-03-08").start)
    # the state survives uc_state.json
    st2 = pumped_state_from!(PumpedState(), JSON.parse(JSON.json(pumped_state_dict(st))))
    @test st2.date == st.date && st2.soc == st.soc && st2.prices == st.prices
end

@testset "pumped carry: the day-ahead LP" begin
    # one day: cheap solar at midday, gas at night; reservoir hydro at 60 EUR/MWh
    solar = [h in 9:17 ? 20000.0 : 0.0 for h in 0:23]
    nets  = [prepare_network(30000.0, solar[h], 3000.0; hydro_reservoir_cost = 60.0,
                             pump_mw = load_pump_limits(dacfg(true), false)) for h in 1:24]
    pure  = Dict(g["name"] => g["energy_mwh"] for g in values(nets[1].gens)
                 if haskey(g, "energy_mwh") && get(g, "technology", "") == "pumped_storage")
    c     = load_pumped_carry(carrycfg(true), false)
    solve(p) = solve_da(nets, Int[], [], 0.0, HiGHS.Optimizer; pumped = p)
    tot(d)   = sum(values(d))
    half     = Dict(n => 0.5 * e for (n, e) in pure if !(n in c.mixed))

    # off: as before, no end levels reported
    r0 = solve(nothing)
    @test r0.status == "OPTIMAL" && r0.pumped_end === nothing
    # first day (no start given): half full in, half full out
    r1 = solve((start = Dict{String,Float64}(), price = nothing, mixed = c.mixed))
    @test r1.status == "OPTIMAL" && isapprox(tot(r1.pumped_end), tot(half); rtol = 1e-6)
    @test !any(n in c.mixed for n in keys(r1.pumped_end))               # mixed plants are not stores
    # stored water worth a lot: the plants end fuller than they started
    r2 = solve((start = half, price = 500.0, mixed = c.mixed))
    @test tot(r2.pumped_end) > tot(half) + 1000
    # worthless: they empty
    r3 = solve((start = half, price = 0.0, mixed = c.mixed))
    @test tot(r3.pumped_end) < 1.0
    # start empty and keep it: nothing to turbine in hour 1
    empty = Dict(n => 0.0 for n in keys(half))
    r4 = solve((start = empty, price = nothing, mixed = c.mixed))
    @test all(get(r4.sched[1], n, 0.0) <= 1e-6 for n in keys(empty))
    @test isapprox(tot(r4.pumped_end), 0.0; atol = 1e-3)
end
