# ============================================================
# Steps RD10 + RD11 of redispatch_realism/: REE's objective and pay-as-bid
# prices in the redispatch ([redispatch].objective = "ree", [redispatch.bids]).
#
# REE picks the technically valid solution with the lowest cost: redispatched
# energy at its bid minus the same energy at the day-ahead price (P.O. 3.2
# §6.1.3); ties go to the least energy moved.  Phase I pays upward energy its
# own bid (start-ups included, RD9) and refunds downward energy at the
# day-ahead price (P.O. 3.2 Annex I 1.1.1).  So per free unit g, with
# P_g = anchor + up − down:
#
#     min  Σ (bid_up_g − p_DA)·up_g + Σ (p_DA − refund_g)·down_g + ε·Σ (up_g + down_g)
#
# refund = p_DA (phase I rule, down_refund = "da") or the unit's down bid
# (real time and phase II, down_refund = "bid").  bid_up = max(c_g, p_DA)·(1 + up_markup)
# — a unit left out of the market bids at least the day-ahead price — so every
# swap costs money and only moves a constraint forces survive.  That is why REE
# never redispatches for economics, and why this objective needs no anchor.
#
# Storage at its opportunity cost (RD11): reservoir and pumped hydro (and
# batteries) bid the day-ahead price, not their near-zero marginal cost, since
# water or charge used now is missing in another hour.  Without this, pumped
# storage supplied 3.3 TWh of the model's 4.4 TWh "up" in 2024.
#
# Mark-ups by fuel/technology come from [redispatch.bids]; REE's 2024 prices per
# unit and hour are in the I90 files (redispatch_realism/fetch_i90.py) to fit
# them.  Constant water value path only.
# ============================================================

function load_rd_bids(cfg)
    b = get(get(cfg, "redispatch", Dict()), "bids", Dict())
    table = Dict{String,Tuple{Float64,Float64}}()
    for row in get(b, "by_type", Any[])
        table[lowercase(String(row["type"]))] = (Float64(get(row, "up_markup", 0.0)), Float64(get(row, "down_markup", 0.0)))
    end
    # F2 (6 Nov 2026): real time's own up mark-ups, [[redispatch.bids.rt_by_type]] type = … up_markup = …
    # (fit_rt_upmarkup.py: CCGT 1.387 from REE's real-time I90 prices Jan-Jun 2024; Jul-Dec error in the PAID price
    # 22 vs 77 EUR/MWh with phase I's 0.451). Used only in real time (RD_OFFER_KEY[] === nothing). NOT ADOPTED:
    # the reported cost is paid − p_DA, and with the model's day-ahead price too low in winter it overshot REE's
    # real-time cost per MWh by 28-45 % in the Jan/Apr/Dec test weeks (0.74-0.95x without it). Off unless set.
    rt_table = Dict{String,Float64}()
    for row in get(b, "rt_by_type", Any[])
        rt_table[lowercase(String(row["type"]))] = Float64(row["up_markup"])
    end
    isempty(rt_table) || println("  [redispatch.bids] real-time up mark-ups: ", join(("$k $(v)" for (k, v) in rt_table), ", "))
    load_rd_offers!(String(get(b, "offers_file", "")), cfg)
    load_rd_offer_rule!(String(get(b, "offers_rule", "")))
    return (up_markup     = Float64(get(b, "up_markup", 0.0)),
            down_markup   = Float64(get(b, "down_markup", 0.0)),
            down_refund   = lowercase(String(get(b, "down_refund", "da"))),
            tie_break     = Float64(get(b, "tie_break_eur_mwh", 0.5)),
            by_type       = table,
            rt_by_type    = rt_table)
end

