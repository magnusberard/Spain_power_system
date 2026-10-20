# ============================================================
# Step RD9 of redispatch_realism/: voltage start-ups in the AC redispatch
# ([redispatch.startups], off by default).
#
# With [redispatch].q_requires_online (RD3) the free reactive sources are gone,
# and in the low-load hours the AC redispatch can no longer hold voltage: on
# 2–4 Dec 2024, 17 of the 20 lowest-load hours failed.  REE solves exactly this
# in phase I by starting synchronous units (combined cycles or coal) at minimum
# load to absorb the surplus reactive power, then rebalances the energy they add
# (Davi-Arderius & Schittekatte 2023; P.O. 3.2).  This file does the same, hour
# by hour, on the AC model:
#
#   1. solve the hour as before; if it solves, nothing is started;
#   2. otherwise add a priced reactive slack at every bus (Q only, no P) and
#      solve again — where the slack is used is where reactive power is missing
#      or in surplus;
#   3. start the cheapest offline candidate unit electrically closest to the
#      bus with the largest slack (fewest branches away, then the lowest cost of
#      one start plus an hour at minimum load), at minimum load, with its full
#      reactive capability; the anchored objective takes the added energy back
#      elsewhere, as phase II does;
#   4. repeat until no slack is used or max_rounds; then drop the slack and
#      solve the hour for real with the started units.
#
# Every start is written to results/rd_startups.csv with its start-up cost,
# which redispatch_realism/settle.py adds to the redispatch cost.
#
# Not a unit commitment over the day: each hour decides on its own and a start
# is paid in every hour it is needed (an upper bound on start costs).  The
# daily phase I stage (RD8) replaces that later.  AC only (DC has no reactive
# power), constant water value path only.
# ============================================================

"""
    load_rd_startups(cfg) -> NamedTuple or nothing

The [redispatch.startups] settings, with minimum loads and start-up cost terms
taken from [unit_commitment] (gas) and [unit_commitment.coal] — the same
sources the day-ahead unit commitment uses, read even when that is off.
"""
function load_rd_startups(cfg)
    c = get(get(cfg, "redispatch", Dict()), "startups", Dict())
    mr = load_rd_mustrun(cfg)
    rs = load_rd_reserve(cfg)
    p1 = load_rd_phase1(cfg)
    (get(c, "enabled", false) || mr !== nothing || rs !== nothing || p1 !== nothing) || return nothing
    uc = get(cfg, "unit_commitment", Dict())
    co = get(uc, "coal", Dict())
    usd(x) = Float64(x) * Float64(get(uc, "usd_inflator_to_2024", 1.1953)) / Float64(get(uc, "usd_per_eur", 1.0824))
    return (startups             = Bool(get(c, "enabled", false)),   # RD9 loop on failed hours
            mustrun              = mr,                                # RD5 zones, or nothing
            reserve              = rs,                                # RD7 requirement, or nothing
            phase1               = p1,                                # RD8 daily stage, or nothing
            q_slack_eur_per_mvar = Float64(get(c, "q_slack_eur_per_mvar", 1000.0)),
            min_slack_mvar       = Float64(get(c, "min_slack_mvar", 5.0)),
            max_rounds           = Int(get(c, "max_rounds", 8)),
            max_hops             = Int(get(c, "max_hops", 4)),
            candidates           = Set(lowercase.(String.(get(c, "candidates", ["Gas:Combined_cycle", "Coal"])))),
            # smallest unit that may be started: below it are the industrial plants
            # generations.csv lists as combined cycles (refineries, factories), which
            # REE does not start for voltage; 100 MW = [unit_commitment].min_mw
            candidate_min_mw     = Float64(get(c, "candidate_min_mw", get(uc, "min_mw", 100.0))),
            # gas (CCGT): Intertek-based terms of [unit_commitment]
            gas_min_load_1x1     = Float64(get(uc, "min_load_1x1", 0.48)),
            gas_min_load_2x1     = Float64(get(uc, "min_load_2x1", 0.25)),
            gas_two_by_one_mw    = Float64(get(uc, "two_by_one_min_mw", 700.0)),
            gas_wear_eur_per_mw  = usd(get(uc, "start_wear_usd_per_mw", 52.0)),
            gas_start_fuel       = Float64(get(uc, "start_fuel_mwh_per_mw", 1.5)),
            gas_eta              = Float64(get(c, "gas_eta", 0.55)),
            # coal: [unit_commitment.coal], large vs small subcritical
            coal_large_mw        = Float64(get(co, "large_min_mw", 300.0)),
            coal_min_load_large  = Float64(get(co, "min_load_large", 0.4)),
            coal_min_load_small  = Float64(get(co, "min_load_small", 0.4)),
            coal_wear_large      = usd(get(co, "start_wear_usd_per_mw_large", 100.0)),
            coal_wear_small      = usd(get(co, "start_wear_usd_per_mw_small", 100.0)),
            coal_start_fuel      = Float64(get(co, "start_fuel_mwh_per_mw", 3.0)),
            coal_eta             = Float64(get(co, "eta", 0.36)))
