# [participation].hold_when_passive: an intraday stage whose [participation] shares are
# all 0.0 does not clear; it keeps the previous stage's schedule.
#
# Why (11 Nov 2026): with every share at 0.0 a stage sees exactly the previous
# stage's load, wind and solar, but it still re-solved the whole day: the unit
# commitment of ID2/ID3 with intraday starts, the hydro budget, and (phase I in the
# chain) the move away from REE's PDVP. Those re-solves moved plants that nobody had a
# reason to trade (2024 Passive, after the traded-volume fix: ID3 0.11 GWh/day, CID
# 0.03, all CCGT / reservoir / pumped storage; ID2 more, re-optimising around phase I).
# PowerVision's passive case (Koks et al. 2026) is "no re-trading after the day-ahead":
# every deviation is left to balancing. A held stage therefore stores the previous
# schedule unchanged and writes the same dispatch rows as a cleared one, so the stage
# files, the redispatch anchors and the viewer keep working.
#
# Prices: no auction clears in a held stage. Its rows repeat the previous stage's price
# for the same hour with its setter (setter_rule "hold"), so the price files keep every stage.
# Unit commitment: a held ID2/ID3 writes the next day's carry-over as a cleared one that
# changed nothing would (hold_carry_over!), so phase I's units stay on into the next day.
#
# Defined after [participation] is read (run_market_chain.jl includes this file there).

const PASSIVE_HOLD = Bool(get(get(cfg, "participation", Dict{String,Any}()), "hold_when_passive", false))

stage_holds(st::AbstractString) = PASSIVE_HOLD && all(a == 0.0 for a in values(PARTICIPATION[st]))

"""
    hold_stage!(schedule, rows_acc, label, date_str, day_ts, base_for, prev_label_for; nuclear_sched)

Store `base_for(date_str, hour)` (the previous stage's MW per unit) as this stage's
schedule for every hour of `day_ts`, write its dispatch rows, and repeat the price of
stage `prev_label_for(hour)`. Errors if an hour has no previous schedule.
"""
function hold_stage!(schedule, rows_acc, label, date_str, day_ts, base_for, prev_label_for; nuclear_sched = nothing)
    nets = build_da_nets(date_str, day_ts; nuclear_sched = nuclear_sched)
    sched = Dict{Int,Dict{String,Float64}}()
    for (h_idx, ts) in enumerate(eachrow(day_ts))
        ps = base_for(date_str, ts.hour)
        ps === nothing && error("[participation].hold_when_passive: no previous schedule for $label $date_str hour $(ts.hour)")
        sched[h_idx] = Dict(String(g["name"]) => get(ps, String(g["name"]), 0.0) for (_, g) in nets[h_idx].gens)
        rec = get(BESS_DRAW, ps, nothing)            # [bess] the kept schedule keeps its charge changes (da.jl)
        rec === nothing || (BESS_DRAW[sched[h_idx]] = rec)
    end
    store_stage_result!(schedule, rows_acc, date_str, day_ts, nets, sched)
    # the held hour repeats the previous stage's price and its setter (plant and label), so the
    # viewer's price-setter view shows who set it; setter_rule "hold" marks the hour as held
    prev = Dict((r.stage, r.hour) => r for r in price_rows_all if string(r.date) == string(date_str))
    n_price = 0
    for ts in eachrow(day_ts)
        r = get(prev, (prev_label_for(ts.hour), ts.hour), nothing)
        r === nothing && continue
        push!(price_rows_all, (date = date_str, hour = ts.hour, stage = label, price_eur_mwh = r.price_eur_mwh,
                               price_setter = r.price_setter, setter_unit = r.setter_unit, setter_rule = "hold"))
        n_price += 1
    end
    label in ("ID2", "ID3") && hold_carry_over!(date_str, day_ts, nets)
    @printf "  %s %s : held (passive: all [participation] shares 0, previous schedule kept, %d prices repeated)\n" label date_str n_price
    return nothing
end

"""
    hold_carry_over!(date_str, day_ts, nets)

A held ID2/ID3 leaves the next day's starting state (UC_STATE) as a cleared ID2/ID3 that changed
nothing would (run_market_chain.jl, run_copper_plate!): with intraday starts a cleared stage starts from
UC_COMMIT (the DA's commitment plus the units phase I keeps on, prev_on) and writes its end of day as the
carry-over. A held stage wrote nothing, so the next day started from the DA's end of day, which does not
know phase I's units: phase I started them again in hour 0 (2024 Passive, ce853fc: 2,691 phase I starts in
hour 0 against 766 in the same run without the hold, 754 Active; +118 MEUR phase I cost). Without intraday
starts a cleared ID2/ID3 does not write the carry-over either, so neither does a held one.
"""
function hold_carry_over!(date_str, day_ts, nets)
    (UC_CFG === nothing || !UC_CFG.intraday_starts) && return nothing
    units = uc_units_for(nets, date_str, UC_CFG, FUEL_PRICES; fuel_th = UC_GAS_FUEL_TH)
    init  = get(UC_INIT_FOR_DAY, String(date_str), nothing)
    H     = nrow(day_ts)
    none  = Dict{String,Tuple{Bool,Float64}}()
    on(h, name) = first(get(get(UC_COMMIT, (String(date_str), day_ts.hour[h]), none), name, (false, 0.0)))
    state = Dict{String,NamedTuple{(:on, :up, :down),Tuple{Bool,Int,Int}}}()
    for name in keys(units)
        last = on(H, name)
        run  = 0
        for h in H:-1:1
            on(h, name) == last || break
            run += 1
        end
        if run == H && init !== nothing && haskey(init, name) && init[name].on == last
            run = min(run + (last ? init[name].up : init[name].down), 10_000)
        end
        state[name] = (on = last, up = last ? run : 0, down = last ? 0 : run)
    end
    empty!(UC_STATE); merge!(UC_STATE, state); UC_STATE_DATE[] = String(date_str)
    return nothing
end
