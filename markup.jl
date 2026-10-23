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
    rsi_source::String                   # "file" (rsi), "model" (model_rsi) or "none"
    largest_share::Float64               # model RSI: largest firm's share of offered MW
    rsi_scale::Float64                   # model RSI: slope of the calibration vs OMIE (2024)
    rsi_offset::Float64                  # model RSI: intercept of that calibration
end

const MARKUP_GAS_TECH = Set(["Combined_cycle", "Gas_turbine"])
const MARKUP_NO_TAX_TECH = Set(["CHP", "CHP_Waste", "mini_hydro"])

function load_markup(cfg; root = @__DIR__, scenario::Bool = false)
    m = get(get(cfg, "costs", Dict()), "markup", Dict())
    get(m, "enabled", false) || return nothing
    tb = sort(CSV.read(joinpath(root, m["table_file"]), DataFrame), :rsi)
    # Scenario runs (e.g. 2035) study 2024 calendar dates, so the 2024 tax
    # quarters and the 2024 RSI file must not be read: one tax rate for the
    # whole run (scenario_tax) and no RSI — hence no gas mark-up (L_gas = 0)
    # until the model computes its own RSI; coal keeps the constant L_coal.
    src   = String(get(m, scenario ? "scenario_rsi_source" : "rsi_source", scenario ? "none" : "file"))
    src in (scenario ? ("model", "none") : ("file", "model", "none")) ||
        error("config.toml: [costs.markup] RSI source \"$src\" not allowed " *
              (scenario ? "in scenario runs (\"model\" or \"none\")" : "(\"file\", \"model\" or \"none\")"))
    share = Float64(get(m, "largest_share", 0.214))
    scale = Float64(get(m, "rsi_scale", 1.0))
    offs  = Float64(get(m, "rsi_offset", 0.0))
    fuels = Set(String.(get(m, "tax_fuels", ["Gas", "Coal", "Nuclear", "Biomass", "Oil"])))
    if scenario
        return MarkupCfg(Dict{String,Float64}(), Float64(get(m, "scenario_tax", 0.0)), fuels,
                         Dict{Tuple{String,Int},Float64}(),
                         Float64.(tb.rsi), Float64.(tb.L_gas), Float64(get(m, "L_coal", 0.0)),
                         Float64(get(m, "cap", 0.5)), src, share, scale, offs)
    end
    rsi = Dict{Tuple{String,Int},Float64}()
    if src == "file"
        rs = CSV.read(joinpath(root, m["rsi_file"]), DataFrame)
        rsi = Dict((string(r.date), Int(r.hour)) => Float64(r.rsi) for r in eachrow(rs))
    end
    MarkupCfg(Dict(String(k) => Float64(v) for (k, v) in get(m, "tax", Dict())),
              Float64(get(m, "tax_default", 0.07)), fuels, rsi,
              Float64.(tb.rsi), Float64.(tb.L_gas), Float64(get(m, "L_coal", 0.0)),
              Float64(get(m, "cap", 0.5)), src, share, scale, offs)
end

"""
    offered_mw(net) -> MW

What the market stage can offer in one hour: the sum of the units' pmax in the
copper-plate network (thermal after availability, solar/wind available that
hour, hydro and pumped-storage turbines, CHP blocks, batteries), without the
fixed cross-border injections (OMIE's offered capacity has no French imports
either) and the SLACK backstop (9 999 pu).  Island units held at 0 MW in the market count 0.
"""
offered_mw(net) = sum(max(Float64(g["pmax"]), 0.0) * BASEMVA for g in values(net.gens)
                      if !(get(g, "fuel", "") in ("CrossBorder", "Slack")); init = 0.0)

"""
    model_rsi(mk, cap_mw, load_mw) -> RSI

RSI computed by the model ([costs.markup] rsi_source / scenario_rsi_source =
"model"), with no owner data: in 2024 the largest firm (Iberdrola, 99 % of
hours) held a near-constant share of OMIE's offered capacity (mean 0.214,
5-95 % 0.183-0.250, Data/markup/omie_hourly_2024.csv), and an RSI with that
share fixed tracks OMIE's own (correlation 0.98, mean |ΔL_gas| 0.007):

    RSI = rsi_offset + rsi_scale * (1 - largest_share) * offered MW / load MW

rsi_offset and rsi_scale map the model's ratio onto OMIE's on 2024 days (least
squares).  OMIE's curves hold only the auction (bilateral contracts sit
outside both offered and matched MW, Spain + Portugal) and its hydro offers are
energy-limited, so the model's ratio runs higher; the slope stays near 1.
"""
model_rsi(mk::MarkupCfg, cap_mw, load_mw) =
    load_mw > 0 ? mk.rsi_offset + mk.rsi_scale * (1 - mk.largest_share) * cap_mw / load_mw : NaN

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
function markup_for(mk::MarkupCfg, date_str, hour::Int; rsi = NaN)
    tax = markup_tax(mk, Date(String(date_str)))
    r = mk.rsi_source == "file" ? get(mk.rsi, (String(date_str), hour), NaN) :
        mk.rsi_source == "model" ? Float64(rsi) : NaN
    lim(v) = clamp(v, 0.0, mk.cap)
    isnan(r) && return (tax, r, 0.0, lim(mk.l_coal))
    return (tax, r, lim(markup_interp(mk.x, mk.l_gas, r)), lim(mk.l_coal))
end

"Scale the generators' linear costs of one day's hourly networks in place; returns one log row per hour."
function apply_markup!(nets, mk::MarkupCfg, date_str, day_ts)
    rows = NamedTuple[]
    for (net, ts) in zip(nets, eachrow(day_ts))
        # offered MW and load of this hour, before any cost changes (pmax only)
        cap  = offered_mw(net)
        load = hasproperty(ts, :load_mw) ? Float64(ts.load_mw) : NaN
        tax, r, lg, lc = markup_for(mk, date_str, Int(ts.hour); rsi = model_rsi(mk, cap, load))
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
        push!(rows, (date = String(date_str), hour = Int(ts.hour), rsi = r, tax = tax, L_gas = lg, L_coal = lc,
                     offered_mw = cap, load_mw = load))
    end
    return rows
end
