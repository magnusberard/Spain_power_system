# [run].remove_pumping: take the real 2024 pumping out of the 2024 load.
#
# The 2024 load (Data/ES_old/load, omie_conversion/convert_omie_to_model_data.py)
# is OMIE's day-ahead production + imports, so it also holds what the real pumps
# bought (6.2 TWh in 2024, mostly at midday). The model's own pumped storage then
# pumps on top of it: pumping counted twice. With the switch on, every stage's
# load is the old load minus that hour's real day-ahead pumping (REE e·sios 25,
# Data/OMIE/pumping_2024.csv from omie_conversion/build_pumping_2024.py), and the
# model's pumps decide when to buy and sell, as in the 2035 runs. The same MW go
# out of every stage, so the stage-to-stage forecast changes stay as they were.
#
# 2024 path only: EMPIRE's 2035 demand is consumption, with storage modelled
# separately (Node_ElectricAnnualDemand.tab vs storPW/storENInstalledCap.tab).
#
# [da].pump_limits (load_pump_limits below): each pumped-storage plant pumps with
# its own pumping power instead of its full capacity.
using CSV, DataFrames

const PUMPING_FILE = joinpath(@__DIR__, "Data", "OMIE", "pumping_2024.csv")

"""
    load_pumping(cfg, scen_active; file) -> Dict(date => 24 MW) or nothing

`nothing` when [run].remove_pumping is off (the default). Refuses scenario runs.
"""
function load_pumping(cfg, scen_active::Bool; file = PUMPING_FILE)
    on = get(get(cfg, "run", Dict{String,Any}()), "remove_pumping", false)
    on isa Bool || error("config.toml: [run].remove_pumping must be true or false")
    on || return nothing
    scen_active && error("config.toml: [run].remove_pumping is for the 2024 path only " *
                         "(EMPIRE's demand already leaves pumping out); set it to false")
    isfile(file) || error("[run].remove_pumping: $file not found " *
                          "(python omie_conversion/build_pumping_2024.py)")
    df = CSV.read(file, DataFrame; types = Dict(:date => String))
    pump = Dict{String,Vector{Float64}}()
    for g in groupby(sort(df, [:date, :hour]), :date)
        g.hour == 0:23 || error("$file: $(g.date[1]) does not have hours 0-23")
        all(>=(0), g.pumping_mw) || error("$file: negative pumping on $(g.date[1])")
        pump[g.date[1]] = Float64.(g.pumping_mw)
    end
    return pump
end

const PUMP_MW_FILE = joinpath(@__DIR__, "Data", "pumped_storage_pump_mw.csv")

"""
    load_pump_limits(cfg, scen_active; file) -> Dict(unit_id => pumping MW) or nothing

[da].pump_limits: each pumped-storage plant pumps with its own pumping power
(Data/pumped_storage_pump_mw.csv, omie_conversion/build_pump_mw.py) instead of
its full capacity; data_preparation.jl sets pmin = −pump_mw. `nothing` when
off (the default). Refuses scenario runs.
"""
function load_pump_limits(cfg, scen_active::Bool; file = PUMP_MW_FILE)
    on = get(get(cfg, "da", Dict{String,Any}()), "pump_limits", false)
    on isa Bool || error("config.toml: [da].pump_limits must be true or false")
    on || return nothing
    scen_active && error("config.toml: [da].pump_limits is for the 2024 path only " *
                         "(EMPIRE sizes pumped storage itself); set it to false")
    isfile(file) || error("[da].pump_limits: $file not found (python omie_conversion/build_pump_mw.py)")
    df = CSV.read(file, DataFrame; types = Dict(:unit_id => String))
    all(x -> !ismissing(x) && x > 0, df.pump_mw) || error("$file: every pump_mw must be > 0")
    return Dict(String(r.unit_id) => Float64(r.pump_mw) for r in eachrow(df))
end

"""
    remove_pumping!(pump, tables...)

Subtract the real pumping from `load_mw` in each stage table (columns date,
hour, load_mw). Every date in the tables must be in `pump`.
"""
function remove_pumping!(pump, tables...)
    for t in tables, r in eachrow(t)
        haskey(pump, r.date) || error("[run].remove_pumping: no pumping for $(r.date) in $PUMPING_FILE")
        r.load_mw -= pump[r.date][r.hour+1]
    end
    return nothing
end