# ------------------------------------------------------------
# Step 4 (plan of 1 Nov 2026): phase II's down offers from REE's own buy-back offers.
# P.O. 3.2 §6.2.2: phase II takes the offers to reduce the schedule in decreasing price. REE's I90DIA17 holds every
# such offer; build_phase2_offers.py turns them into a curve per model unit and hour (its REE units' blocks) and per
# fuel:technology and hour (all REE units of that technology, pooled), as segments (share of the unit's own
# schedule, price), highest buy-back price first. [redispatch.bids].offers_file names the file; without it, or for a
# unit and hour with no curve, the [redispatch.bids] values (B) stay. Two stated rules:
#   - the refund is capped at the day-ahead price: phase II only restores the balance after phase I, and REE never
#     redispatches for profit (P.O. 3.2 §6.2), so an offer above p_DA comes first but earns nothing;
#   - used in phase I (DC day problem and its AC check) only, where phase II happens; real time keeps the
#     [redispatch.bids] values (REE's real-time offers, I90DIA32, are not used yet).
# Pumped storage has no curve (kept out of phase II, decision of 30 Oct): its [redispatch.bids] value stays.
const RD_OFFERS = Dict{Tuple{String,Int,String},Vector{Tuple{Float64,Float64}}}()   # (date, hour, key) ⇒ [(share, €/MWh)]
const RD_OFFERS_LOADED = Ref(false)
const RD_OFFER_KEY = Ref{Union{Nothing,Tuple{String,Int}}}(nothing)   # (date, hour) while phase I's AC check solves

function load_rd_offers!(f, cfg)
    (RD_OFFERS_LOADED[] || isempty(f)) && return
    RD_OFFERS_LOADED[] = true
    f = isabspath(f) ? f : joinpath(@__DIR__, f)
    run = get(cfg, "run", Dict())
    lo, hi = String(get(run, "from", "0000")), String(get(run, "to", "9999"))
    n = 0
    for r in CSV.File(f; types = Dict(:date => String, :key => String))
        (lo <= r.date <= hi) || continue
        push!(get!(RD_OFFERS, (r.date, Int(r.hour), lowercase(r.key)), Tuple{Float64,Float64}[]),
              (Float64(r.share), Float64(r.price)))
        n += 1
    end
    for v in values(RD_OFFERS)                       # highest buy-back price first (cheapest to turn down)
        sort!(v; by = last, rev = true)
    end
    @printf "Phase II offers : %d curves (%d segments) from %s (REE I90DIA17, step 4)\n" length(RD_OFFERS) n f
end

# The rule for runs without REE's offers (2035): [redispatch.bids].offers_rule, built by build_offer_rule.py from 2024's
# offers (estimated Jan–Jun, tested Jul–Dec; ratio form): per fuel:technology, segments (share of the unit's schedule,
# buy-back price = ratio × p_DA), highest price first. Used where a unit and hour have no curve from offers_file.
const RD_OFFER_RULE = Dict{String,Vector{Tuple{Float64,Float64}}}()     # "fuel:technology" ⇒ [(share, ratio)]
function load_rd_offer_rule!(f)
    (isempty(f) || !isempty(RD_OFFER_RULE)) && return
    f = isabspath(f) ? f : joinpath(@__DIR__, f)
    for r in CSV.File(f; types = Dict(:technology => String))
        push!(get!(RD_OFFER_RULE, lowercase(r.technology), Tuple{Float64,Float64}[]), (Float64(r.share), Float64(r.ratio)))
    end
    for v in values(RD_OFFER_RULE)
        sort!(v; by = last, rev = true)
    end
    @printf "Phase II offer rule: %d technologies from %s (build_offer_rule.py)\n" length(RD_OFFER_RULE) f
end

