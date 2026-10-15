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
# Coal ([unit_commitment.coal]), same rules, Intertek's subcritical classes by
# installed MW (small 35–299 MW, large 300–900 MW; Intertek 2020 p. 6):
#   min up / down, min load            Table 2: small 720 / 360 min, 40 %;
#                                      large 720 / 480 min, 35 %.
#   start wear (warm, median, 2020 $)  Table 4: small 112, large 64 $/MW, same
#                                      2020→2024 $ and $→EUR conversion as gas.
#   start fuel 5.7 MWh fuel per MW     DIW Data Documentation 68, Table 25,
#                                      coal warm start (Meibom et al. 2008),
#                                      priced at the unit's coal + CO2 cost per
#                                      MWh of fuel = EUR/MWh_el cost × eta 0.435
#                                      (EMPIRE's coal efficiency).
# Assumption: all Spanish coal units are subcritical (not checked per unit).
# With use_availability_factor = true the fleet-wide coal availability factor
# still scales each unit (a closure proxy); with false (the setting here) units
# run at full size and closed plants are removed via [fleet].closed_units.
# ASSUMPTION (ours): units of `two_by_one_min_mw` (700 MW) or more are 2x1
# (two gas turbines + one steam turbine) and get the 2x1 minimum load.  Neither
# generations.csv nor GEM gives the layout; the 54 Spanish CCGTs of 100 MW or
# more split into 43 of 200-435 MW and 11 of 782-859 MW with none between, and
# ~400 MW is a typical 1x1, ~800 MW a typical 2x1.
#
# Carry-over (run_market_chain.jl, UC_STATE): each unit's state at the end of a
# DA day (on/off, hours in that state) is the next day's starting point when the
# next study day is the following calendar day — so a start after midnight is
# paid and minimum up/down times run across midnight.  On the FIRST day of a
# run (or after a gap in the study days) a unit running in hour 1 counts as
# already on (no start cost) — a stated simplification.
# The later gates (ID2, ID3, CID, BAL) keep the DA on/off: off ⇒ 0 MW, on ⇒
# between min load and max (da.jl, uc_bounds); they cannot start a unit.
# ============================================================

struct UCUnit
    name       :: String    # generations.csv unit_id
    mw         :: Float64   # capacity this day (max pmax over the day)
    min_load   :: Float64   # fraction of the hour's pmax
    min_up     :: Int       # hours
    min_down   :: Int       # hours
    start_cost :: Float64   # EUR per start
    var_cost   :: Float64   # EUR/MWh this day (its fuel + CO2 + VOM cost in nets)
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
            time_limit_s      = Float64(get(c, "time_limit_s", 600.0)),
            mic_check         = Bool(get(c, "mic_check", false)),
            max_rounds        = Int(get(c, "max_rounds", 100)),
            coal              = load_uc_coal(c))
end

# [unit_commitment.coal]: the same rules for the coal fleet; `nothing` when off.
# Intertek's two subcritical classes, chosen by the unit's installed MW
# (Intertek 2020 defines small subcritical as 35–299 MW, large as 300–900 MW).
function load_uc_coal(c)
    k = get(c, "coal", Dict())
    get(k, "enabled", false) || return nothing
    usd(x) = Float64(x) * Float64(c["usd_inflator_to_2024"]) / Float64(c["usd_per_eur"])
    return (min_mw            = Float64(k["min_mw"]),
            large_min_mw      = Float64(k["large_min_mw"]),
            small = (min_up = Int(k["min_up_h_small"]), min_down = Int(k["min_down_h_small"]),
                     min_load = Float64(k["min_load_small"]), wear_eur_per_mw = usd(k["start_wear_usd_per_mw_small"])),
            large = (min_up = Int(k["min_up_h_large"]), min_down = Int(k["min_down_h_large"]),
                     min_load = Float64(k["min_load_large"]), wear_eur_per_mw = usd(k["start_wear_usd_per_mw_large"])),
            start_fuel_mwh_per_mw = Float64(k["start_fuel_mwh_per_mw"]),
            eta = Float64(k["eta"]),
            use_availability_factor = Bool(get(k, "use_availability_factor", true)))
end

