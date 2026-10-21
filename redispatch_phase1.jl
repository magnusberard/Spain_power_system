# ============================================================
# Step RD8 of redispatch_realism/: REE's phase I/II as a daily stage on the
# day-ahead schedule ([redispatch.phase1], off by default).
#
# REE resolves technical constraints at D-1 on the day-ahead base schedule
# (PDBF), for the whole day: phase I starts or raises units for security,
# phase II takes the added energy back elsewhere (P.O. 3.2; CEER 2021).  The
# model's AC redispatch instead ran hour by hour at the end of the chain, so a
# unit kept on all night paid seven starts (RD9) and no phase split existed.
# Here, per study day:
#
#   * one 24-hour DC network model on the day-ahead schedule and day-ahead
#     profiles, full demand (the day-ahead balances it; DC has no losses);
#   * offline CCGT/coal units (candidates of [redispatch.startups]) get on/off
#     decisions: minimum load, start-up cost, minimum up/down times
#     ([unit_commitment] terms, as RD9 uses); units on in the day-ahead move
#     continuously;
#   * REE's cost rule (redispatch_objective.jl): up at the bid, down refunded
#     at the day-ahead price (phase I), plus start-up costs;
#   * the RD5 voltage-zone counts ([redispatch.mustrun]) as constraints, with a
#     penalised shortfall so a day never becomes infeasible;
#   * line limits as in the AC stage (× line_rating_factor); N-1 is RD6.
#
# Solved as a MILP with Gurobi.  Outputs: rd_phase1.csv (unit, hour, day-ahead
# MW, phase I/II MW, on/off) and rd_phase1_summary.csv (per hour: up, down,
# extra cost, starts).  Units it commits stay committed in the real-time AC
# stage (phase I limits hold in the later markets), without a second start-up
# cost.  The day starts with every candidate off (no carry-over between days).
# ============================================================

import LinearAlgebra

function load_rd_phase1(cfg)
    c = get(get(cfg, "redispatch", Dict()), "phase1", Dict())
    get(c, "enabled", false) || return nothing
    uc = get(cfg, "unit_commitment", Dict())
    return (n1           = Bool(get(c, "n1", false)),                     # RD6
            n1_emergency = Float64(get(c, "n1_emergency_factor", 1.0)),   # × nominal rating after an outage
            n1_min_kv    = Float64(get(c, "n1_min_kv", 220.0)),
            n1_rounds    = Int(get(c, "n1_max_rounds", 4)),
            n1_max_cuts  = Int(get(c, "n1_max_cuts", 500)),
            n1_overload_eur = Float64(get(c, "n1_overload_eur_mwh", 3000.0)),  # soft limit: price of a post-outage overload
            mip_gap      = Float64(get(c, "mip_gap", 1e-3)),
            time_limit_s = Float64(get(c, "time_limit_s", 600.0)),
            min_up       = Int(get(uc, "min_up_h", 2)),
            min_down     = Int(get(uc, "min_down_h", 6)),
            zone_short_eur = Float64(get(c, "zone_shortfall_eur", 1.0e5)),
            bids         = load_rd_bids(cfg))
end

const RD_PHASE1_ON   = Dict{Tuple{String,Int},Set{String}}()   # units phase I committed, per hour
# Phase I/II changes per hour (MW, unit ⇒ phase I − day-ahead).  In Spain they
# become part of the schedule the later stages start from, so the real-time
# stage is anchored to the balancing schedule plus these changes; otherwise
# every phase I start-up is counted and charged a second time in real time.
const RD_PHASE1_DELTA = Dict{Tuple{String,Int},Dict{String,Float64}}()
const RD_N1_SLACK    = Tuple{Int,JuMP.VariableRef}[]          # (hour position, overload slack) of the day being solved
const RD_N1_DONE     = Set{Tuple{Int,Int,Int}}()              # (hour position, monitored, outage) already constrained
const RD_PHASE1_ROWS = NamedTuple[]
const RD_PHASE1_SUM  = NamedTuple[]
const RD_SAVED_DA    = Ref{Any}(nothing)