"""
    rd_down_curve(g, key, p_da = NaN) -> [(share, €/MWh)] or nothing

The unit's own buy-back curve for (date, hour), else its fuel:technology's pooled curve, else (with p_da and an
[redispatch.bids].offers_rule) the rule's curve for its fuel:technology at that day-ahead price, else nothing.
"""
function rd_down_curve(g, key, p_da = NaN)
    key === nothing && return nothing
    (g["fuel"] == "Hydro" && lowercase(g["technology"]) == "pumped_storage") && return nothing
    if !isempty(RD_OFFERS)
        c = get(RD_OFFERS, (key[1], key[2], lowercase(String(g["name"]))), nothing)
        c === nothing || return c
        c = get(RD_OFFERS, (key[1], key[2], lowercase("tech:$(g["fuel"]):$(g["technology"])")), nothing)
        c === nothing || return c
    end
    (isempty(RD_OFFER_RULE) || isnan(p_da)) && return nothing
    r = get(RD_OFFER_RULE, lowercase("$(g["fuel"]):$(g["technology"])"), nothing)
    r === nothing && return nothing
    return [(s, max(q * p_da, 0.0)) for (s, q) in r]
end

"""
    rd_add_down_cost!(model, obj, dn, g, tgt_pu, p_da, p_dn, tie, key)

Add the cost of turning unit g down by `dn` (pu) to `obj`: on its offer curve if it has one in this hour (segment i
at most share_i × its schedule, at p_DA − min(price_i, p_DA) + tie), otherwise at the [redispatch.bids] refund p_dn.
A last segment at the full p_DA keeps the problem feasible if the shares round below 1.
"""
function rd_add_down_cost!(model, obj, dn, g, tgt_pu, p_da, p_dn, tie, key)
    c = rd_down_curve(g, key, p_da)
    if c === nothing || tgt_pu <= 1e-9
        JuMP.add_to_expression!(obj, (p_da - p_dn + tie) * BASEMVA, dn)
        return
    end
    segs = JuMP.@variable(model, [1:length(c)], lower_bound = 0.0)
    rest = JuMP.@variable(model, lower_bound = 0.0)
    for (i, (s, pr)) in enumerate(c)
        JuMP.set_upper_bound(segs[i], s * tgt_pu)
        JuMP.add_to_expression!(obj, (p_da - min(pr, p_da) + tie) * BASEMVA, segs[i])
    end
    JuMP.add_to_expression!(obj, (p_da + tie) * BASEMVA, rest)
    JuMP.@constraint(model, dn == sum(segs) + rest)
    return
end

"""
    rd_down_cost_eur(g, down_mw, sched_mw, p_da, p_dn, key) -> EUR

The cost of turning g down by `down_mw` from `sched_mw`, as rd_add_down_cost! prices it (for the reports).
"""
function rd_down_cost_eur(g, down_mw, sched_mw, p_da, p_dn, key)
    c = rd_down_curve(g, key, p_da)
    (c === nothing || sched_mw <= 1e-6) && return down_mw * (p_da - p_dn)
    left, cost = down_mw, 0.0
    for (s, pr) in c
        take = min(left, s * sched_mw)
        cost += take * (p_da - min(pr, p_da))
        left -= take
        left <= 1e-9 && break
    end
    return cost + max(left, 0.0) * p_da
end

# Day-ahead price of the hour being solved: set by the hourly loop.
const RD_CURRENT_PDA = Ref(NaN)
const RD_SAVED_PDA = Dict{Tuple{String,Int},Float64}()

"""
    rd_da_price(date_str, hour) -> EUR/MWh

From this run's day-ahead prices, or (standalone load flow) from the saved
results/market_prices.csv.
"""
function rd_da_price(date_str, hour)
    for r in price_rows_all
        (r.stage == "DA" && r.date == date_str && r.hour == hour) && return Float64(r.price_eur_mwh)
    end
    if isempty(RD_SAVED_PDA)
        f = joinpath(RESULTS, "market_prices.csv")
        isfile(f) || error("objective = \"ree\" needs the day-ahead price: no DA rows in this run and no $f")
        for r in eachrow(CSV.read(f, DataFrame))
            String(r.stage) == "DA" && (RD_SAVED_PDA[(string(r.date), Int(r.hour))] = Float64(r.price_eur_mwh))
        end
    end
    return get(RD_SAVED_PDA, (date_str, hour)) do
        error("objective = \"ree\": no day-ahead price for $date_str h$hour")
    end
