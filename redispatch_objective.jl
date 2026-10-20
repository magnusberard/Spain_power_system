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
    return (up_markup     = Float64(get(b, "up_markup", 0.0)),
            down_markup   = Float64(get(b, "down_markup", 0.0)),
            down_refund   = lowercase(String(get(b, "down_refund", "da"))),
            tie_break     = Float64(get(b, "tie_break_eur_mwh", 0.5)),
            by_type       = table)
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
    get(bids.by_type, lowercase("$(g["fuel"]):$(g["technology"])"),
        get(bids.by_type, lowercase(g["fuel"]), (bids.up_markup, bids.down_markup)))
end

"""
    rd_bid_prices(bids, g, p_da) -> (price paid per MWh up, refund per MWh down)
"""
function rd_bid_prices(bids, g, p_da)
    mu, md = rd_markups(bids, g)
    c = rd_is_storage(g) ? p_da : g["cost"][1] / BASEMVA
    up = max(c, p_da) * (1 + mu)
    dn = bids.down_refund == "da" ? p_da : c * (1 - md)
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
        p_up, p_dn = rd_bid_prices(bids, g, p_da)
        JuMP.add_to_expression!(obj, (p_up - p_da + bids.tie_break) * BASEMVA, up)
        JuMP.add_to_expression!(obj, (p_da - p_dn + bids.tie_break) * BASEMVA, down)
    end
    JuMP.@objective(pm.model, Min, obj + xb_ct_cost)
    return
end