"""
    uc_units_for(nets, date_str, ucc, fp) -> Dict{String,UCUnit}

The committed units for one day: every Gas/Combined_cycle unit in `nets`
(and, with [unit_commitment.coal], every coal unit; see below)
whose largest hourly pmax is at least `ucc.min_mw`.
"""
function uc_units_for(nets, date_str, ucc, fp)
    fuel_th = gas_fuel_cost_th(fp, Date(String(date_str)))      # EUR/MWh of gas
    start_eur_per_mw = ucc.wear_eur_per_mw + ucc.start_fuel_mwh_per_mw * fuel_th
    mw  = Dict{String,Float64}()
    vc  = Dict{String,Float64}()
    for net in nets, (_, g) in net.gens
        (g["fuel"] == "Gas" && g["technology"] == "Combined_cycle") || continue
        mw[g["name"]] = max(get(mw, g["name"], 0.0), g["pmax"] * BASEMVA)
        vc[g["name"]] = g["cost"][1] / BASEMVA
    end
    units = Dict{String,UCUnit}()
    for (name, m) in mw
        m >= ucc.min_mw || continue
        ml = m >= ucc.two_by_one_min_mw ? ucc.min_load_2x1 : ucc.min_load_1x1
        units[name] = UCUnit(name, m, ml, ucc.min_up, ucc.min_down, start_eur_per_mw * m, vc[name])
    end
    # Coal ([unit_commitment.coal]): class by installed MW; start fuel priced at
    # the unit's own fuel + CO2 cost per MWh of fuel = its EUR/MWh_el cost × eta
    # (the model's coal cost is one figure incl. CO2; VOM ignored here).
    cc = get(ucc, :coal, nothing)
    if cc !== nothing
        cmw = Dict{String,Float64}(); cvc = Dict{String,Float64}(); cinst = Dict{String,Float64}()
        for net in nets, (_, g) in net.gens
            g["fuel"] == "Coal" || continue
            cmw[g["name"]]   = max(get(cmw, g["name"], 0.0), g["pmax"] * BASEMVA)
            cvc[g["name"]]   = g["cost"][1] / BASEMVA
            cinst[g["name"]] = Float64(get(g, "installed_mw", g["pmax"] * BASEMVA))
        end
        for (name, m) in cmw
            (m >= 1.0 && cinst[name] >= cc.min_mw) || continue
            p = cinst[name] >= cc.large_min_mw ? cc.large : cc.small
            start_per_mw = p.wear_eur_per_mw + cc.start_fuel_mwh_per_mw * cvc[name] * cc.eta
            units[name] = UCUnit(name, m, p.min_load, p.min_up, p.min_down, start_per_mw * m, cvc[name])
        end
    end
    return units
end

# ── Minimum-income check ([unit_commitment].mic_check) ───────────────────────
# Spain's day-ahead in 2024 accepted a unit's bids only if the day's income
# covered its minimum-income condition: a fixed term (EUR) plus a variable term
# (EUR/MWh) (OMIE Reglas de funcionamiento §6.3.1.2; EUPHEMIA Public Description
# §5.2.1).  Cost-based here (our interpretation): fixed term = this day's
# starts x start cost, variable term = the unit's own EUR/MWh cost.  A unit
# carried on from the night before without a start has no fixed term.
#
# The clearing follows the published procedures:
#   1. clear (MIP + fixed-integer LP for the prices, da.jl);
#   2. find the running units whose income at those prices is below their
#      condition ("paradoxically accepted"); remove the one with the largest
#      gap between the average price its condition requires and the average
#      price it received, EUR/MWh (OMIE §6.3.1.2, point 3), for the whole day,
#      and clear again; repeat until every running unit passes;
#   3. then try each removed unit that would earn its condition at the final
#      prices back in, one at a time, most profitable first (EUPHEMIA §7.7,
#      "PRMIC reinsertion"; OMIE §6.3.2), keeping it only if no unit then fails
#      and the total cost does not rise;
# at most `max_rounds` clears per day (100: the default of the Comillas
# simulator, Insunza et al. 2026).  A removed unit still runs the hours it must
# stay on from the night before (OMIE's scheduled stop, da.jl).
# Every round is logged → results/uc_rounds.csv.

const MIC_TOL_EUR = 1.0     # income shortfalls below 1 EUR count as met

