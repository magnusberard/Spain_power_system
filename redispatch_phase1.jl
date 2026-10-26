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
#
# Where it runs ([redispatch.phase1].in_chain):
#   false (default) — after all market stages, on the (saved) day-ahead
#     schedule; the real-time stage starts from the balancing schedule plus
#     phase I's changes.  Those changes were made against the day-ahead and do
#     not fit a balancing schedule the intraday markets have re-traded, so on
#     days with much phase I the real-time stage undoes the mismatch (2–8 Dec
#     2024: real-time up 3.4× REE's).
#   true — inside the market chain, as in Spain (P.O. 3.2): right after each
#     day's DA, before ID2.  The DA schedule plus phase I/II's changes (REE's
#     PDVP) is what the intraday markets start from, and the units phase I
#     started stay on at least at minimum load in ID2, ID3, CID and BAL (REE's
#     security limits; through UC_COMMIT, the same path the DA commitment
#     takes).  The balancing schedule then already holds phase I, so the
#     real-time stage starts from it unchanged.  Needs the market stages to run
#     (not from_saved).  The DA price and da_dispatch.csv stay the DA's own;
#     intraday prices may move, because the started units' energy is in them.
# ============================================================

import LinearAlgebra

# ── RD13: water budget for hydro in the redispatch ([redispatch.hydro_budget]) ───
# The redispatch cannot create water: the weekly water plan (SDDP) and the markets
# already fixed each hydro unit's daily energy.  REE practically never raises hydro
# in phase I (2024: 39 of 13,584 GWh, I90DIA03) but turns it down a lot in phase II
# (3,657 of 11,925 GWh): going down saves water, going up spends water planned for
# other hours.  Without a budget, phase I and real time raised hydro at 1.59 × the
# day-ahead price instead of starting gas (2–8 Dec 2024, no zones: 297 GWh hydro up).
# Rule: per unit and day the redispatch may not add energy to the schedule
# (Σ_h (pg − schedule) ≤ tolerance_mwh); shifting between hours and going down stay
# free.  DC phase I: one constraint per unit and day.  Hour-by-hour stages (the
# phase I AC check, real time): a running tally per stage, unit and day caps each
# hour's output at schedule + tolerance + what earlier hours of the day gave back.
# The cap limits energy only (a constraint pg ≤ cap in the solve, hydro_budget_constrain!),
# not pmax: reserve held but not used costs no water, so the reserve check (RD7/E1) still
# sees the unit's physical headroom.  Until 23 Oct the cap lowered pmax, which also took
# hydro out of the reserve and started 63 gas units for reserve on 2–8 Dec 2024 (C4).

function load_rd_hydro_budget(cfg)
    c = get(get(cfg, "redispatch", Dict()), "hydro_budget", Dict())
    get(c, "enabled", false) || return nothing
    return (tolerance_mwh = Float64(get(c, "tolerance_mwh", 0.0)),)
end

const RD_HYDRO_TALLY = Dict{Tuple{String,String,String},Float64}()   # (stage, date, unit) ⇒ MWh added so far

rd_is_hydro_budget_unit(g) = g["fuel"] == "Hydro" && abs(g["pmax"] - g["pmin"]) > 1e-9

"""
    hydro_budget_cap!(network, sched, hb, stage, date_str)

Before an hourly solve: cap each free hydro unit's output at its schedule + tolerance +
the energy earlier hours of the day gave back (MW = MWh for one hour).  The cap is kept
as `g["rd_energy_cap"]` (per unit, MW/BASEMVA) and enforced by hydro_budget_constrain!;
pmax is left alone.
"""
function hydro_budget_cap!(network, sched, hb, stage, date_str)
    (hb === nothing || sched === nothing) && return 0
    n = 0
    for (_, g) in network["gen"]
        rd_is_hydro_budget_unit(g) || continue
        s = get(sched, g["name"], 0.0)
        room = hb.tolerance_mwh + max(0.0, -get(RD_HYDRO_TALLY, (stage, date_str, g["name"]), 0.0))
        cap = (s + room) / BASEMVA
        if cap < g["pmax"]
            g["rd_energy_cap"] = max(cap, g["pmin"])
            n += 1
        end
    end
    return n
end

rd_energy_cap(g) = get(g, "rd_energy_cap", g["pmax"])