phase1_sched_for(date_str, hour) =
    RD_FROM_SAVED_ACTIVE ?
        get((RD_SAVED_DA[] === nothing ? (RD_SAVED_DA[] = load_saved_schedule("DA")) : RD_SAVED_DA[]),
            (date_str, hour), nothing) :
        da_sched_for(date_str, hour)

function phase1_nets(date_str, day_ts)
    bv = day_bellman[date_str]
    [prepare_network(ts.load_mw - xb_export_offset(date_str, ts.hour), ts.solar_mw, ts.wind_mw;
                     hydro_reservoir_cost = bv.water_value,
                     crossborder_inj = crossborder_inj_for(date_str, ts.hour),
                     crossborder_exports = WEEKS_ACTIVE || XB_EXPORT_AT_BORDER,
                     crossborder_bus_caps = RD_XB_SPLIT == "country_total" ? XB_BUS_CAPS : nothing,
                     crossborder_same_direction = RD_XB_SPLIT == "country_total",
                     da_dispatch = phase1_sched_for(date_str, ts.hour),
                     frozen_fuels = RD_FROZEN_FUELS, island_buses = ISLAND_BUSES, removed_units = REMOVED_UNITS,
                     nuclear_availability = nuclear_avail_for(date_str), coal_availability = coal_avail_for(date_str),
                     chp_blocks = chp_blocks_for(date_str), chp_siting_buses = CHP_SITING_BUSES,
                     voltage_band = VOLTAGE_BAND, line_rating_factor = LINE_RATING_FACTOR,
                     reactors_enabled = REACTORS_ENABLED, reactor_in_service_pct = REACTOR_PCT,
                     load_power_factor = LOAD_PF, apparent_power_limit = APPARENT_POWER_LIMIT,
                     rated_power_factor = RATED_PF, renewable_power_factor = RENEWABLE_PF,
                     unit_scale = UNIT_SCALE, cost_override = cost_override_for(date_str),
                     unit_cost_override = unit_cost_override_for(date_str), bess_units = BESS_UNITS,
                     unit_scale_by_id = UNIT_SCALE_ID, extra_units = EXTRA_UNITS, line_scale = LINE_SCALE,
                     rating_scale = RATING_SCALE, extra_lines = EXTRA_LINES)
     for ts in eachrow(day_ts)]
end

function build_phase1_dc(pm::PowerModels.AbstractPowerModel)
    for (n, _) in PowerModels.nws(pm)
        PowerModels.variable_bus_voltage(pm; nw = n)
        PowerModels.variable_gen_power(pm; nw = n)
        PowerModels.variable_branch_power(pm; nw = n)
        PowerModels.variable_dcline_power(pm; nw = n)
        PowerModels.constraint_model_voltage(pm; nw = n)
        for i in PowerModels.ids(pm, :ref_buses; nw = n)
            PowerModels.constraint_theta_ref(pm, i; nw = n)
        end
        for i in PowerModels.ids(pm, :bus; nw = n)
            PowerModels.constraint_power_balance(pm, i; nw = n)
        end
        for i in PowerModels.ids(pm, :branch; nw = n)
            PowerModels.constraint_ohms_yt_from(pm, i; nw = n)
            PowerModels.constraint_ohms_yt_to(pm, i; nw = n)
            PowerModels.constraint_voltage_angle_difference(pm, i; nw = n)
            PowerModels.constraint_thermal_limit_from(pm, i; nw = n)
            PowerModels.constraint_thermal_limit_to(pm, i; nw = n)
        end
        for i in PowerModels.ids(pm, :dcline; nw = n)
            PowerModels.constraint_dcline_power_losses(pm, i; nw = n)
        end
    end
end

