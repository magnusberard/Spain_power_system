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
#
# Step E2, `rule = "e2"` (off by default; best effort decided 5 Nov 2026, vault
# real-time-reserve-trigger): REE's reserve mechanism with the trigger the E2 tests
# came closest with (redispatch_realism/e2_rule.py, window from data/e2_window_2024.json):
#   requirement_t = mFRR requirement (e·sios 1788) + assigned aFRR band (632)
#                   + P.O. 1.5 §4.4 gaps (REE's D+1 forecasts against the after-intraday
#                   programme), file from redispatch_realism/build_rt_reserve_requirement.py
#   available_t   = from the model's own real-time starting schedule (balancing + phase I):
#                   running CCGT/coal (> 1 MW): capacity − output; running pumped-storage
#                   turbine: capacity − output; pumping pumped storage: the pumping (it can
#                   stop).  Peninsular units only; reservoir hydro and gas turbines do not count.
#   shortfall_t   = max(0, requirement_t − available_t);  x_t = max of the shortfall over
#                   [t − window_back, t + window_ahead] (1 and 1: REE starts ahead and holds)
# Remedy, P.O. 3.2: start offline CCGT/coal candidates at minimum load, cheapest start
# per MW of headroom they add, until the hour's headroom is available_t + x_t; the solve
# then keeps that headroom.  The trigger reproduced the timing of REE's identified need
# (hourly corr 0.55 Jul–Dec 2024, 0.58 in 2023) but not its size (failed the pass marks);
# results carry that caveat.  Every real-time hour is solved on its own, so the window is
# taken per day before the hours are solved (e2_prepare_hour!), from the day's schedules.
# ============================================================