"""
    hydro_budget_constrain!(pm, network)

In the solve: pg ≤ the water-budget cap for each unit hydro_budget_cap! capped.
"""
function hydro_budget_constrain!(pm, network)
    n = 0
    for (_, g) in network["gen"]
        haskey(g, "rd_energy_cap") || continue
        haskey(PowerModels.ref(pm, :gen), g["index"]) || continue
        JuMP.@constraint(pm.model, PowerModels.var(pm, :pg, g["index"]) <= g["rd_energy_cap"])
        n += 1
    end
    return n
end

"""
    hydro_budget_record!(result, network, sched, hb, stage, date_str)

After a solved hour: add each hydro unit's change from its schedule to the day's tally.
"""
function hydro_budget_record!(result, network, sched, hb, stage, date_str)
    (hb === nothing || sched === nothing) && return
    sol = get(get(result, "solution", Dict()), "gen", Dict())
    for (k, g) in network["gen"]
        rd_is_hydro_budget_unit(g) || continue
        haskey(sol, k) || continue
        key = (stage, date_str, g["name"])
        RD_HYDRO_TALLY[key] = get(RD_HYDRO_TALLY, key, 0.0) + sol[k]["pg"] * BASEMVA - get(sched, g["name"], 0.0)
    end
end

function load_rd_phase1(cfg)
    c = get(get(cfg, "redispatch", Dict()), "phase1", Dict())
    get(c, "enabled", false) || return nothing
    uc = get(cfg, "unit_commitment", Dict())
    return (in_chain     = Bool(get(c, "in_chain", false)),               # after the DA, before ID2
            ac_check     = Bool(get(c, "ac_check", false)),               # step C: AC voltage check in phase I
            ac_zones     = Bool(get(c, "ac_check_zones", true)),          # step C: RD5 zone counts also in that check
            hydro_budget = load_rd_hydro_budget(cfg),                     # RD13: no added hydro energy per day
            n1           = Bool(get(c, "n1", false)),                     # RD6
            n1_emergency = Float64(get(c, "n1_emergency_factor", 1.0)),   # × nominal rating after an outage
            n1_min_kv    = Float64(get(c, "n1_min_kv", 220.0)),
            n1_rounds    = Int(get(c, "n1_max_rounds", 4)),
            n1_max_cuts  = Int(get(c, "n1_max_cuts", 500)),
            n1_overload_eur = Float64(get(c, "n1_overload_eur_mwh", 3000.0)),  # soft limit: price of a post-outage overload
            n1_outage    = lowercase(String(get(c, "n1_outage", "element"))), # "element" (one circuit/transformer) or "branch"
            n1_seasonal  = Bool(get(c, "n1_seasonal_ratings", false)),        # RD6b: P.O. 1.1 seasonal limits after an outage
            n1_line_season = Dict(String(k) => Float64(v) for (k, v) in
                                  get(c, "n1_line_season_factor", Dict("winter" => 1.18, "spring" => 1.09,
                                                                       "summer" => 1.0, "autumn" => 1.09))),
            n1_trafo_winter = Float64(get(c, "n1_trafo_winter_factor", 1.10)),
            mip_gap      = Float64(get(c, "mip_gap", 1e-3)),
            time_limit_s = Float64(get(c, "time_limit_s", 600.0)),
            min_up       = Int(get(uc, "min_up_h", 2)),
            min_down     = Int(get(uc, "min_down_h", 6)),
            zone_short_eur = Float64(get(c, "zone_shortfall_eur", 1.0e5)),
            units_req    = load_rd_unit_requirement(c),                   # fix 2: units REE needs specifically
            bids         = load_rd_bids(cfg))
end

# Fix 2 (2024 only, like RD5): units REE raised in phase I on most days of the year are required in
# the hours REE raised them (build_unit_requirement.py; RD5's zone counts let the model meet a zone
# with its cheapest members, but REE kept e.g. Aboño 2 on through phase I on 358 days).
function load_rd_unit_requirement(c)
    f = String(get(c, "unit_requirement_file", ""))
    isempty(f) && return nothing
    f = isabspath(f) ? f : joinpath(@__DIR__, f)
    req = Dict{Tuple{String,Int},Vector{String}}()
    for r in eachrow(CSV.read(f, DataFrame))
        push!(get!(req, (string(r.date), Int(r.hour)), String[]), String(r.unit_id))
    end
    @printf "  [redispatch.phase1] unit requirement: %d unit-hours in %d hours\n" sum(length, values(req)) length(req)
    return req
