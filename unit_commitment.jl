# ============================================================
# Unit commitment of the combined-cycle gas fleet in the day-ahead market
# ============================================================
# With [unit_commitment] on, every CCGT of at least `min_mw` is either OFF or
# running between its minimum load and its maximum, pays a start-up cost each
# time it starts, and respects a minimum up and down time.  solve_da (da.jl)
# adds the binaries; this file only builds each unit's numbers for one day.
# The price comes from a second LP solve with the on/off decisions fixed (the
# usual "fix the integers, read the duals" rule; also what the Comillas
# simulator does, Insunza et al. 2026, SSRN 6722443).
#
# Numbers and sources (all in [unit_commitment], config.toml):
#   min up 2 h, min down 6 h           Intertek for WECC (2020), "Update of
#   min load 48 % (1x1) / 25 % (2x1)   Reliability and Cost Impacts of Flexible
#                                      Generation on Fossil-fueled Generators",
#                                      Table 2, "Typical CC [GT+HRSG+ST]".
#   start wear 52 $/MW (2020 $)        same report, Table 4, typical CC, warm
#                                      start, median ("lower bound").  To 2024
#                                      EUR: x 1.1953 (WECC's 2020->2024 $
#                                      inflator, PCDS meeting 28 Feb 2024)
#                                      / 1.0824 (ECB annual average 2024, USD
#                                      per EUR, EXR.A.USD.EUR.SP00.A)
#                                      = 57.4 EUR/MW.
#   start fuel 1.5 MWh gas per MW      DIW Data Documentation 68 (Schröder et
#                                      al. 2013), Table 25, CCGT hot/warm start,
#                                      citing Meibom et al. (2008).  Priced at
#                                      the day's gas price PLUS its CO2
#                                      (gas_fuel_cost_th, fuel_prices.jl).
# ASSUMPTION (ours): units of `two_by_one_min_mw` (700 MW) or more are 2x1
# (two gas turbines + one steam turbine) and get the 2x1 minimum load.  Neither
# generations.csv nor GEM gives the layout; the 54 Spanish CCGTs of 100 MW or
# more split into 43 of 200-435 MW and 11 of 782-859 MW with none between, and
# ~400 MW is a typical 1x1, ~800 MW a typical 2x1.
#
# Simplification (Part 1): no carry-over between days — a unit running in the
# first hour counts as already on (no start cost in hour 1), and the minimum
# down time only binds inside the day.
# ============================================================

struct UCUnit
    name       :: String    # generations.csv unit_id
    mw         :: Float64   # capacity this day (max pmax over the day)
    min_load   :: Float64   # fraction of the hour's pmax
    min_up     :: Int       # hours
    min_down   :: Int       # hours
    start_cost :: Float64   # EUR per start
end

"""
    load_uc_config(cfg) -> NamedTuple or nothing

The [unit_commitment] settings; `nothing` when the switch is off.
"""
function load_uc_config(cfg)
    c = get(cfg, "unit_commitment", Dict())
    get(c, "enabled", false) || return nothing
    wear_eur = Float64(c["start_wear_usd_per_mw"]) * Float64(c["usd_inflator_to_2024"]) /
               Float64(c["usd_per_eur"])
    return (min_mw            = Float64(get(c, "min_mw", 100.0)),
            min_up            = Int(c["min_up_h"]),
            min_down          = Int(c["min_down_h"]),
            min_load_1x1      = Float64(c["min_load_1x1"]),
            min_load_2x1      = Float64(c["min_load_2x1"]),
            two_by_one_min_mw = Float64(c["two_by_one_min_mw"]),
            wear_eur_per_mw   = wear_eur,
            start_fuel_mwh_per_mw = Float64(c["start_fuel_mwh_per_mw"]),
            mip_gap           = Float64(get(c, "mip_gap", 1e-4)),
            time_limit_s      = Float64(get(c, "time_limit_s", 600.0)))
end

"""
    uc_units_for(nets, date_str, ucc, fp) -> Dict{String,UCUnit}

The committed units for one day: every Gas/Combined_cycle unit in `nets`
whose largest hourly pmax is at least `ucc.min_mw`.
"""
function uc_units_for(nets, date_str, ucc, fp)
    fuel_th = gas_fuel_cost_th(fp, Date(String(date_str)))      # EUR/MWh of gas
    start_eur_per_mw = ucc.wear_eur_per_mw + ucc.start_fuel_mwh_per_mw * fuel_th
    mw = Dict{String,Float64}()
    for net in nets, (_, g) in net.gens
        (g["fuel"] == "Gas" && g["technology"] == "Combined_cycle") || continue
        mw[g["name"]] = max(get(mw, g["name"], 0.0), g["pmax"] * BASEMVA)
    end
    units = Dict{String,UCUnit}()
    for (name, m) in mw
        m >= ucc.min_mw || continue
        ml = m >= ucc.two_by_one_min_mw ? ucc.min_load_2x1 : ucc.min_load_1x1
        units[name] = UCUnit(name, m, ml, ucc.min_up, ucc.min_down, start_eur_per_mw * m)
    end
    return units
end