end

# ── Step RD5: must-run by voltage zone ([redispatch.mustrun]) ────────────────
# Built from REE's 2024 I90 data by redispatch_realism/build_voltage_zones.py:
# in every hour where REE raised a unit of a zone for voltage, the number of the
# zone's thermal units online in REE's viable programme (PDVP).  Before an hour
# is solved, offline CCGT/coal members of a zone below its count are started at
# minimum load, cheapest first (nuclear counts but is never started).
function load_rd_mustrun(cfg)
    c = get(get(cfg, "redispatch", Dict()), "mustrun", Dict())
    get(c, "enabled", false) || return nothing
    resolve(p) = isabspath(p) ? p : joinpath(@__DIR__, p)
    zu  = CSV.read(resolve(String(c["zones_file"])), DataFrame)
    req = CSV.read(resolve(String(c["requirement_file"])), DataFrame)
    members = Dict{String,Vector{String}}()
    for r in eachrow(zu)
        push!(get!(members, String(r.zone), String[]), String(r.unit_id))
    end
    need = Dict{Tuple{String,Int},Vector{Tuple{String,Int}}}()
    scale = Float64(get(c, "scale", 1.0))
    for r in eachrow(req)
        n = round(Int, scale * r.n_online)
        n > 0 && push!(get!(need, (string(r.date), Int(r.hour)), Tuple{String,Int}[]), (String(r.zone), n))
    end
    @printf "  [redispatch.mustrun] %d zones, %d member units, requirements in %d hours\n" length(members) nrow(zu) length(need)
    return (members = members, need = need)
end

"""
    apply_zone_mustrun!(network, su, date_str, hour) -> number of units started

RD5: start the cheapest offline candidates of every zone whose online thermal
units (reactive power not taken away by RD3) are fewer than REE had.
"""
function apply_zone_mustrun!(network, su, date_str, hour)
    mr = su.mustrun
    mr === nothing && return 0
    gens = network["gen"]
    byname = Dict(g["name"] => g for (_, g) in gens)
    n_started = 0
    for (zone, n) in get(mr.need, (date_str, hour), Tuple{String,Int}[])
        units = [byname[u] for u in get(mr.members, zone, String[]) if haskey(byname, u)]
        online = count(g -> !su_is_off(g), units)
        online >= n && continue
        cands = sort([g for g in units if su_is_off(g) && su_is_candidate(su, g)]; by = g -> su_terms(su, g)[3])
        for g in first(cands, min(n - online, length(cands)))
            pmin_mw, start = su_commit!(su, g)
            n_started += 1
            push!(RD_STARTUP_ROWS, (date = date_str, hour = hour, round = 0, unit = g["name"],
                                    fuel = g["fuel"], technology = g["technology"], bus_i = g["gen_bus"],
                                    min_load_mw = round(pmin_mw; digits = 1),
                                    start_cost_eur = round(start; digits = 0),
                                    trigger_bus_i = 0, trigger_slack_mvar = NaN, hops = -1,
                                    zone = zone, zone_need = n, zone_online = online))
        end
    end
    return n_started
end

const RD_STARTUP_ROWS = NamedTuple[]
const RD_SU_OK = ("LOCALLY_SOLVED", "ALMOST_LOCALLY_SOLVED", "OPTIMAL")
rd_su_ok(res) = string(res["termination_status"]) in RD_SU_OK

su_is_candidate(su, g) = (lowercase(g["fuel"]) in su.candidates ||
                          lowercase("$(g["fuel"]):$(g["technology"])") in su.candidates) &&
                         Float64(get(g, "installed_mw", g["pmax"] * BASEMVA)) >= su.candidate_min_mw