end

const RD_PHASE1_ON   = Dict{Tuple{String,Int},Set{String}}()   # units phase I committed, per hour
# Phase I/II changes per hour (MW, unit ⇒ phase I − day-ahead).  In Spain they
# become part of the schedule the later stages start from, so the real-time
# stage is anchored to the balancing schedule plus these changes; otherwise
# every phase I start-up is counted and charged a second time in real time.
const RD_PHASE1_DELTA = Dict{Tuple{String,Int},Dict{String,Float64}}()
const RD_PHASE1_MINLOAD = Dict{String,Float64}()              # candidate ⇒ minimum load (fraction of installed)
const RD_PHASE1_STARTCOST = Dict{Tuple{String,Int},Tuple{Int,Float64}}()   # (date, hour) ⇒ (DC starts, their cost EUR)
const RD_N1_SLACK    = Tuple{Int,JuMP.VariableRef}[]          # (hour position, overload slack) of the day being solved
const RD_N1_DONE     = Set{Tuple{Int,Int,Int}}()              # (hour position, monitored, outage) already constrained
const RD_N1_PAIR     = Tuple{String,String,Float64}[]          # per RD_N1_SLACK entry: (monitored, outage, limit MW)
const RD_N1_LEFT_ROWS = NamedTuple[]                          # overloads left after phase I → rd_n1_left.csv
const RD_PHASE1_ROWS = NamedTuple[]
const RD_PHASE1_SUM  = NamedTuple[]
# in_chain: the day-ahead schedule before phase I moved it (the report's da_mw), per (date, hour)
const RD_DA_BEFORE_PHASE1 = Dict{Tuple{String,Int},Dict{String,Float64}}()
# in_chain + ac_check: the AC check's own changes (MW per unit), which the markets did not see; real
# time is anchored to BAL plus these, and settle.py reads them from rd_phase1_ac.csv
const RD_PHASE1_AC_ROWS = Dict{Tuple{String,Int},Dict{String,Float64}}()
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
#
# RD6b, n1_seasonal_ratings: P.O. 1.1 (2016) §4.3.2 judges a line after a single
# outage against its SEASONAL thermal limit (transient +15 % for under 20 min,
# kept as n1_emergency_factor), and a transformer against its rating, +10 % in
# winter.  RDL 17/2022 Annex I sets the seasons (winter Nov–Mar, spring Apr–May,
# summer Jun–Aug, autumn Sep–Oct) but leaves the values to each line's owner
# (thermal model, CIGRE 601 / IEEE 738, wind 0.6 m/s).  The model's line ratings
# are generic conductor ratings (Data/lines.csv Imax: 1.29 kA at 220 kV, 2.58 kA
# at 400 kV per circuit), taken here as the summer value; n1_line_season_factor
# scales them per season.  Default factors: a conductor's ampacity at a given
# maximum temperature grows about as √(Tc − Ta) when convection dominates; with
# Tc = 85 °C and design ambients 35 °C (summer), 25 °C (spring/autumn) and 15 °C
# (winter): 1.0, 1.09 and 1.18.  An assumption to vary, not REE's per-line data.
rd_season(month::Int) = month in (11, 12, 1, 2, 3) ? "winter" : month in (4, 5) ? "spring" :
                        month in (6, 7, 8) ? "summer" : "autumn"

# Parallel elements per branch (n1_outage = "element"): a line's circuits
# (Data/lines.csv) and a transformer bank's units (transformers_reactance.csv
# n_recommended), which prepare_network merges into one branch each.
const RD_N1_ELEMENTS = Dict{String,Int}()
function rd_n1_elements()
    isempty(RD_N1_ELEMENTS) || return RD_N1_ELEMENTS
    ldf = CSV.read(joinpath(DATA, "lines.csv"), DataFrame)
    dup = DEDUP_AB_LINES[] ? ab_duplicate_ids(ldf) : Set{String}()     # [network].dedup_ab_lines
    for r in eachrow(ldf)
        c = String(r.line_id) in dup ? r.circuits / 2 : r.circuits
        RD_N1_ELEMENTS[String(r.line_id)] = max(Int(round(c)), 1)
    end
    for r in eachrow(CSV.read(joinpath(DATA, "transformers_reactance.csv"), DataFrame))
        RD_N1_ELEMENTS[String(r.transformer_id)] = max(Int(round(r.n_recommended)), 1)
    end
    return RD_N1_ELEMENTS
