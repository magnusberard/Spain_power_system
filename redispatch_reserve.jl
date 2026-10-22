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
#
# Step E1, `tertiary = true` (off by default): P.O. 1.5 (BOE-A-2022-4969, in force
# in 2024) also requires tertiary reserve, upward "the largest loss of production
# from a single failure, increased by 2 % of the forecast demand" (§4.3),
# deliverable within 15 minutes.  The requirement becomes aFRR band + largest
# scheduled single unit + tertiary_demand_share × demand, and with
# tertiary_ramp15 a running thermal unit's headroom counts only up to what it can
# ramp in 15 minutes (Data/power_unit_tech_params.csv, sustained rates; hydro and
# storage are not ramp-limited, as in [da].ramp_limits).  Each hour's
# requirement and headroom go to rd_reserve.csv.  Not yet included: §4.4's
# supplementary reserve (REE's own forecasts against the market schedules), step E2.
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
    tertiary = Bool(get(c, "tertiary", false))
    return (req = req, scale = Float64(get(c, "scale", 1.0)), extra_mw = Float64(get(c, "extra_mw", 0.0)),
            offline_hydro = Bool(get(c, "offline_hydro_counts", true)),
            tertiary = tertiary,                                                     # step E1
            tertiary_share = Float64(get(c, "tertiary_demand_share", 0.02)),
            ramp15 = tertiary && Bool(get(c, "tertiary_ramp15", true)) ? load_ramp_rates() : nothing,
            providers = Set(lowercase.(String.(get(c, "providers",
                ["Gas:Combined_cycle", "Gas:Gas_turbine", "Coal", "Hydro:reservoir", "Hydro:pumped_storage"])))))
end

const RD_CURRENT_RESERVE = Ref(0.0)      # MW needed in the hour being solved
const RD_RESERVE_ROWS = NamedTuple[]      # per hour: requirement and headroom → rd_reserve.csv

# Headroom a provider can deliver within 15 minutes (pu): with tertiary_ramp15, a
# ramp-limited unit (thermal) up to a quarter of its hourly ramp; others in full.
function rd_head15(rs, g)
    h = g["pmax"] - g["pg"]
    rs.ramp15 === nothing && return h
    rr = get(rs.ramp15, (String(g["fuel"]), String(g["technology"])), nothing)
    rr === nothing && return h
    return min(h, rr * Float64(get(g, "installed_mw", g["pmax"] * BASEMVA)) / BASEMVA / 4)
end
rd_cap15(rs, g) = rd_head15(rs, merge(g, Dict("pg" => 0.0)))   # 15-minute cap from zero output

# P.O. 1.5 §4.3: the largest single loss of production (the largest scheduled unit)
# and the demand, from the hour's network.
function rd_tertiary_parts(network)
    pseudo(n) = any(p -> startswith(n, p), ("LS_", "SLACK", "XB_", "RX_", "BESS_"))
    loss = maximum((g["pg"] * BASEMVA for (_, g) in network["gen"] if !pseudo(String(g["name"]))); init = 0.0)
    demand = sum((l["pd"] for (_, l) in network["load"]); init = 0.0) * BASEMVA
    return loss, demand
end

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
    afrr = rd_reserve_need(rs, date_str, hour)
    loss, demand = rs.tertiary ? rd_tertiary_parts(network) : (0.0, 0.0)
    need = afrr + loss + rs.tertiary_share * demand * rs.tertiary            # step E1: + tertiary (P.O. 1.5 §4.3)
    RD_CURRENT_RESERVE[] = need
    need > 0 || return 0
    gens = network["gen"]
    head(g) = rd_head15(rs, g) * BASEMVA
    have = sum((head(g) for (_, g) in gens if rd_provider_on(rs, g)); init = 0.0)
    have0 = have
    rs.tertiary && push!(RD_RESERVE_ROWS, (date = date_str, hour = hour, afrr_mw = round(afrr; digits = 1),
                                           largest_loss_mw = round(loss; digits = 1),
                                           demand_part_mw = round(rs.tertiary_share * demand; digits = 1),
                                           need_mw = round(need; digits = 1), headroom_mw = round(have0; digits = 1)))
    have >= need && return 0
    function add(g)
        inst = Float64(get(g, "installed_mw", g["pmax"] * BASEMVA))
        a = inst * (1 - su_terms(su, g)[1])
        rr = rs.ramp15 === nothing ? nothing : get(rs.ramp15, (String(g["fuel"]), String(g["technology"])), nothing)
        return rr === nothing ? a : min(a, rr * inst / 4)
    end
    cands = [g for (_, g) in gens if su_is_off(g) && su_is_candidate(su, g) && add(g) > 1.0]
    sort!(cands; by = g -> su_terms(su, g)[3] / add(g))           # EUR per MW of headroom
    n = 0
    for g in cands
        have >= need && break
        pmin_mw, start = su_commit!(su, g)
        have += head(g)
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
    if rs.ramp15 === nothing
        avail = sum(g["pmax"] for g in on) * BASEMVA
        rhs = min(need_mw, 0.98 * avail)                           # never more than exists
        JuMP.@constraint(pm.model, sum(g["pmax"] - PowerModels.var(pm, :pg, g["index"]) for g in on) >= rhs / BASEMVA)
        return
    end
    # step E1, tertiary_ramp15: each provider's counted headroom h ≤ pmax − pg and
    # h ≤ its 15-minute ramp; Σ h ≥ need
    avail = sum(min(g["pmax"], rd_cap15(rs, g)) for g in on) * BASEMVA
    rhs = min(need_mw, 0.98 * avail)
    hs = JuMP.AffExpr(0.0)
    for g in on
        h = JuMP.@variable(pm.model, lower_bound = 0.0, upper_bound = max(rd_cap15(rs, g), 0.0))
        JuMP.@constraint(pm.model, h <= g["pmax"] - PowerModels.var(pm, :pg, g["index"]))
        JuMP.add_to_expression!(hs, h)
    end
    JuMP.@constraint(pm.model, hs >= rhs / BASEMVA)
    return
end

function write_rd_reserve(dir)
    isempty(RD_RESERVE_ROWS) && return
    CSV.write(joinpath(dir, "rd_reserve.csv"), DataFrame(RD_RESERVE_ROWS))
    @printf "  rd_reserve.csv   : %d hours (requirement: aFRR + largest loss + demand share; headroom)\n" length(RD_RESERVE_ROWS)
end