# A candidate is off when RD3 has taken its reactive power away (qmin = qmax = 0).
su_is_off(g) = g["qmax"] == 0.0 && g["qmin"] == 0.0 && get(g, "pmax", 0.0) >= 0.0

"""
    su_terms(su, g) -> (min_load_fraction, start_cost_eur, hour_cost_eur)

Minimum load and the cost of one start for unit `g`.  Start fuel is priced at
the unit's own EUR/MWh_el cost × efficiency (fuel + CO2 per MWh of fuel), the
same approximation unit_commitment.jl uses for coal.
"""
function su_terms(su, g)
    mw   = Float64(get(g, "installed_mw", g["pmax"] * BASEMVA))
    c_el = g["cost"][1] / BASEMVA
    if g["fuel"] == "Coal"
        large = mw >= su.coal_large_mw
        ml    = large ? su.coal_min_load_large : su.coal_min_load_small
        start = ((large ? su.coal_wear_large : su.coal_wear_small) + su.coal_start_fuel * c_el * su.coal_eta) * mw
    else
        ml    = mw >= su.gas_two_by_one_mw ? su.gas_min_load_2x1 : su.gas_min_load_1x1
        start = (su.gas_wear_eur_per_mw + su.gas_start_fuel * c_el * su.gas_eta) * mw
    end
    return ml, start, start + c_el * ml * mw
end

# Bus adjacency over every branch (lines and transformers), for "fewest hops".
function su_adjacency(network)
    adj = Dict{Int,Vector{Int}}()
    for (_, b) in network["branch"]
        get(b, "br_status", 1) == 1 || continue
        push!(get!(adj, b["f_bus"], Int[]), b["t_bus"])
        push!(get!(adj, b["t_bus"], Int[]), b["f_bus"])
    end
    return adj
end

function su_hops(adj, start, max_hops)
    dist = Dict(start => 0)
    frontier = [start]
    for d in 1:max_hops
        nxt = Int[]
        for b in frontier, n in get(adj, b, Int[])
            haskey(dist, n) && continue
            dist[n] = d
            push!(nxt, n)
        end
        frontier = nxt
    end
    return dist
end

# Priced reactive slack: one Q-only pseudo-unit per bus.
function su_add_q_slack!(network)
    gens = network["gen"]
    next = maximum(g["index"] for (_, g) in gens) + 1
    ids = Int[]
    for (_, bus) in network["bus"]
        i = next + length(ids)
        gens[string(i)] = Dict{String,Any}(
            "index" => i, "gen_bus" => bus["index"], "name" => "QS_" * String(get(bus, "name", string(bus["index"]))),
            "fuel" => "QSlack", "technology" => "QSlack", "installed_mw" => 0.0,
            "pmax" => 0.0, "pmin" => 0.0, "qmax" => 99.0, "qmin" => -99.0,
            "pg" => 0.0, "qg" => 0.0, "vg" => 1.0, "mbase" => BASEMVA, "gen_status" => 1,
            "model" => 2, "ncost" => 2, "cost" => [0.0, 0.0], "startup" => 0.0, "shutdown" => 0.0)
        push!(ids, i)
    end
    return ids
end

su_remove_q_slack!(network, ids) = foreach(i -> delete!(network["gen"], string(i)), ids)

# Objective term: λ·|Q| over the slack units (|Q| through an epigraph variable).
function su_q_slack_penalty!(pm, ids, eur_per_mvar)
    obj = JuMP.objective_function(pm.model)
    for i in ids
        q = PowerModels.var(pm, :qg, i)
        t = JuMP.@variable(pm.model, lower_bound = 0.0)
        JuMP.@constraint(pm.model, t >= q)
        JuMP.@constraint(pm.model, t >= -q)
        JuMP.add_to_expression!(obj, eur_per_mvar * BASEMVA, t)
    end
    JuMP.@objective(pm.model, Min, obj)
    return
end

function su_commit!(su, g)
    ml, start, _ = su_terms(su, g)
    inst = Float64(get(g, "installed_mw", g["pmax"] * BASEMVA)) / BASEMVA
    g["pmax"] = max(g["pmax"], inst)          # a frozen unit (coal at 0 MW) is unfrozen
    g["pmin"] = ml * inst
    g["pg"]   = ml * inst
    s = get(g, "smax", Inf)
    q = isfinite(s) ? s : inst / 0.9
    g["qmax"], g["qmin"] = q, -q
    return ml * inst * BASEMVA, start
