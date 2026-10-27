# How much of each forecast update the intraday stages trade ([participation]),
# and which units may move in the balancing stage ([balancing].eligible).
#
# Participation: each intraday stage (ID2, ID3, CID) clears against a forecast
# that is only partly updated from what the previous stage planned,
#
#   planned_g = planned_(g-1) + α_(g,s) · (forecast_g − planned_(g-1))
#
# per source s (load, wind, solar). Balancing keeps the full final forecast, so
# whatever the intraday stages leave untraded is balanced there. α = 1 is
# PowerVision's active case (every actor trades its whole update; the model's
# behaviour before this switch), α = 0 the passive case (Koks et al. 2026).
# Measured for CID from REE e·sios, 14 Jun–31 Dec 2024: wind 0.07, solar (PV +
# thermal) 0.06, load 0.07 — the slope of the change between the schedule after
# the last auction (PHF2 in hours 0–11, PHF3 in 12–23) and after continuous
# trading (PHFC) on the error left after the last auction (actual − PHF).
#
# Balancing: in Spain only units qualified by REE provide balancing energy
# (aFRR, mFRR, RR), and the same qualification admits units to phase II of the
# technical constraints (P.O. 3.2 §6.2, BOE-A-2024-6215; renewables may qualify
# since the Resolution of 18 Dec 2015, BOE-A-2015-13875). Units outside the list
# hold their previous-gate (CID) MW; wind and solar keep their curtailment and
# nuclear its day-ahead freeze. An empty list lets every unit move.
using DataFrames

const PARTICIPATION_STAGES  = ("id2", "id3", "cid")
const PARTICIPATION_SOURCES = ("load", "wind", "solar")
const BAL_ALWAYS_FREE = ("Wind", "Solar", "Nuclear", "Slack", "LoadShed", "CrossBorder")

# stage ⇒ source ⇒ α from [participation]; missing entries are 1.0
function load_participation(cfg)
    p = get(cfg, "participation", Dict{String,Any}())
    shares = Dict(st => Dict(src => Float64(get(get(p, st, Dict{String,Any}()), src, 1.0))
                             for src in PARTICIPATION_SOURCES)
                  for st in PARTICIPATION_STAGES)
    for st in PARTICIPATION_STAGES, src in PARTICIPATION_SOURCES
        0.0 <= shares[st][src] <= 1.0 ||
            error("config.toml: [participation].$st.$src must be within 0..1, got $(shares[st][src])")
    end
    return shares
end
participation_active(shares) = any(a != 1.0 for d in values(shares) for a in values(d))

# Replace the stage's load/wind/solar MW in `hours` by the partly updated value
# relative to `base` (the previous stage's planned values, same rows).
function blend_stage!(stage::DataFrame, base::DataFrame, shares; hours = 0:23)
    (stage.date == base.date && stage.hour == base.hour) ||
        error("[participation]: stage tables are not aligned by date and hour")
    for (col, src) in ((:load_mw, "load"), (:wind_mw, "wind"), (:solar_mw, "solar"))
        a = shares[src]
        a == 1.0 && continue
        for i in 1:nrow(stage)
            stage.hour[i] in hours || continue
            b = base[i, col]
            stage[i, col] = b + a * (stage[i, col] - b)
        end
    end
    return stage
end

# Blend ID2 on DA, ID3 (hours 12–23) on ID2, CID on ID3 in hours 12–23 and on ID2
# before (ID3 trades 12–23 only); a disabled stage passes its predecessor on.
function apply_participation!(da, id2, id3, cid, shares; id2_on = true, id3_on = true, cid_on = true)
    id2_on && blend_stage!(id2, da, shares["id2"])
    pre_id3 = id2_on ? id2 : da
    id3_on && blend_stage!(id3, pre_id3, shares["id3"]; hours = 12:23)
    if cid_on
        blend_stage!(cid, pre_id3, shares["cid"]; hours = 0:11)
        blend_stage!(cid, id3_on ? id3 : pre_id3, shares["cid"]; hours = 12:23)
    end
    return nothing
end

# May a unit of this fuel / technology move in balancing? Entries are "Fuel" or
# "Fuel:technology" (case-insensitive technology match).
bal_may_move(fuel, tech, eligible) =
    isempty(eligible) || fuel in BAL_ALWAYS_FREE || fuel in eligible ||
    lowercase("$(fuel):$(tech)") in lowercase.(eligible)

# Fix every unit that may not move at its MW in `hold_sched[(date, hour)]`;
# `nets` are prepare_network's per-hour outputs (named tuples with `gens`).
function hold_units!(nets, day_ts, date_str, hold_sched, eligible, basemva)
    n_held = 0
    for (h_idx, ts) in enumerate(eachrow(day_ts))
        ps = get(hold_sched, (date_str, ts.hour), nothing)
        ps === nothing && continue
        for g in values(nets[h_idx].gens)              # the dict solve_da reads
            bal_may_move(String(g["fuel"]), String(g["technology"]), eligible) && continue
            v = get(ps, String(g["name"]), nothing)
            v === nothing && continue
            g["pmin"] = g["pmax"] = g["pg0"] = v / basemva
            n_held += 1
        end
    end
    return n_held
end
