# Tests for participation.jl ([participation] shares, [balancing].eligible).
#     julia --project=. scripts/test_participation.jl
using Test, DataFrames
include(joinpath(@__DIR__, "..", "participation.jl"))

table(f) = DataFrame(date = fill("2024-07-01", 24), hour = 0:23,
                     load_mw = [f(h, 1) for h in 0:23], wind_mw = [f(h, 2) for h in 0:23],
                     solar_mw = [f(h, 3) for h in 0:23])
tables() = (table((h, k) -> 1000.0 * k + h), table((h, k) -> 1000.0 * k + h + 100),
            table((h, k) -> 1000.0 * k + h + 200), table((h, k) -> 1000.0 * k + h + 300))
shares(id2, id3, cid) = Dict("id2" => Dict(s => id2 for s in PARTICIPATION_SOURCES),
                             "id3" => Dict(s => id3 for s in PARTICIPATION_SOURCES),
                             "cid" => Dict(s => cid for s in PARTICIPATION_SOURCES))

@testset "participation" begin
    # α = 1 everywhere: nothing changes, bit for bit
    da, id2, id3, cid = tables(); ref = deepcopy((id2, id3, cid))
    apply_participation!(da, id2, id3, cid, shares(1.0, 1.0, 1.0))
    @test (id2, id3, cid) == ref
    @test !participation_active(shares(1.0, 1.0, 1.0))
    @test participation_active(shares(1.0, 1.0, 0.07))

    # α = 0 everywhere (passive): every intraday stage plans with the DA forecast;
    # ID3's untraded hours 0–11 are left alone
    da, id2, id3, cid = tables(); id3_early = id3[1:12, :]
    apply_participation!(da, id2, id3, cid, shares(0.0, 0.0, 0.0))
    @test id2.load_mw == da.load_mw
    @test id3.wind_mw[13:24] == da.wind_mw[13:24]
    @test id3[1:12, :] == id3_early
    @test cid.solar_mw == da.solar_mw

    # CID only, α = 0.5: hours 0–11 move half-way from ID2, hours 12–23 from ID3
    da, id2, id3, cid = tables()
    apply_participation!(da, id2, id3, cid, shares(1.0, 1.0, 0.5))
    @test cid.load_mw[1] ≈ id2.load_mw[1] + 0.5 * (1300.0 - id2.load_mw[1])   # 1200
    @test cid.load_mw[13] ≈ id3.load_mw[13] + 0.5 * (1312.0 - id3.load_mw[13]) # 1262
    @test cid.load_mw[1] ≈ 1200.0 && cid.load_mw[13] ≈ 1262.0

    # ID3 off: CID's base is ID2 in every hour
    da, id2, id3, cid = tables()
    apply_participation!(da, id2, id3, cid, shares(1.0, 1.0, 0.0); id3_on = false)
    @test cid.wind_mw == id2.wind_mw

    # source-specific shares
    da, id2, id3, cid = tables()
    sh = shares(1.0, 1.0, 1.0); sh["cid"]["wind"] = 0.0
    apply_participation!(da, id2, id3, cid, sh)
    @test cid.wind_mw[1] == id2.wind_mw[1] && cid.load_mw[1] == 1300.0

    @test_throws ErrorException load_participation(Dict("participation" => Dict("cid" => Dict("wind" => 1.5))))
    @test load_participation(Dict())["cid"]["load"] == 1.0
    bad = table((h, k) -> 0.0); bad.hour[1] = 5
    @test_throws ErrorException blend_stage!(bad, table((h, k) -> 0.0), sh["cid"])
end

@testset "balancing eligibility" begin
    el = ["Gas:Combined_cycle", "Gas:Gas_turbine", "Coal", "Hydro:reservoir",
          "Hydro:pumped_storage", "Battery"]
    @test bal_may_move("Gas", "CHP", String[])                 # empty list: everyone
    @test bal_may_move("Gas", "Combined_cycle", el)
    @test bal_may_move("Gas", "combined_cycle", el)
    @test !bal_may_move("Gas", "CHP", el)                      # CHP block holds
    @test bal_may_move("Coal", "Coal", el)
    @test !bal_may_move("Hydro", "run_of_river", el)
    @test !bal_may_move("Hydro", "mini_hydro", el)
    @test !bal_may_move("Biomass", "CHP_Waste", el)
    @test bal_may_move("Wind", "Onshore", el) && bal_may_move("Solar", "PV", el)
    @test bal_may_move("Battery", "Li-Ion", el) && bal_may_move("Slack", "Slack", el)

    gen(name, fuel, tech) = Dict{String,Any}("name" => name, "fuel" => fuel, "technology" => tech,
                                              "pmin" => 0.0, "pmax" => 5.0, "pg0" => 2.5)
    nets = [Dict("gen" => Dict("1" => gen("CCGT1", "Gas", "Combined_cycle"),
                               "2" => gen("CHP_GAS_X", "Gas", "CHP"),
                               "3" => gen("ROR1", "Hydro", "run_of_river"))) for _ in 1:2]
    day_ts = DataFrame(date = ["2024-07-01", "2024-07-01"], hour = [0, 1])
    hold = Dict(("2024-07-01", 0) => Dict("CCGT1" => 300.0, "CHP_GAS_X" => 120.0, "ROR1" => 40.0))
    @test hold_units!(nets, day_ts, "2024-07-01", hold, el, 100.0) == 2   # hour 1 has no schedule
    g = nets[1]["gen"]
    @test g["1"]["pmax"] == 5.0                                          # eligible: free
    @test g["2"]["pmin"] == g["2"]["pmax"] == 1.2                        # held at 120 MW
    @test g["3"]["pmin"] == g["3"]["pmax"] == 0.4
    @test nets[2]["gen"]["2"]["pmax"] == 5.0
end