end

# One Ipopt log per solve: on Windows a finished solve can still hold its log file
# open, and the next solve writing the same file then fails with INVALID_OPTION.
su_log(log_file, k) = log_file === nothing ? nothing : replace(log_file, r"\.log$" => "_su$(k).log")

"""
    solve_hour_with_startups(network, gens, optimizer_for, sched, su; label, date_str, hour)

The redispatch solve of one hour with voltage start-ups (see the file header).
`optimizer_for(k)` gives the optimizer for solve k of the hour (0 = the plain
first solve).  Returns the final solve's result; the started units stay
committed in `network`, so the hour's outputs show them.
"""
function solve_hour_with_startups(network, gens, optimizer_for, sched, su;
                                  label = nothing, date_str = "", hour = 0)
    su.phase1 === nothing || apply_phase1_commitments!(network, su, date_str, hour)   # RD8: phase I units stay on
    n_zone = apply_zone_mustrun!(network, su, date_str, hour)        # RD5, before any solve
    n_zone > 0 && @printf "    must-run: %d unit(s) started for voltage zones\n" n_zone
    n_res = commit_for_reserve!(network, su, date_str, hour)         # RD7, after the zones
    n_res > 0 && @printf "    reserve: %d unit(s) started for upward reserve\n" n_res
    res = solve_anchored_opf(network, gens, optimizer_for(0), sched; iis_label = label)
    (rd_su_ok(res) || !su.startups) && return res
    adj = su_adjacency(network)
    slack_ids = su_add_q_slack!(network)
    slack_bus = Dict(i => network["gen"][string(i)]["gen_bus"] for i in slack_ids)
    n_started = 0
    for rnd in 1:su.max_rounds
        r = solve_anchored_opf(network, gens, optimizer_for(rnd), sched;
                               model_hook = pm -> su_q_slack_penalty!(pm, slack_ids, su.q_slack_eur_per_mvar))
        rd_su_ok(r) || (@printf "    start-ups: slack solve %s in round %d\n" string(r["termination_status"]) rnd; break)
        sol = r["solution"]["gen"]
        need = [(slack_bus[i], sol[string(i)]["qg"] * BASEMVA) for i in slack_ids
                if haskey(sol, string(i)) && abs(sol[string(i)]["qg"]) * BASEMVA > su.min_slack_mvar]
        isempty(need) && break
        bus, q = need[argmax([abs(x[2]) for x in need])]
        local dist, cands
        for hops in (su.max_hops, 2 * su.max_hops)        # widen once before giving up
            dist = su_hops(adj, bus, hops)
            cands = [g for (_, g) in gens if haskey(dist, g["gen_bus"]) && su_is_candidate(su, g) && su_is_off(g)]
            isempty(cands) || break
        end
        if isempty(cands)
            @printf "    start-ups: no offline candidate within %d hops of bus %d (%.0f Mvar)\n" 2 * su.max_hops bus q
            break
        end
        sort!(cands; by = g -> (dist[g["gen_bus"]], su_terms(su, g)[3]))
        g = first(cands)
        pmin_mw, start = su_commit!(su, g)
        n_started += 1
        push!(RD_STARTUP_ROWS, (date = date_str, hour = hour, round = rnd, unit = g["name"],
                                fuel = g["fuel"], technology = g["technology"], bus_i = g["gen_bus"],
                                min_load_mw = round(pmin_mw; digits = 1),
                                start_cost_eur = round(start; digits = 0),
                                trigger_bus_i = bus, trigger_slack_mvar = round(q; digits = 1),
                                hops = dist[g["gen_bus"]], zone = "", zone_need = 0, zone_online = 0))
    end
    su_remove_q_slack!(network, slack_ids)
    n_started == 0 && return res
    @printf "    start-ups: %d unit(s) started at minimum load\n" n_started
    return solve_anchored_opf(network, gens, optimizer_for(su.max_rounds + 1), sched; iis_label = label)
end

function write_rd_startups(dir)
    isempty(RD_STARTUP_ROWS) && return
    CSV.write(joinpath(dir, "rd_startups.csv"), DataFrame(RD_STARTUP_ROWS))
    @printf "  rd_startups.csv  : %d start-ups (voltage, [redispatch.startups])\n" length(RD_STARTUP_ROWS)
end