# ── Step RD6: preventive N-1 in phase I (n1 = true) ──────────────────────────
# REE's security analysis checks every single outage (P.O. 3.2); N-1 was 28 % of
# its phase I upward redispatch in 2024 (e·sios cause SCA).  Iterative and lazy:
# solve, compute every monitored branch's flow after each single outage of a
# ≥ n1_min_kv line or transformer with line outage distribution factors (DC),
# add constraints only for the (branch, outage, hour) combinations above
# n1_emergency_factor × the branch's nominal rating, solve again; at most
# n1_max_rounds rounds and n1_max_cuts new constraints per round, worst first.
# The base case keeps line_rating_factor (its N-1 proxy); outages are skipped
# where they would island part of the grid.  Van den Bergh et al. (2015): the
# preventive N-1 criterion costs several times the curative one, so the result
# is an upper bound on N-1 redispatch.

"""
    rd_ptdf(network) -> (ptdf, branch_ids, bus_col)

DC power transfer distribution factors (branch flow per MW injected at a bus,
withdrawn at the slack), from the branches' reactances.
"""
function rd_ptdf(network)
    br = sort([b for (_, b) in network["branch"] if get(b, "br_status", 1) == 1]; by = b -> b["index"])
    buses = sort(collect(keys(network["bus"])); by = k -> network["bus"][k]["index"])
    bus_col = Dict(network["bus"][k]["index"] => i for (i, k) in enumerate(buses))
    slack = first(network["bus"][k]["index"] for k in buses if network["bus"][k]["bus_type"] == 3)
    nl, nb = length(br), length(buses)
    A = zeros(nl, nb)
    bvec = zeros(nl)
    for (l, b) in enumerate(br)
        A[l, bus_col[b["f_bus"]]] = 1.0
        A[l, bus_col[b["t_bus"]]] = -1.0
        bvec[l] = 1.0 / max(abs(b["br_x"]), 1e-6)
    end
    keep = [i for i in 1:nb if i != bus_col[slack]]
    Bred = A[:, keep]' * (bvec .* A[:, keep])
    ptdf = zeros(nl, nb)
    ptdf[:, keep] = (bvec .* A[:, keep]) / Bred
    return ptdf, [b["index"] for b in br], bus_col
end

"""
    add_n1_cuts!(pm, m, nets, nwk, H, p1, sens) -> number of constraints added

Check the current solution against every single outage and add the worst
violated (branch, outage, hour) limits as constraints.
"""
function add_n1_cuts!(pm, m, nets, nwk, H, p1, sens)
    ptdf, ids, bus_col = sens
    net = nets[1].network
    byid = Dict(b["index"] => b for (_, b) in net["branch"])
    kv(b) = max(get(net["bus"][string(b["f_bus"])], "base_kv", 0.0), get(net["bus"][string(b["t_bus"])], "base_kv", 0.0))
    outages = [c for (c, id) in enumerate(ids) if kv(byid[id]) >= p1.n1_min_kv]
    # φ[:, c]: change on every branch per MW lost on branch c; LODF = φ / (1 − φ_cc)
    phi = zeros(length(ids), length(outages))
    for (j, c) in enumerate(outages)
        b = byid[ids[c]]
        phi[:, j] = ptdf[:, bus_col[b["f_bus"]]] - ptdf[:, bus_col[b["t_bus"]]]
    end
    lim = [byid[id]["rate_a"] / LINE_RATING_FACTOR * p1.n1_emergency for id in ids]     # pu, nominal × factor
    cand = Tuple{Float64,Int,Int,Int,Float64}[]          # (excess, hour k, monitored l, outage c, lodf)
    for k in 1:H
        n = nwk[k]
        f = [JuMP.value(PowerModels.var(pm, n, :p, (id, byid[id]["f_bus"], byid[id]["t_bus"]))) for id in ids]
        for (j, c) in enumerate(outages)
            den = 1.0 - phi[c, j]
            abs(den) < 1e-4 && continue                      # would island part of the grid
            post = f .+ (phi[:, j] ./ den) .* f[c]
            for l in eachindex(ids)
                (l == c || (k, l, c) in RD_N1_DONE) && continue
                ex = abs(post[l]) - lim[l]
                ex > 1e-4 && push!(cand, (ex, k, l, c, phi[l, j] / den))
            end
        end
    end
    sort!(cand; by = x -> -x[1])
    added = 0
    for (ex, k, l, c, lodf) in first(cand, min(p1.n1_max_cuts, length(cand)))
        n = nwk[k]
        bl, bc = byid[ids[l]], byid[ids[c]]
        pl = PowerModels.var(pm, n, :p, (ids[l], bl["f_bus"], bl["t_bus"]))
        pc = PowerModels.var(pm, n, :p, (ids[c], bc["f_bus"], bc["t_bus"]))
        # soft: an overload no redispatch can remove (fixed injections, grid data)
        # is priced, not infeasible — 3,000 EUR/MWh is above any bid, so every
        # overload redispatch can fix is fixed; the rest is reported
        s = JuMP.@variable(m, lower_bound = 0.0)
        JuMP.@constraint(m, pl + lodf * pc <=  lim[l] + s)
        JuMP.@constraint(m, pl + lodf * pc >= -lim[l] - s)
        JuMP.set_objective_coefficient(m, s, p1.n1_overload_eur * BASEMVA)
        push!(RD_N1_SLACK, (k, s))
        push!(RD_N1_DONE, (k, l, c))
        added += 1
    end
    @printf "    N-1: %d post-outage overloads found, %d constraints added (worst %.0f MW over)\n" length(cand) added (isempty(cand) ? 0.0 : cand[1][1] * BASEMVA)
    return added
