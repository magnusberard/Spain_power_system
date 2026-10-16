# Generation tax and RSI-based mark-ups on the market bids ([costs.markup]).
#
# Every generator's per-MWh cost c (as set by prepare_network) becomes, in the
# market stages (DA, ID2, ID3, CID, BAL; not the redispatch):
#
#   bid = c / (1 - tax)                       taxed fuels (Gas, Coal, Nuclear, ...)
#   bid = c / (1 - tax) / (1 - L_gas(RSI))    gas units (Combined_cycle, Gas_turbine)
#   bid = c / (1 - tax) / (1 - L_coal)        coal units (one constant L)
#
# tax : Spain's tax on the value of electricity production (IVPEE, Ley 15/2012,
#       7 %), paid on all generation and passed into bids. 2024: the tax base was
#       cut by 50 % in Q1 and 25 % in Q2 (Real Decreto-ley 8/2023), i.e. an
#       effective 3.5 % and 5.25 %, then 7 %. CHP/waste/mini-hydro blocks are
#       calibrated market bids (tax already in them); wind, solar and hydro (water
#       value) are left unchanged.
# RSI : Residual Supply Index of the hour, (offered capacity - largest firm's
#       offered capacity) / demand (Sheffrin 2002, CAISO; Newbery 2008, EPRG
#       0821). For 2024 read from Data/markup/rsi_2024.csv, computed from OMIE's
#       day-ahead bids (omie_conversion/markup_rsi.py); a model-side RSI for other
#       years is still to be built.
# L   : Lerner index (bid - cost)/bid over the model's own cost incl. tax, from
#       real 2024 bids near the price (scripts/build_markup_table.py).
#       Gas: the median per RSI interval (table_file), linear interpolation
#       between the interval points, held constant beyond the first and last.
#       Coal: one constant (L_coal in the config), the median over all hours,
#       since coal bids do not follow RSI. Both limited to 0 <= L <= cap (no bid
#       below cost + tax).
using CSV, DataFrames, Dates

struct MarkupCfg
    tax::Dict{String,Float64}            # "2024Q1" => 0.035
    tax_default::Float64
    tax_fuels::Set{String}
    rsi::Dict{Tuple{String,Int},Float64} # (date, hour 0-23) => RSI
    x::Vector{Float64}                   # table: RSI points (increasing)
    l_gas::Vector{Float64}
    l_coal::Float64                      # constant, all hours
    cap::Float64
end

const MARKUP_GAS_TECH = Set(["Combined_cycle", "Gas_turbine"])
const MARKUP_NO_TAX_TECH = Set(["CHP", "CHP_Waste", "mini_hydro"])

function load_markup(cfg; root = @__DIR__)
    m = get(get(cfg, "costs", Dict()), "markup", Dict())
    get(m, "enabled", false) || return nothing
    rs = CSV.read(joinpath(root, m["rsi_file"]), DataFrame)
    tb = sort(CSV.read(joinpath(root, m["table_file"]), DataFrame), :rsi)
    MarkupCfg(Dict(String(k) => Float64(v) for (k, v) in get(m, "tax", Dict())),
              Float64(get(m, "tax_default", 0.07)),
              Set(String.(get(m, "tax_fuels", ["Gas", "Coal", "Nuclear", "Biomass", "Oil"]))),
              Dict((string(r.date), Int(r.hour)) => Float64(r.rsi) for r in eachrow(rs)),
              Float64.(tb.rsi), Float64.(tb.L_gas), Float64(get(m, "L_coal", 0.0)),
              Float64(get(m, "cap", 0.5)))
end

markup_tax(mk::MarkupCfg, d::Date) =
    get(mk.tax, "$(year(d))Q$(quarterofyear(d))", mk.tax_default)

"Piecewise-linear interpolation, constant beyond the ends."
function markup_interp(x, y, r)
    r <= x[1] && return y[1]
    r >= x[end] && return y[end]
    i = searchsortedlast(x, r)
    return y[i] + (r - x[i]) / (x[i+1] - x[i]) * (y[i+1] - y[i])
end

"(tax, rsi, L_gas, L_coal) for one hour; RSI missing → no gas mark-up (L_gas = 0)."
function markup_for(mk::MarkupCfg, date_str, hour::Int)
    tax = markup_tax(mk, Date(String(date_str)))
    r = get(mk.rsi, (String(date_str), hour), NaN)
    lim(v) = clamp(v, 0.0, mk.cap)
    isnan(r) && return (tax, r, 0.0, lim(mk.l_coal))
    return (tax, r, lim(markup_interp(mk.x, mk.l_gas, r)), lim(mk.l_coal))
end

"Scale the generators' linear costs of one day's hourly networks in place; returns one log row per hour."
function apply_markup!(nets, mk::MarkupCfg, date_str, day_ts)
    rows = NamedTuple[]
    for (net, ts) in zip(nets, eachrow(day_ts))
        tax, r, lg, lc = markup_for(mk, date_str, Int(ts.hour))
        for g in values(net.gens)
            f, t = get(g, "fuel", ""), get(g, "technology", "")
            (f in mk.tax_fuels && !(t in MARKUP_NO_TAX_TECH)) || continue
            k = 1 / (1 - tax)
            if f == "Gas" && t in MARKUP_GAS_TECH
                k /= (1 - lg)
            elseif f == "Coal"
                k /= (1 - lc)
            end
            g["cost"][1] *= k
        end
        push!(rows, (date = String(date_str), hour = Int(ts.hour), rsi = r, tax = tax, L_gas = lg, L_coal = lc))
    end
    return rows
end