end

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
function add_n1_cuts!(pm, m, nets, nwk, H, p1, sens; month::Int = 6)
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
    season = rd_season(month)
    f_line = p1.n1_seasonal ? get(p1.n1_line_season, season, 1.0) : 1.0
    f_tr   = p1.n1_seasonal && season == "winter" ? p1.n1_trafo_winter : 1.0
    # off: every branch at nominal × n1_emergency_factor, as before RD6b
    f_of(b) = !p1.n1_seasonal ? p1.n1_emergency :
              startswith(String(get(b, "name", "")), "TR_") ? f_tr : f_line * p1.n1_emergency
    lim = [byid[id]["rate_a"] / LINE_RATING_FACTOR * f_of(byid[id]) for id in ids]       # pu, nominal × factor
    # n1_outage = "element": an outage trips ONE of the n parallel elements a branch
    # stands for (circuits of a line, transformers of a bank), as P.O. 1.1's N-1;
    # "branch" trips the whole branch (losing a double-circuit line is P.O. 1.1's
    # separate, milder criterion b).  Tripping one of n elements of branch c: the
    # element carries f_c/n and its self-sensitivity is φ_cc/n, so the injection that
    # removes it is ΔP = (f_c/n) / (1 − φ_cc/n); the other branches change by φ_l·ΔP,
    # and the n − 1 elements left in c carry f_c + (φ_cc − 1)·ΔP within (n − 1)/n of
    # c's limit.
    nel(c) = p1.n1_outage == "element" ? get(rd_n1_elements(), String(get(byid[ids[c]], "name", "")), 1) : 1
    cand = Tuple{Float64,Int,Int,Int,Float64,Float64}[]  # (excess, hour k, monitored l, outage c, lodf, limit)
    for k in 1:H
        n = nwk[k]
        f = [JuMP.value(PowerModels.var(pm, n, :p, (id, byid[id]["f_bus"], byid[id]["t_bus"]))) for id in ids]
        for (j, c) in enumerate(outages)
            ne  = nel(c)
            den = 1.0 - phi[c, j] / ne
            abs(den) < 1e-4 && continue                      # would island part of the grid
            post = f .+ (phi[:, j] ./ (den * ne)) .* f[c]
            for l in eachindex(ids)
                (k, l, c) in RD_N1_DONE && continue
                if l == c
                    ne > 1 || continue                       # the remaining elements of the tripped branch
                    coef = 1.0 + (phi[c, j] - 1.0) / (den * ne)
                    lim_rest = lim[c] * (ne - 1) / ne
                    ex = abs(coef * f[c]) - lim_rest
                    ex > 1e-4 && push!(cand, (ex, k, l, c, coef - 1.0, lim_rest))
                else
                    ex = abs(post[l]) - lim[l]
                    ex > 1e-4 && push!(cand, (ex, k, l, c, phi[l, j] / (den * ne), lim[l]))
                end
            end
        end
    end
    sort!(cand; by = x -> -x[1])
    added = 0
    for (ex, k, l, c, lodf, lim_lc) in first(cand, min(p1.n1_max_cuts, length(cand)))
        n = nwk[k]
        bl, bc = byid[ids[l]], byid[ids[c]]
        pl = PowerModels.var(pm, n, :p, (ids[l], bl["f_bus"], bl["t_bus"]))
        pc = PowerModels.var(pm, n, :p, (ids[c], bc["f_bus"], bc["t_bus"]))
        # soft: an overload no redispatch can remove (fixed injections, grid data)
        # is priced, not infeasible — 3,000 EUR/MWh is above any bid, so every
        # overload redispatch can fix is fixed; the rest is reported
        # (l == c: the elements left in the tripped branch, pl + lodf·pc = coef·pc)
        s = JuMP.@variable(m, lower_bound = 0.0)
        JuMP.@constraint(m, pl + lodf * pc <=  lim_lc + s)
        JuMP.@constraint(m, pl + lodf * pc >= -lim_lc - s)
        JuMP.set_objective_coefficient(m, s, p1.n1_overload_eur * BASEMVA)
        push!(RD_N1_SLACK, (k, s))
        push!(RD_N1_PAIR, (String(get(bl, "name", string(ids[l]))), String(get(bc, "name", string(ids[c]))), lim_lc * BASEMVA))
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
                RD_PHASE1_MINLOAD[name] = ml
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
    # RD13 water budget ([redispatch.hydro_budget]): phase I may not add hydro energy to a
    # unit's day — Σ_h (pg − schedule) ≤ tolerance; shifting between hours and going down stay free
    if p1.hydro_budget !== nothing
        sched_mw = Dict(name => sum(get(scheds[k], name, 0.0) for k in 1:H) for (name, _) in gen_of)
        for (name, g) in gen_of
            g["fuel"] == "Hydro" || continue
            pgs = [pg_of[(name, k)] for k in 1:H if haskey(pg_of, (name, k))]
            isempty(pgs) && continue
            JuMP.@constraint(m, sum(pgs) * BASEMVA <= sched_mw[name] + p1.hydro_budget.tolerance_mwh)
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
    # fix 2: units REE needs specifically must be on in the hours REE raised them (on in the
    # day-ahead already counts; a unit that is neither on nor a candidate cannot be forced)
    if p1.units_req !== nothing
        for (k, h) in enumerate(hours), nm in get(p1.units_req, (date_str, h), String[])
            abs(get(scheds[k], nm, 0.0)) >= 1.0 && continue
            haskey(u, (nm, k)) || continue
            short = JuMP.@variable(m, lower_bound = 0.0, upper_bound = 1.0)
            JuMP.@constraint(m, u[(nm, k)] + short >= 1)
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
    empty!(RD_N1_SLACK); empty!(RD_N1_DONE); empty!(RD_N1_PAIR)
    if p1.n1 && JuMP.has_values(m)                                   # RD6: lazy preventive N-1
        sens = rd_ptdf(nets[1].network)
        for r in 1:p1.n1_rounds
            add_n1_cuts!(pm, m, nets, nwk, H, p1, sens; month = Dates.month(Date(date_str))) == 0 && break
            JuMP.optimize!(m)
            JuMP.has_values(m) || break
        end
        # overloads redispatch could not remove, per (monitored branch, outage)
        if JuMP.has_values(m)
            left = Dict{Tuple{String,String},Vector{Float64}}()
            lim_of = Dict{Tuple{String,String},Float64}()
            for (i, (k, s)) in enumerate(RD_N1_SLACK)
                v = JuMP.value(s) * BASEMVA
                v > 1.0 || continue
                key = RD_N1_PAIR[i][1:2]
                push!(get!(left, key, Float64[]), v)
                lim_of[key] = RD_N1_PAIR[i][3]
            end
            for ((mon, out), v) in left
                push!(RD_N1_LEFT_ROWS, (date = date_str, monitored = mon, outage = out, hours = length(v),
                                        mean_mw = round(sum(v) / length(v); digits = 1), max_mw = round(maximum(v); digits = 1),
                                        limit_mw = round(lim_of[(mon, out)]; digits = 1)))
            end
            worst = sort(collect(left); by = kv -> -sum(kv[2]))
            for ((mon, out), v) in first(worst, 5)
                @printf "    N-1 left: %s over by %.0f MW (max %.0f, %d h) after losing %s (limit %.0f MW)\n" mon sum(v) / length(v) maximum(v) length(v) out lim_of[(mon, out)]
            end
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
        RD_PHASE1_STARTCOST[(date_str, h)] = (nst, sum((su_terms(su, gen_of[nm])[2] for ((nm, kk), s) in starts
                                                        if kk == k && JuMP.value(s) > 0.5); init = 0.0))
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
changes for the hour (a new dict; `sched` itself is left untouched).  With
in_chain the balancing schedule already holds them: `sched` unchanged.
"""
function phase1_anchor(sched, date_str, hour)
    # in_chain: the DC changes are in BAL already; only the AC check's own changes (made after the
    # markets) are added — RD_PHASE1_DELTA holds just those then (phase1_in_chain! clears the rest)
    RD_PHASE1_IN_CHAIN && !RD_STARTUPS.phase1.ac_check && return sched
    delta = get(RD_PHASE1_DELTA, (date_str, hour), nothing)
    (delta === nothing || sched === nothing) && return sched
    out = copy(sched)
    for (name, d) in delta
        out[name] = get(out, name, 0.0) + d
    end
    return out
end

"""
    phase1_in_chain!(su, date_str, da_schedule)