end

"""
    run_phase1_day!(su, date_str)

Phase I/II for one study day (see the file header).  Fills RD_PHASE1_ON,
RD_PHASE1_ROWS and RD_PHASE1_SUM.
"""
function run_phase1_day!(su, date_str)
    p1 = su.phase1
    day_ts = sort(filter(r -> r.date == date_str, hourly_da), :hour)
    H = nrow(day_ts)
    nets = phase1_nets(date_str, day_ts)
    mn = Dict{String,Any}("multinetwork" => true, "baseMVA" => BASEMVA, "per_unit" => true, "name" => "phase1",
                          "nw" => Dict{String,Any}(string(h - 1) => nets[h].network for h in 1:H))
    pm = PowerModels.instantiate_model(mn, PowerModels.DCPPowerModel, build_phase1_dc)   # mn["multinetwork"] = true
    m  = pm.model
    obj = zero(JuMP.AffExpr)
    hours = [Int(ts.hour) for ts in eachrow(day_ts)]
    p_da  = [rd_da_price(date_str, h) for h in hours]
    scheds = [something(phase1_sched_for(date_str, h), Dict{String,Float64}()) for h in hours]
    u = Dict{Tuple{String,Int},JuMP.VariableRef}()       # on/off of candidates
    pg_of = Dict{Tuple{String,Int},JuMP.VariableRef}()
    gen_of = Dict{String,Any}()
    # network id (Int or String, by PowerModels version) → position in the day
    nwk = Dict(parse(Int, string(n)) + 1 => n for n in keys(PowerModels.nws(pm)))
    for k in 1:H
        n = nwk[k]
        gens = nets[k].network["gen"]
        ct, _ = add_xb_group_constraints!(pm, gens; nw = n)
        JuMP.add_to_expression!(obj, ct)
        for (_, g) in gens
            name = g["name"]
            pg = PowerModels.var(pm, n, :pg, g["index"])
            if startswith(name, "SLACK") || startswith(name, "LS_")
                JuMP.add_to_expression!(obj, g["cost"][1], pg)
                continue
            end
            (rd_is_market_unit(name) || startswith(name, "BESS_")) || continue
            tgt  = get(scheds[k], name, 0.0) / BASEMVA
            inst = Float64(get(g, "installed_mw", g["pmax"] * BASEMVA)) / BASEMVA
            cand = su_is_candidate(su, g) && abs(tgt) < RD_Q_ONLINE_FRAC * inst      # off in the day-ahead
            (cand || abs(g["pmax"] - g["pmin"]) > 1e-9) || continue                 # frozen, not a candidate
            gen_of[name] = g
            pg_of[(name, k)] = pg
            p_up, p_dn = rd_bid_prices(p1.bids, g, p_da[k])
            if cand
                ml = su_terms(su, g)[1]
                JuMP.set_lower_bound(pg, 0.0)                     # a frozen unit (coal at 0 MW) is unfrozen
                JuMP.set_upper_bound(pg, max(g["pmax"], inst))
                v = JuMP.@variable(m, binary = true)
                u[(name, k)] = v
                JuMP.@constraint(m, pg <= max(g["pmax"], inst) * v)
                JuMP.@constraint(m, pg >= ml * inst * v)
                JuMP.add_to_expression!(obj, (p_up - p_da[k] + p1.bids.tie_break) * BASEMVA, pg)
            else
                up = JuMP.@variable(m, lower_bound = 0.0); dn = JuMP.@variable(m, lower_bound = 0.0)
                JuMP.@constraint(m, pg == tgt + up - dn)
                JuMP.add_to_expression!(obj, (p_up - p_da[k] + p1.bids.tie_break) * BASEMVA, up)
                JuMP.add_to_expression!(obj, (p_da[k] - p_dn + p1.bids.tie_break) * BASEMVA, dn)
            end
        end
    end
    # start-ups, minimum up and down times (every candidate starts the day off)
    starts = Dict{Tuple{String,Int},JuMP.VariableRef}()
    for name in unique(first.(collect(keys(u))))
        g = gen_of[name]
        start_cost = su_terms(su, g)[2]
        ks = sort([k for (nm, k) in keys(u) if nm == name])
        for k in ks
            s = JuMP.@variable(m, lower_bound = 0.0, upper_bound = 1.0)
            w = JuMP.@variable(m, lower_bound = 0.0, upper_bound = 1.0)
            prev = haskey(u, (name, k - 1)) ? u[(name, k - 1)] : 0.0
            JuMP.@constraint(m, s >= u[(name, k)] - prev)
            JuMP.@constraint(m, w >= prev - u[(name, k)])
            starts[(name, k)] = s
            JuMP.add_to_expression!(obj, start_cost, s)
            starts[(name, -k)] = w                                  # shut-downs, keyed by −k
        end
        for k in ks
            JuMP.@constraint(m, sum(starts[(name, j)] for j in max(1, k - p1.min_up + 1):k if haskey(starts, (name, j))) <= u[(name, k)])
            JuMP.@constraint(m, sum(starts[(name, -j)] for j in max(1, k - p1.min_down + 1):k if haskey(starts, (name, -j))) <= 1 - u[(name, k)])
        end
    end
    # RD5 zone counts
    if su.mustrun !== nothing
        for (k, h) in enumerate(hours), (zone, need) in get(su.mustrun.need, (date_str, h), Tuple{String,Int}[])
            members = get(su.mustrun.members, zone, String[])
            on_da = count(nm -> abs(get(scheds[k], nm, 0.0)) >= 1.0, members)
            vs = [u[(nm, k)] for nm in members if haskey(u, (nm, k))]
            short = JuMP.@variable(m, lower_bound = 0.0)
            JuMP.@constraint(m, on_da + (isempty(vs) ? 0.0 : sum(vs)) + short >= need)
            JuMP.add_to_expression!(obj, p1.zone_short_eur, short)
        end
    end
    JuMP.@objective(m, Min, obj)
    opt = gurobi_da(log_file = joinpath(IPOPT_LOG_DIR, "$(date_str)_phase1.log"))
    JuMP.set_optimizer(m, opt)
    JuMP.set_optimizer_attribute(m, "MIPGap", p1.mip_gap)
    JuMP.set_optimizer_attribute(m, "TimeLimit", p1.time_limit_s)
    t0 = time()
    JuMP.optimize!(m)
    empty!(RD_N1_SLACK); empty!(RD_N1_DONE)
    if p1.n1 && JuMP.has_values(m)                                   # RD6: lazy preventive N-1
        sens = rd_ptdf(nets[1].network)
        for r in 1:p1.n1_rounds
            add_n1_cuts!(pm, m, nets, nwk, H, p1, sens) == 0 && break
            JuMP.optimize!(m)
            JuMP.has_values(m) || break
        end
    end
    status = string(JuMP.termination_status(m))
    @printf "  phase I/II %s: %s in %.0f s, %d candidates, objective %.0f EUR\n" date_str status (time() - t0) length(unique(first.(collect(keys(u))))) (JuMP.has_values(m) ? JuMP.objective_value(m) : NaN)
    JuMP.has_values(m) || return
    for (k, h) in enumerate(hours)
        on = Set{String}()
        delta = Dict{String,Float64}()
        up_mwh = dn_mwh = cost = 0.0
        nst = 0
        for ((name, kk), pg) in pg_of
            kk == k || continue
            g = gen_of[name]
            mw  = JuMP.value(pg) * BASEMVA
            da  = get(scheds[k], name, 0.0)
            com = haskey(u, (name, k)) && JuMP.value(u[(name, k)]) > 0.5
            com && push!(on, name)
            d = mw - da
            abs(d) > 1e-3 && (delta[name] = d)
            p_up, p_dn = rd_bid_prices(p1.bids, g, p_da[k])
            d > 0 ? (up_mwh += d; cost += d * (p_up - p_da[k])) : (dn_mwh -= d; cost += -d * (p_da[k] - p_dn))
            if abs(d) > 0.5 || com
                push!(RD_PHASE1_ROWS, (date = date_str, hour = h, unit = name, fuel = g["fuel"], technology = g["technology"],
                                       da_mw = round(da; digits = 1), phase1_mw = round(mw; digits = 1), committed = com))
            end
            if haskey(starts, (name, k)) && JuMP.value(starts[(name, k)]) > 0.5
                nst += 1
                cost += su_terms(su, g)[2]
            end
        end
        RD_PHASE1_ON[(date_str, h)] = on
        RD_PHASE1_DELTA[(date_str, h)] = delta
        n1_left =sum((JuMP.value(s) * BASEMVA for (kk, s) in RD_N1_SLACK if kk == k); init = 0.0)
        push!(RD_PHASE1_SUM, (date = date_str, hour = h, status = status, up_mwh = round(up_mwh; digits = 1),
                              down_mwh = round(dn_mwh; digits = 1), starts = nst, units_committed = length(on),
                              extra_cost_eur = round(cost; digits = 0), p_da = p_da[k],
                              n1_overload_left_mw = round(n1_left; digits = 1)))
    end