end

rd_is_storage(g) = g["fuel"] == "Battery" ||
                   (g["fuel"] == "Hydro" && lowercase(g["technology"]) in ("reservoir", "pumped_storage"))

function rd_markups(bids, g)
    k = lowercase("$(g["fuel"]):$(g["technology"])")
    haskey(bids.by_type, k) && return bids.by_type[k]
    f = lowercase(String(g["fuel"]))
    haskey(bids.by_type, f) && return bids.by_type[f]
    # A technology missing from the table takes its fuel's mark-ups (the mean over the fuel's rows),
    # not the global default: with down_markup = 0 a missing technology refunded 100 % of p_DA, so
    # turning it down cost nothing (solar thermal, 3.1 TWh in 2024 before 26 Oct).
    same = [v for (kk, v) in bids.by_type if startswith(kk, f * ":")]
    isempty(same) && return (bids.up_markup, bids.down_markup)
    return (sum(first, same) / length(same), sum(last, same) / length(same))
end

"""
    rd_bid_prices(bids, g, p_da) -> (price paid per MWh up, refund per MWh down)
"""
function rd_bid_prices(bids, g, p_da; rt::Bool = false)
    mu, md = rd_markups(bids, g)
    if rt && !isempty(get(bids, :rt_by_type, Dict{String,Float64}()))                # F2: real time's own up mark-up
        mu = get(bids.rt_by_type, lowercase("$(g["fuel"]):$(g["technology"])"), mu)
    end
    c = rd_is_storage(g) ? p_da : g["cost"][1] / BASEMVA
    up = max(c, p_da) * (1 + mu)
    # "da": phase I's refund at the day-ahead price; "bid": the unit's cost-based down bid;
    # "bid_da" (RD12): phase II's down bids as a share of the day-ahead price, fitted per
    # technology to REE's 2024 phase II (fit_phase2_bids.py: ~0.95)
    dn = bids.down_refund == "da" ? p_da : bids.down_refund == "bid_da" ? p_da * (1 - md) : c * (1 - md)
    return up, dn
end

"""
    rd_ree_objective!(pm, gens, sched, bids, p_da)

Replace the model's objective with REE's (see the header).  Units the schedule
does not contain (started units' anchor is 0 MW) are anchored at 0.
"""
function rd_ree_objective!(pm, gens, sched, bids, p_da, xb_ct_cost)
    obj = zero(JuMP.AffExpr)
    for (_, g) in gens
        pg = PowerModels.var(pm, :pg, g["index"])
        name = g["name"]
        if startswith(name, "SLACK") || startswith(name, "LS_")
            JuMP.add_to_expression!(obj, g["cost"][1], pg)            # last-resort penalties stay
            continue
        end
        (rd_is_market_unit(name) || startswith(name, "BESS_")) || continue
        abs(g["pmax"] - g["pmin"]) > 1e-9 || continue                  # frozen
        startswith(name, "QS_") && continue                           # RD9 diagnostic slack
        tgt = get(sched, name, 0.0) / BASEMVA
        up   = JuMP.@variable(pm.model, lower_bound = 0.0)
        down = JuMP.@variable(pm.model, lower_bound = 0.0)
        JuMP.@constraint(pm.model, pg == tgt + up - down)
        p_up, p_dn = rd_bid_prices(bids, g, p_da; rt = RD_OFFER_KEY[] === nothing)    # F2: not in phase I's AC check
        JuMP.add_to_expression!(obj, (p_up - p_da + bids.tie_break) * BASEMVA, up)
        # step 4: REE's buy-back offers in phase I's AC check (RD_OFFER_KEY set); real time keeps the bids
        rd_add_down_cost!(pm.model, obj, down, g, tgt, p_da, p_dn, bids.tie_break, RD_OFFER_KEY[])
    end
    JuMP.@objective(pm.model, Min, obj + xb_ct_cost)
    return
end