"""
    mic_check(res, uc) -> Vector of failing units, largest EUR/MWh gap first

Income Σ price·MW against Σ var_cost·MW + starts·start_cost for every unit in
`uc.units` that ran this day and is not removed.
"""
function mic_check(res, uc)
    removed = get(uc, :force_off, Set{String}())
    H = length(res.sched)
    fails = NamedTuple[]
    for (name, u) in uc.units
        name in removed && continue
        mwh    = sum(get(res.sched[h], name, 0.0) for h in 1:H)
        mwh > 0.5 || continue
        income = sum(get(res.es_price, h, 0.0) * get(res.sched[h], name, 0.0) for h in 1:H)
        starts = count(h -> get(res.uc.start, (h, name), false), 1:H)
        cost   = u.var_cost * mwh + starts * u.start_cost
        income < cost - MIC_TOL_EUR || continue
        push!(fails, (unit = name, mwh = mwh, income = income, cost = cost,
                      gap = (cost - income) / mwh, starts = starts))
    end
    sort!(fails; by = f -> -f.gap)
    return fails
end

"""
    mic_reinsert_candidates(res, uc) -> removed units that would earn their
    condition at `res`'s prices, most profitable first

Estimate: running at full output in every hour priced above its cost, minus
one start.
"""
function mic_reinsert_candidates(res, uc)
    H = length(res.sched)
    out = NamedTuple[]
    for name in get(uc, :force_off, Set{String}())
        u = uc.units[name]
        gain = sum(max(0.0, get(res.es_price, h, 0.0) - u.var_cost) * u.mw for h in 1:H) - u.start_cost
        gain > MIC_TOL_EUR && push!(out, (unit = name, gain = gain))
    end
    sort!(out; by = c -> -c.gain)
    return out
end

"""
    mic_clear(solve, uc, max_rounds) -> (result, log)

`solve(uc)` clears the DA with that commitment set-up (solve_da).  Returns the
final result and one log row per clear.
"""
function mic_clear(solve, uc, max_rounds::Int)
    removed = Set{String}()
    log     = NamedTuple[]
    # One row per clear; NaN where a field does not apply (all rows same types).
    fld(f, k) = f === nothing ? NaN : round(Float64(get(f, k, NaN)); digits = 1)
    row(rnd, action, f, obj) = push!(log, (round = rnd, action = String(action),
        unit_id = f === nothing ? "" : String(f.unit),
        mwh = fld(f, :mwh), income_eur = fld(f, :income), cost_eur = fld(f, :cost),
        gap_eur_mwh = fld(f, :gap), objective_eur = round(Float64(obj); digits = 1)))
    ok(r) = r.status in ("OPTIMAL", "LOCALLY_SOLVED") && r.uc !== nothing

    res = solve(merge(uc, (force_off = copy(removed),)))
    ok(res) || return (res, log)
    n = 1
    # Phase 1: remove failing units one at a time
    while true
        fails = mic_check(res, merge(uc, (force_off = removed,)))
        if isempty(fails)
            row(n, "valid", nothing, res.objective)
            break
        end
        if n >= max_rounds
            row(n, "max_rounds", fails[1], res.objective)
            return (res, log)
        end
        f = fails[1]
        row(n, "remove", f, res.objective)
        push!(removed, f.unit)
        n += 1
        res = solve(merge(uc, (force_off = copy(removed),)))
        ok(res) || return (res, log)
    end
    # Phase 2: try removed units back, one at a time
    tried = Set{String}()
    while n < max_rounds
        cands = filter(c -> !(c.unit in tried), mic_reinsert_candidates(res, merge(uc, (force_off = removed,))))
        isempty(cands) && break
        c = cands[1]
        push!(tried, c.unit)
        trial_removed = setdiff(removed, [c.unit])
        n += 1
        trial = solve(merge(uc, (force_off = copy(trial_removed),)))
        if ok(trial) && isempty(mic_check(trial, merge(uc, (force_off = trial_removed,)))) &&
           trial.objective <= res.objective + 1e-6 * abs(res.objective) + MIC_TOL_EUR
            row(n, "reinsert", (unit = c.unit, gap = -c.gain), trial.objective)
            removed = trial_removed
            res = trial
        else
            row(n, "reinsert_rejected", (unit = c.unit, gap = -c.gain), ok(trial) ? trial.objective : NaN)
        end
    end
    return (res, log)
end