end

"""
    phase1_anchor(sched, date_str, hour) -> schedule

The real-time stage's starting schedule: `sched` (balancing) plus phase I/II's
changes for the hour (a new dict; `sched` itself is left untouched).
"""
function phase1_anchor(sched, date_str, hour)
    delta = get(RD_PHASE1_DELTA, (date_str, hour), nothing)
    (delta === nothing || sched === nothing) && return sched
    out = copy(sched)
    for (name, d) in delta
        out[name] = get(out, name, 0.0) + d
    end
    return out
end

"""
    apply_phase1_commitments!(network, date_str, hour) -> units kept on

Real-time AC stage: units phase I committed for this hour stay committed
(minimum load, reactive power); their start-up was paid in phase I.
"""
function apply_phase1_commitments!(network, su, date_str, hour)
    on = get(RD_PHASE1_ON, (date_str, hour), Set{String}())
    isempty(on) && return 0
    n = 0
    for (_, g) in network["gen"]
        (g["name"] in on && su_is_off(g)) || continue
        su_commit!(su, g)
        n += 1
    end
    return n
end

function write_rd_phase1(dir)
    isempty(RD_PHASE1_SUM) && return
    CSV.write(joinpath(dir, "rd_phase1.csv"), DataFrame(RD_PHASE1_ROWS))   # settle.py reads the changes from here too
    CSV.write(joinpath(dir, "rd_phase1_summary.csv"), DataFrame(RD_PHASE1_SUM))
    @printf "  rd_phase1*.csv   : %d unit-hours changed, %d hours ([redispatch.phase1])\n" length(RD_PHASE1_ROWS) length(RD_PHASE1_SUM)
end
