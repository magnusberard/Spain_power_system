# ============================================================
# Step RD7 of redispatch_realism/: upward reserve in the real-time redispatch
# ([redispatch.reserve], off by default).
#
# 89 % of what REE turned up in real time in 2024 (4.8 of 5.4 TWh, about 1.1
# of the 1.28 bn EUR real-time cost) was for "too little upward reserve": the
# running units' spare capacity did not cover the reserve REE needs, so REE
# started more units (e·sios cause RSI; CEER 2021 on Spanish real-time
# redispatch).  The model had nothing like it.  Here, per hour:
#
#   1. before solving: headroom = Σ over running reserve providers of
#      (maximum − scheduled output); if it is below the requirement, start the
#      cheapest offline CCGT/coal candidates (cost per MW of headroom they add)
#      until it is covered — a started unit adds (maximum − minimum load);
#   2. in the solve: Σ (pmax − pg) over the running providers ≥ requirement,
#      so the redispatch cannot spend the headroom.
#
# Requirement = REE's assigned aFRR upward band that hour (I90DIA05, built into
# a file by redispatch_realism/build_reserve_requirement.py) × scale + extra_mw.
# Providers: gas (CCGT, gas turbine), coal, reservoir and pumped hydro that are
# running (RD3's "online": reactive power not taken away).  Uses RD9's start-up
# terms and writes its starts to rd_startups.csv with zone = "reserve".
# ============================================================

function load_rd_reserve(cfg)
    c = get(get(cfg, "redispatch", Dict()), "reserve", Dict())
    get(c, "enabled", false) || return nothing
    f = String(c["requirement_file"])
    f = isabspath(f) ? f : joinpath(@__DIR__, f)
    req = Dict{Tuple{String,Int},Float64}()
    for r in eachrow(CSV.read(f, DataFrame))
        req[(string(r.date), Int(r.hour))] = Float64(r.afrr_up_mw)
    end
    @printf "  [redispatch.reserve] requirement for %d hours\n" length(req)
    return (req = req, scale = Float64(get(c, "scale", 1.0)), extra_mw = Float64(get(c, "extra_mw", 0.0)),
            offline_hydro = Bool(get(c, "offline_hydro_counts", true)),
            providers = Set(lowercase.(String.(get(c, "providers",
                ["Gas:Combined_cycle", "Gas:Gas_turbine", "Coal", "Hydro:reservoir", "Hydro:pumped_storage"])))))
end

const RD_CURRENT_RESERVE = Ref(0.0)      # MW needed in the hour being solved

rd_reserve_need(rs, date_str, hour) =
    rs === nothing ? 0.0 : rs.scale * get(rs.req, (date_str, hour), 0.0) + rs.extra_mw

rd_is_provider(rs, g) = lowercase(g["fuel"]) in rs.providers ||
                        lowercase("$(g["fuel"]):$(g["technology"])") in rs.providers

# Provider that counts: running — RD3 left (or a start-up gave) it reactive power,
# or it is scheduled away from 0 — or, with offline_hydro_counts, reservoir and
# pumped hydro even when stopped: they synchronise within minutes and carry much
# of Spain's aFRR band, which the model's market stages do not schedule.
rd_provider_on(rs, g) = rd_is_provider(rs, g) &&
    (!su_is_off(g) || abs(get(g, "pg", 0.0)) > 1e-6 || (rs.offline_hydro && g["fuel"] == "Hydro"))

"""
    commit_for_reserve!(network, su, date_str, hour) -> units started

Start the cheapest offline candidates until the running providers' headroom
(maximum − scheduled output) covers the hour's requirement.
"""
function commit_for_reserve!(network, su, date_str, hour)
    rs = su.reserve
    rs === nothing && return 0
    need = rd_reserve_need(rs, date_str, hour)
    RD_CURRENT_RESERVE[] = need
    need > 0 || return 0
    gens = network["gen"]
    head(g) = (g["pmax"] - g["pg"]) * BASEMVA
    have = sum((head(g) for (_, g) in gens if rd_provider_on(rs, g)); init = 0.0)
    have >= need && return 0
    add(g) = (Float64(get(g, "installed_mw", g["pmax"] * BASEMVA)) * (1 - su_terms(su, g)[1]))
    cands = [g for (_, g) in gens if su_is_off(g) && su_is_candidate(su, g) && add(g) > 1.0]
    sort!(cands; by = g -> su_terms(su, g)[3] / add(g))           # EUR per MW of headroom
    n = 0
    for g in cands
        have >= need && break
        pmin_mw, start = su_commit!(su, g)
        have += g["pmax"] * BASEMVA - pmin_mw
        n += 1
        push!(RD_STARTUP_ROWS, (date = date_str, hour = hour, round = -1, unit = g["name"],
                                fuel = g["fuel"], technology = g["technology"], bus_i = g["gen_bus"],
                                min_load_mw = round(pmin_mw; digits = 1), start_cost_eur = round(start; digits = 0),
                                trigger_bus_i = 0, trigger_slack_mvar = NaN, hops = -1,
                                zone = "reserve", zone_need = round(Int, need), zone_online = round(Int, have)))
    end
    have < need && @printf "    reserve: %.0f of %.0f MW headroom after starting %d unit(s)\n" have need n
    return n
end

"""
    rd_add_reserve!(pm, gens, need_mw)

Σ (pmax − pg) over the running providers ≥ need (what headroom exists).
"""
function rd_add_reserve!(pm, gens, rs, need_mw)
    (rs === nothing || need_mw <= 0) && return
    on = [g for (_, g) in gens if rd_provider_on(rs, g)]
    isempty(on) && return
    avail = sum(g["pmax"] for g in on) * BASEMVA
    rhs = min(need_mw, 0.98 * avail)                               # never more than exists
    JuMP.@constraint(pm.model, sum(g["pmax"] - PowerModels.var(pm, :pg, g["index"]) for g in on) >= rhs / BASEMVA)
    return
end