[redispatch.phase1].in_chain: phase I/II on this day's DA schedule, run between
the DA and ID2.  Afterwards `da_schedule` holds, for every hour of the day, the
DA schedule plus phase I/II's changes (REE's PDVP), so ID2 (and every later gate
that falls back to the DA schedule) starts from it.  The units phase I started
are written into UC_COMMIT as on at minimum load: ID2/ID3 with intraday starts
keep them on (prev_on), CID and BAL bound them (uc_bounds).  The DA's own
schedule is already in da_dispatch.csv and its price in market_prices.csv.
"""
function phase1_in_chain!(su, date_str, da_schedule)
    run_phase1_day!(su, date_str)
    n_moved = n_kept = 0
    for ts in eachrow(filter(r -> r.date == date_str, hourly_da))
        key = (date_str, ts.hour)
        haskey(da_schedule, key) || continue
        RD_DA_BEFORE_PHASE1[key] = copy(da_schedule[key])         # for the report (rd_phase1.csv da_mw)
        delta = get(RD_PHASE1_DELTA, key, Dict{String,Float64}())
        if !isempty(delta)
            pdvp = copy(da_schedule[key])
            for (name, d) in delta
                pdvp[name] = get(pdvp, name, 0.0) + d
            end
            da_schedule[key] = pdvp
            n_moved += length(delta)
        end
        # the changes are now part of the schedule ID2–BAL start from: nothing is added on top of
        # BAL for them later; after the markets RD_PHASE1_DELTA only holds the AC check's own changes
        RD_PHASE1_DELTA[key] = Dict{String,Float64}()
        on = get(RD_PHASE1_ON, key, Set{String}())
        isempty(on) && continue
        lim = get!(UC_COMMIT, key, Dict{String,Tuple{Bool,Float64}}())
        for name in on
            lim[name] = (true, get(RD_PHASE1_MINLOAD, name, 0.0))
            n_kept += 1
        end
    end
    @printf "    phase I in the chain: %d unit-hours moved from the DA schedule, %d unit-hours kept on in ID2–BAL\n" n_moved n_kept
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

# ── Step C: AC voltage check in phase I ([redispatch.phase1].ac_check) ────────
# REE's phase I is an AC security analysis on the day-ahead schedule; voltage is
# 58 % of its phase I up energy, and its real time has almost no voltage
# redispatch left (2–8 Dec 2024: 0.3 GWh).  The DC phase I sees no voltage, so
# without this check the voltage problems first appear in the model's real time.
# Per hour, after the DC solve: the AC network on the day-ahead profile, anchored
# to phase I's schedule (DA + its changes), with the units phase I committed kept
# on, solved with RD9's start-up loop (and RD5's zone counts if ac_check_zones,
# no real-time reserve).  The AC solution's deviation from the DA becomes phase
# I's change for the hour, the units it starts become phase I commitments (they
# stay on in real time), and rd_phase1*.csv are rewritten for the hour.  With
# ac_check_zones = false the voltage need comes from the AC grid alone, not from
# REE's 2024 data, so a new asset can change it.  After the markets only for now
# (not with in_chain: the AC solve is defined after the market stages).

function phase1_ac_check_day!(su, date_str)
    p1 = su.phase1
    bv = day_bellman[date_str]
    su_ac = merge(su, (reserve = nothing, mustrun = p1.ac_zones ? su.mustrun : nothing))
    day_ts = sort(filter(r -> r.date == date_str, hourly_da), :hour)
    n_ok = n_new = 0
    prev_on = Set{String}()          # units on in the hour before (a unit kept on pays one start)
    for ts in eachrow(day_ts)
        h = Int(ts.hour)
        key = (date_str, h)
        base = phase1_sched_for(date_str, h)
        base === nothing && continue
        pdvp = copy(base)
        for (name, d) in get(RD_PHASE1_DELTA, key, Dict{String,Float64}())
            pdvp[name] = get(pdvp, name, 0.0) + d
        end
        net = prepare_network(rd_load_mw(ts.load_mw - xb_export_offset(date_str, h)), ts.solar_mw, ts.wind_mw;
                              hydro_reservoir_cost = bv.water_value,
                              crossborder_inj = crossborder_inj_for(date_str, h),
                              crossborder_exports = WEEKS_ACTIVE || XB_EXPORT_AT_BORDER,
                              crossborder_bus_caps = RD_XB_SPLIT == "country_total" ? XB_BUS_CAPS : nothing,
                              crossborder_same_direction = RD_XB_SPLIT == "country_total",
                              da_dispatch = pdvp,
                              frozen_fuels = RD_FROZEN_FUELS, island_buses = ISLAND_BUSES, removed_units = REMOVED_UNITS,
                              nuclear_availability = nuclear_avail_for(date_str), coal_availability = coal_avail_for(date_str),
                              chp_blocks = chp_blocks_for(date_str), chp_siting_buses = CHP_SITING_BUSES,
                              voltage_band = VOLTAGE_BAND, line_rating_factor = LINE_RATING_FACTOR,
                              reactors_enabled = REACTORS_ENABLED, reactor_in_service_pct = REACTOR_PCT,
                              reactor_switchable = REACTOR_SWITCHABLE,
                              load_power_factor = LOAD_PF, apparent_power_limit = APPARENT_POWER_LIMIT,
                              rated_power_factor = RATED_PF, renewable_power_factor = RENEWABLE_PF,
                              gen_bus_voltage_control = GEN_BUS_VCTRL, gen_bus_vmin = GEN_BUS_VMIN, gen_bus_vmax = GEN_BUS_VMAX,
                              voltage_limits_by_kv = VOLT_LIMITS_KV, voltage_limits_scope = VOLT_LIMITS_SCOPE,
                              q_requires_online = RD_Q_ONLINE, q_online_min_frac = RD_Q_ONLINE_FRAC,
                              q_condenser_ok = RD_Q_CONDENSER,
                              unit_scale = UNIT_SCALE, cost_override = cost_override_for(date_str),
                              unit_cost_override = unit_cost_override_for(date_str), bess_units = BESS_UNITS,
                              unit_scale_by_id = UNIT_SCALE_ID, extra_units = EXTRA_UNITS, line_scale = LINE_SCALE,
                              rating_scale = RATING_SCALE, extra_lines = EXTRA_LINES)
        network, gens = net.network, net.gens
        RD_BIDS === nothing || (RD_CURRENT_PDA[] = rd_da_price(date_str, h))
        RD_CURRENT_RESERVE[] = 0.0                       # no real-time reserve in phase I
        hydro_budget_cap!(network, pdvp, p1.hydro_budget, "phase1_ac", date_str)     # RD13
        n_rows = length(RD_STARTUP_ROWS)
        log_file = joinpath(IPOPT_LOG_DIR, "$(date_str)_h$(lpad(h, 2, '0'))_ph1ac.log")
        res = solve_hour_with_startups(network, gens, k -> rd_optimizer_single(log_file = su_log(log_file, k)),
                                       pdvp, su_ac; label = "phase I AC $date_str h$h", date_str = date_str, hour = h)
        started = Set{String}()
        for i in n_rows+1:length(RD_STARTUP_ROWS)        # this check's start-ups belong to phase I
            r = RD_STARTUP_ROWS[i]
            push!(started, r.unit)
            RD_STARTUP_ROWS[i] = merge(r, (zone = isempty(r.zone) ? "phase I AC" : "phase I AC: " * r.zone,))
        end
        if !rd_su_ok(res)
            @printf "    phase I AC check %s h%02d: %s, phase I kept as the DC result\n" date_str h string(res["termination_status"])
            prev_on = get(RD_PHASE1_ON, key, Set{String}())
            continue
        end
        n_ok += 1
        hydro_budget_record!(res, network, pdvp, p1.hydro_budget, "phase1_ac", date_str)   # RD13
        sol = res["solution"]["gen"]
        byname = Dict(g["name"] => (k, g) for (k, g) in gens)
        on = union(get(RD_PHASE1_ON, key, Set{String}()), started)
        delta = Dict{String,Float64}()
        for (name, (k, g)) in byname
            (rd_is_market_unit(name) || startswith(name, "BESS_")) && !startswith(name, "RX_") || continue
            haskey(sol, k) || continue
            d = sol[k]["pg"] * BASEMVA - get(base, name, 0.0)
            abs(d) > 1e-3 && (delta[name] = d)
        end
        for name in started
            g = byname[name][2]
            RD_PHASE1_MINLOAD[name] = su_terms(su, g)[1]
        end
        # started by this check and not already on (in the DC result or in the hour before)
        new_starts = setdiff(started, get(RD_PHASE1_ON, key, Set{String}()), prev_on)
        n_new += length(setdiff(started, get(RD_PHASE1_ON, key, Set{String}())))
        RD_PHASE1_ON[key] = on
        RD_PHASE1_DELTA[key] = delta
        # rewrite rd_phase1*.csv for the hour
        p_da = rd_da_price(date_str, h)
        filter!(r -> !(r.date == date_str && r.hour == h), RD_PHASE1_ROWS)
        i_sum = findfirst(r -> r.date == date_str && r.hour == h, RD_PHASE1_SUM)
        old = i_sum === nothing ? nothing : RD_PHASE1_SUM[i_sum]
        up_mwh = dn_mwh = cost = 0.0
        # the report measures phase I against the day-ahead before it: in_chain, `base` already holds
        # the DC changes (they are in the schedule the markets traded from), so measure from the
        # schedule kept before phase I and include the units the DC part moved but this check did not
        orig = RD_PHASE1_IN_CHAIN ? get(RD_DA_BEFORE_PHASE1, key, base) : base
        names = RD_PHASE1_IN_CHAIN ?
            union(keys(delta), (n for n in keys(base) if abs(get(base, n, 0.0) - get(orig, n, 0.0)) > 1e-3 && haskey(byname, n))) :
            keys(delta)
        for name in names
            g = byname[name][2]
            p1mw = get(base, name, 0.0) + get(delta, name, 0.0)
            d = p1mw - get(orig, name, 0.0)
            p_up, p_dn = rd_bid_prices(p1.bids, g, p_da)
            d > 0 ? (up_mwh += d; cost += d * (p_up - p_da)) : (dn_mwh -= d; cost += -d * (p_da - p_dn))
            if abs(d) > 0.5 || name in on
                push!(RD_PHASE1_ROWS, (date = date_str, hour = h, unit = name, fuel = g["fuel"], technology = g["technology"],
                                       da_mw = round(get(orig, name, 0.0); digits = 1),
                                       phase1_mw = round(p1mw; digits = 1), committed = name in on))
            end
        end
        RD_PHASE1_IN_CHAIN && (RD_PHASE1_AC_ROWS[key] = copy(delta))   # the part the markets did not see → real time's anchor
        dc_starts, dc_cost = get(RD_PHASE1_STARTCOST, key, (0, 0.0))
        cost += dc_cost + sum((su_terms(su, byname[n][2])[2] for n in new_starts); init = 0.0)
        row = (date = date_str, hour = h, status = "AC " * string(res["termination_status"]),
               up_mwh = round(up_mwh; digits = 1), down_mwh = round(dn_mwh; digits = 1),
               starts = dc_starts + length(new_starts), units_committed = length(on),
               extra_cost_eur = round(cost; digits = 0), p_da = p_da,
               n1_overload_left_mw = old === nothing ? 0.0 : old.n1_overload_left_mw)
        i_sum === nothing ? push!(RD_PHASE1_SUM, row) : (RD_PHASE1_SUM[i_sum] = row)
        prev_on = on
    end
    @printf "  phase I AC check %s: %d of %d hours solved, %d unit-hours started for voltage\n" date_str n_ok nrow(day_ts) n_new
end

function write_rd_phase1(dir)
    isempty(RD_PHASE1_SUM) && return
    CSV.write(joinpath(dir, "rd_phase1.csv"), DataFrame(RD_PHASE1_ROWS))   # settle.py reads the changes from here too
    CSV.write(joinpath(dir, "rd_phase1_summary.csv"), DataFrame(RD_PHASE1_SUM))
    if !isempty(RD_PHASE1_AC_ROWS)                                         # in_chain + ac_check
        rows = [(date = k[1], hour = k[2], unit = n, ac_mw = round(v; digits = 1))
                for (k, dl) in RD_PHASE1_AC_ROWS for (n, v) in dl if abs(v) > 0.5]
        CSV.write(joinpath(dir, "rd_phase1_ac.csv"),
                  isempty(rows) ? DataFrame(date = String[], hour = Int[], unit = String[], ac_mw = Float64[]) : DataFrame(rows))
    end
    isempty(RD_N1_LEFT_ROWS) || CSV.write(joinpath(dir, "rd_n1_left.csv"), DataFrame(RD_N1_LEFT_ROWS))
    @printf "  rd_phase1*.csv   : %d unit-hours changed, %d hours ([redispatch.phase1])\n" length(RD_PHASE1_ROWS) length(RD_PHASE1_SUM)
end
