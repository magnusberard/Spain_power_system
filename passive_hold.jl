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
# for the same hour (price_setter "Held (passive)"), so the price files keep every stage.
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
    end
    store_stage_result!(schedule, rows_acc, date_str, day_ts, nets, sched)
    prev = Dict((r.stage, r.hour) => r.price_eur_mwh for r in price_rows_all if string(r.date) == string(date_str))
    n_price = 0
    for ts in eachrow(day_ts)
        p = get(prev, (prev_label_for(ts.hour), ts.hour), nothing)
        p === nothing && continue
        push!(price_rows_all, (date = date_str, hour = ts.hour, stage = label, price_eur_mwh = p,
                               price_setter = "Held (passive)", setter_unit = "", setter_rule = "hold"))
        n_price += 1
    end
    @printf "  %s %s : held (passive: all [participation] shares 0, previous schedule kept, %d prices repeated)\n" label date_str n_price
    return nothing
end