function load_rd_reserve(cfg)
    c = get(get(cfg, "redispatch", Dict()), "reserve", Dict())
    get(c, "enabled", false) || return nothing
    rule = Symbol(get(c, "rule", "afrr"))
    rule in (:afrr, :e2) || error("[redispatch.reserve].rule must be \"afrr\" or \"e2\", not \"$rule\"")
    req = Dict{Tuple{String,Int},Float64}()
    po15 = nothing
    if rule == :e2 && String(get(c, "e2_requirement", "file")) == "po15"
        # runs without REE's published requirement (2035; 9 Nov 2026): P.O. 1.5's own terms, build_rt_reserve_formula.py.
        # rd_reserve_po15_base! fills req per hour from the DA demand, wind and solar (aFRR by hour + 2 % of demand +
        # forecast gaps); e2_req adds §4.3's largest single loss, the largest scheduled nuclear/CCGT/coal unit
        f = String(get(c, "e2_formula_file", "redispatch_realism/data/rt_reserve_formula.csv"))
        f = isabspath(f) ? f : joinpath(@__DIR__, f)
        t = CSV.read(f, DataFrame)
        par(p) = Float64(only(t.value[t.part .== p]))
        afrr = [Float64(only(t.value[(t.part .== "afrr") .& (t.hour .== h)])) for h in 0:23]
        po15 = (afrr = afrr, share = par("demand_share"), g_d = par("gap_demand"), g_w = par("gap_wind"), g_s = par("gap_solar"))
        @printf "  [redispatch.reserve] rule e2, requirement from P.O. 1.5's terms (%s): aFRR %.0f-%.0f MW, %.1f %% of demand + gaps %.2f / %.2f / %.2f %% of demand / wind / solar + the largest scheduled unit\n" basename(f) minimum(afrr) maximum(afrr) 100 * po15.share 100 * po15.g_d 100 * po15.g_w 100 * po15.g_s
    else
        f = String(rule == :e2 ? get(c, "e2_requirement_file", "redispatch_realism/data/rt_reserve_requirement_2024.csv") :
                                 c["requirement_file"])
        f = isabspath(f) ? f : joinpath(@__DIR__, f)
        col = rule == :e2 ? :requirement_mw : :afrr_up_mw
        for r in eachrow(CSV.read(f, DataFrame))
            req[(string(r.date), Int(r.hour))] = Float64(r[col])
        end
        @printf "  [redispatch.reserve] rule %s: requirement for %d hours (%s)\n" rule length(req) basename(f)
    end
    tertiary = rule == :afrr && Bool(get(c, "tertiary", false))                 # E1 belongs to the aFRR rule
    return (req = req, scale = Float64(get(c, "scale", 1.0)), extra_mw = Float64(get(c, "extra_mw", 0.0)),
            rule = rule,                                                             # step E2
            po15 = po15,                                                             # P.O. 1.5 terms, or nothing
            # fix A (10 Nov 2026): start a unit for reserve only if its bus can export its minimum load (e2_bus_room)
            deliverable = Bool(get(c, "e2_deliverable", false)),
            window_ahead = Int(get(c, "window_ahead", 1)), window_back = Int(get(c, "window_back", 1)),
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

# ── Step E2 (rule = "e2") ─────────────────────────────────────────────────────
const E2_PROVIDERS = Set(["gas:combined_cycle", "coal", "hydro:pumped_storage"])
const E2_UNITS = Dict{String,Tuple{Float64,Bool}}()     # unit → (capacity MW, pumped storage?), for E2_UNITS_DATE
const E2_UNITS_DATE = Ref("")
const E2_WINDOW = Dict{Tuple{String,Int},Float64}()     # (date, hour) → x_t, the window's shortfall (MW)
const E2_AVAIL = Dict{Tuple{String,Int},Float64}()      # (date, hour) → available_t from the schedule (MW)
const E2_SCHED = Ref{Any}(nothing)                      # the hour being solved: its starting schedule
const E2_STARTED = Dict{String,Tuple{String,Int}}()     # unit → last (date, hour) this rule had it on

e2_is_provider(g) = lowercase(String(g["fuel"])) in E2_PROVIDERS ||
                    lowercase("$(g["fuel"]):$(g["technology"])") in E2_PROVIDERS

# Available reserve of one unit at output p (MW), as in e2_rule.py.
e2_head(cap_mw, pumped, p) = p > 1.0 ? max(cap_mw - p, 0.0) : (pumped && p < -1.0 ? -p : 0.0)

# Real time's starting schedule for an hour, as the real-time loop builds it.
function e2_sched(date_str, hour)
    s = rd_sched_for(date_str, hour)
    (s === nothing || RD_STARTUPS === nothing || RD_STARTUPS.phase1 === nothing) && return s
    return phase1_anchor(s, date_str, hour)
end

e2_avail(s) = sum((e2_head(cap, pumped, Float64(get(s, n, 0.0))) for (n, (cap, pumped)) in E2_UNITS); init = 0.0)

const E2_BIG = Set{String}()     # po15: the units whose loss §4.3 counts (nuclear, CCGT, coal), for E2_UNITS_DATE

"P.O. 1.5 mode: the hour's requirement without the largest loss, from the DA demand, wind and solar (MW)."
function rd_reserve_po15_base!(rs, date_str, hour, load_mw, wind_mw, solar_mw)
    (rs === nothing || !hasproperty(rs, :po15) || rs.po15 === nothing) && return 0.0
    p = rs.po15
    rs.req[(date_str, hour)] = p.afrr[hour + 1] + (p.share + p.g_d) * load_mw + p.g_w * wind_mw + p.g_s * solar_mw
end

"The hour's E2 requirement (MW, before scale and extra), or nothing: with po15, plus the largest scheduled unit in s."
function e2_req(rs, ds, h, s)
    r = get(rs.req, (ds, h), nothing)
    (r === nothing || !hasproperty(rs, :po15) || rs.po15 === nothing) && return r
    big = s === nothing ? 0.0 : maximum((Float64(get(s, n, 0.0)) for n in E2_BIG); init = 0.0)
    return r + big
end

"""
    e2_prepare_hour!(network, su, date_str, sched)

Before the hour's commitments: keep the hour's schedule and, on a day's first hour, take the day's
provider units from the network (capacity: installed MW for CCGT/coal, as a start gives them — coal is
frozen at its schedule in real time; pumped storage its turbine maximum) and each hour's x_t from the
day's schedules, with the neighbouring days' edge hours where their schedules exist.
"""
function e2_prepare_hour!(network, su, date_str, sched)
    rs = su.reserve
    (rs === nothing || rs.rule != :e2) && return
    E2_SCHED[] = sched
    E2_UNITS_DATE[] == date_str && return
    empty!(E2_UNITS); empty!(E2_BIG)
    bus = network["bus"]
    for (_, g) in network["gen"]
        ISLAND_BUSES !== nothing && String(bus[string(g["gen_bus"])]["name"]) in ISLAND_BUSES && continue
        (String(g["fuel"]) in ("Nuclear", "Coal") || (String(g["fuel"]) == "Gas" && String(g["technology"]) == "Combined_cycle")) &&
            startswith(String(g["name"]), "G") && push!(E2_BIG, String(g["name"]))
        e2_is_provider(g) || continue
        pumped = lowercase(String(g["technology"])) == "pumped_storage"
        cap = pumped ? g["pmax"] * BASEMVA : Float64(get(g, "installed_mw", g["pmax"] * BASEMVA))
        E2_UNITS[String(g["name"])] = (cap, pumped)
    end
    E2_UNITS_DATE[] = date_str
    d = Date(date_str)
    A, B = rs.window_ahead, rs.window_back
    keys_ = vcat([(string(d - Day(1)), h) for h in (24 - B):23], [(date_str, h) for h in 0:23],
                 [(string(d + Day(1)), h) for h in 0:(A - 1)])
    short = Dict{Int,Float64}()                      # position in keys_ → shortfall
    for (i, (ds, h)) in enumerate(keys_)
        haskey(rs.req, (ds, h)) || continue
        s = e2_sched(ds, h)
        s === nothing && continue
        r = e2_req(rs, ds, h, s)
        a = e2_avail(s)
        ds == date_str && (E2_AVAIL[(ds, h)] = a)
        short[i] = max(rs.scale * r + rs.extra_mw - a, 0.0)
    end
    for h in 0:23
        i = B + h + 1
        haskey(short, i) || continue                 # no requirement or no schedule this hour
        E2_WINDOW[(date_str, h)] = maximum(short[j] for j in (i - B):(i + A) if haskey(short, j))
    end
    @printf "    reserve (e2): %s, %d providers, shortfall > 0 in %d h, window > 0 in %d h\n" date_str length(E2_UNITS) count(h -> get(short, B + h + 1, 0.0) > 0, 0:23) count(h -> get(E2_WINDOW, (date_str, h), 0.0) > 0, 0:23)
    return
end

# A provider's output in the hour being solved: its schedule, or, if started in this hour
# (phase I's units, voltage zones), its minimum load; 0 when the minimum-load rule holds it off.
function e2_output(g, s)
    get(g, "pmax", 0.0) <= 0.0 && return 0.0
    p = s === nothing ? 0.0 : Float64(get(s, String(g["name"]), 0.0))
    abs(p) > 1.0 && return p
    return (!su_is_off(g) && get(g, "pmin", 0.0) > 0.0) ? g["pg"] * BASEMVA : 0.0
end

"""
    e2_bus_room(network, s) -> Dict(bus => MW)

Fix A (10 Nov 2026): what each bus can still send out, MW = the ratings of its in-service branches − (its scheduled
generation − its load). P.O. 3.2's remedy starts units to hold reserve the system can use; a unit whose bus cannot
export its minimum load gives none, and in the model it made the hour infeasible (y24rule: Besós 5 behind the single
393 MW line out of ES01113 in all 149 unsolved real-time hours).
"""
function e2_bus_room(network, s)
    cap = Dict{Int,Float64}()
    for (_, br) in network["branch"]
        Int(get(br, "br_status", 1)) == 0 && continue
        r = Float64(get(br, "rate_a", 0.0)) * BASEMVA
        for b in (Int(br["f_bus"]), Int(br["t_bus"]))
            cap[b] = get(cap, b, 0.0) + r
        end
    end
    net = Dict{Int,Float64}()
    for (_, g) in network["gen"]
        p = e2_output(g, s)
        p == 0.0 || (net[Int(g["gen_bus"])] = get(net, Int(g["gen_bus"]), 0.0) + p)
    end
    for (_, l) in network["load"]
        b = Int(l["load_bus"])
        net[b] = get(net, b, 0.0) - Float64(l["pd"]) * BASEMVA
    end
    return Dict(b => c - get(net, b, 0.0) for (b, c) in cap)
end

function e2_commit!(network, su, date_str, hour)
    rs = su.reserve
    x = get(E2_WINDOW, (date_str, hour), 0.0)
    a0 = get(E2_AVAIL, (date_str, hour), 0.0)
    s = E2_SCHED[]
    req = rs.scale * something(e2_req(rs, date_str, hour, s), 0.0) + rs.extra_mw
    need = x > 0 ? a0 + x : 0.0                      # headroom to reach in this hour
    RD_CURRENT_RESERVE[] = need
    gens = network["gen"]
    have = 0.0
    for (_, g) in gens
        u = get(E2_UNITS, String(g["name"]), nothing)
        u === nothing || (have += e2_head(u[1], u[2], e2_output(g, s)))
    end
    have1 = have
    n = 0
    n_skip = 0
    room = (have < need && hasproperty(rs, :deliverable) && rs.deliverable) ? e2_bus_room(network, s) : nothing
    if have < need
        add(g) = E2_UNITS[String(g["name"])][1] * (1 - su_terms(su, g)[1])
        # Every real-time hour is solved on its own: a unit this rule started in the previous hour is still
        # running, so keeping it costs no new start (P.O. 3.2 pays a start once) and it goes first.
        prev = hour == 0 ? (string(Date(date_str) - Day(1)), 23) : (date_str, hour - 1)
        held(g) = get(E2_STARTED, String(g["name"]), nothing) == prev
        cost(g) = held(g) ? su_terms(su, g)[3] - su_terms(su, g)[2] : su_terms(su, g)[3]
        cands = [g for (_, g) in gens if haskey(E2_UNITS, String(g["name"])) && !E2_UNITS[String(g["name"])][2] &&
                 su_is_off(g) && su_is_candidate(su, g) && add(g) > 1.0]
        sort!(cands; by = g -> cost(g) / add(g))                  # EUR per MW of headroom (P.O. 3.2)
        for g in cands
            have >= need && break
            gain = add(g)
            if room !== nothing                                   # fix A: only what the bus can export
                b = Int(g["gen_bus"])
                ml = E2_UNITS[String(g["name"])][1] - gain        # the unit's minimum load, MW
                r = get(room, b, Inf)
                if r < ml
                    n_skip += 1
                    continue
                end
                room[b] = r - ml
                gain = min(gain, room[b])
            end
            h = held(g)
            pmin_mw, start = su_commit!(su, g)
            have += gain
            n += 1
            E2_STARTED[String(g["name"])] = (date_str, hour)
            push!(RD_STARTUP_ROWS, (date = date_str, hour = hour, round = -1, unit = g["name"],
                                    fuel = g["fuel"], technology = g["technology"], bus_i = g["gen_bus"],
                                    min_load_mw = round(pmin_mw; digits = 1),
                                    start_cost_eur = h ? 0.0 : round(start; digits = 0),
                                    trigger_bus_i = 0, trigger_slack_mvar = NaN, hops = -1,
                                    zone = h ? "reserve_held" : "reserve",
                                    zone_need = round(Int, need), zone_online = round(Int, have)))
        end
        have < need && @printf "    reserve (e2): %.0f of %.0f MW headroom after starting %d unit(s)\n" have need n
    end
    push!(RD_RESERVE_ROWS, (date = date_str, hour = hour, requirement_mw = round(req; digits = 1),
                            available_mw = round(a0; digits = 1),
                            shortfall_mw = round(max(req - a0, 0.0); digits = 1), window_mw = round(x; digits = 1),
                            headroom_before_mw = round(have1; digits = 1), started = n,
                            headroom_after_mw = round(have; digits = 1), undeliverable = n_skip))
    return n
end

# In the solve: the providers keep the headroom reached (Σ h ≥ need), each h ≤ its maximum − output;
# a unit frozen at its schedule (coal) counts with its fixed headroom.
function rd_add_reserve_e2!(pm, gens, need_mw)
    s = E2_SCHED[]
    fixed = 0.0
    hs = JuMP.AffExpr(0.0)
    cap = 0.0
    for (_, g) in gens
        u = get(E2_UNITS, String(g["name"]), nothing)
        u === nothing && continue
        hmax = e2_head(u[1], u[2], e2_output(g, s)) / BASEMVA
        hmax > 0 || continue
        if g["pmax"] - g["pmin"] < 1e-6
            fixed += hmax
        else
            h = JuMP.@variable(pm.model, lower_bound = 0.0, upper_bound = hmax)
            JuMP.@constraint(pm.model, h <= g["pmax"] - PowerModels.var(pm, :pg, g["index"]))
            JuMP.add_to_expression!(hs, h)
            cap += min(hmax, g["pmax"] - g["pmin"])
        end
    end
    rhs = min(need_mw / BASEMVA - fixed, 0.98 * cap)                # never more than exists
    rhs > 0 && JuMP.@constraint(pm.model, hs >= rhs)
    return
end

"""
    commit_for_reserve!(network, su, date_str, hour) -> units started

Start the cheapest offline candidates until the running providers' headroom
(maximum − scheduled output) covers the hour's requirement.
"""
function commit_for_reserve!(network, su, date_str, hour)
    rs = su.reserve
    rs === nothing && return 0
    rs.rule == :e2 && return e2_commit!(network, su, date_str, hour)            # step E2
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
    rs.rule == :e2 && return rd_add_reserve_e2!(pm, gens, need_mw)              # step E2
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
    @printf "  rd_reserve.csv   : %d hours (%s)\n" length(RD_RESERVE_ROWS) (haskey(first(RD_RESERVE_ROWS), :window_mw) ?
        "E2: requirement, available, shortfall, window, headroom, starts" : "requirement: aFRR + largest loss + demand share; headroom")
end
