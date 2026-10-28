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
#
# [da].pumped_carry (load_pumped_carry below; da.jl): pumped storage keeps its water
# from one day to the next. A pure plant starts the day at the level the day before
# ended (after balancing) and values what is left at the end of the day at
# √η_rt × the mean day-ahead price of the last `pumped_price_days` days; a mixed
# plant (a river reservoir with pumps) pumps into the reservoir and uses the SDDP
# water value. The level and the prices carry between chunks in uc_state.json.
using CSV, DataFrames, Dates

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

"""
    load_pumped_carry(cfg, scen_active; file) -> (mixed = Set(unit_id), days) or nothing

[da].pumped_carry: which pumped plants are mixed (column `kind` of
Data/pumped_storage_pump_mw.csv, from OMIE's unit list) and over how many days
the value of stored water is averaged ([da].pumped_price_days, default 7).
`nothing` when off (the default). Refuses scenario runs.
"""
function load_pumped_carry(cfg, scen_active::Bool; file = PUMP_MW_FILE)
    da = get(cfg, "da", Dict{String,Any}())
    on = get(da, "pumped_carry", false)
    on isa Bool || error("config.toml: [da].pumped_carry must be true or false")
    on || return nothing
    scen_active && error("config.toml: [da].pumped_carry is for the 2024 path only; set it to false")
    days = get(da, "pumped_price_days", 7)
    days isa Integer && days >= 1 || error("config.toml: [da].pumped_price_days must be an integer >= 1")
    isfile(file) || error("[da].pumped_carry: $file not found (python omie_conversion/build_pump_mw.py)")
    df = CSV.read(file, DataFrame; types = Dict(:unit_id => String, :kind => String))
    "kind" in names(df) || error("$file has no `kind` column (python omie_conversion/build_pump_mw.py)")
    all(in(("pure", "mixed")), df.kind) || error("$file: `kind` must be pure or mixed")
    return (mixed = Set(df.unit_id[df.kind .== "mixed"]), days = Int(days))
end

"What a day hands to the next under [da].pumped_carry."
mutable struct PumpedState
    date::String                    # the day these values are the end of ("" = none yet)
    soc::Dict{String,Float64}       # pure plants' level at the end of that day [MWh]
    prices::Vector{Float64}         # mean day-ahead price of that day and the days before [EUR/MWh]
end
PumpedState() = PumpedState("", Dict{String,Float64}(), Float64[])

"""
    pumped_input(carry, st, date_str) -> solve_da's `pumped` argument, or nothing

Continues from `st` when it ends the day before `date_str`; otherwise (a run's
first day, or a gap) the plants start half full and keep that level that day.
The same input serves every stage of the day.
"""
function pumped_input(carry, st::PumpedState, date_str)
    carry === nothing && return nothing
    cont = st.date == string(Date(date_str) - Day(1))
    return (start = cont ? st.soc : Dict{String,Float64}(),
            price = cont && !isempty(st.prices) ? sum(st.prices) / length(st.prices) : nothing,
            mixed = carry.mixed)
end

"""
    pumped_end_of_day!(carry, st, date_str, soc_end, da_price)

After the day's last stage: its end levels become the next day's start, and the
day's mean day-ahead price joins the last `carry.days` days.
"""
function pumped_end_of_day!(carry, st::PumpedState, date_str, soc_end, da_price::Real)
    cont   = st.date == string(Date(date_str) - Day(1))
    prices = vcat(cont ? st.prices : Float64[], Float64(da_price))
    length(prices) > carry.days && (prices = prices[end-carry.days+1:end])
    st.date, st.soc, st.prices = String(date_str), Dict{String,Float64}(soc_end), prices
    return st
end

"For uc_state.json: the state as a Dict, and back."
pumped_state_dict(st::PumpedState) = Dict("date" => st.date, "soc" => st.soc, "prices" => st.prices)
function pumped_state_from!(st::PumpedState, d)
    st.date   = String(d["date"])
    st.soc    = Dict{String,Float64}(String(k) => Float64(v) for (k, v) in d["soc"])
    st.prices = Float64.(collect(d["prices"]))
    return st
end
