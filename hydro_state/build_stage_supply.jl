# Weekly Spanish must-run / availability inputs for the mid-term SDDP, from the SAME per-day
# tables the market chain already uses ([da.nuclear_availability_by_date],
# [da.coal_availability_by_date], [chp.by_date]).
#
# Why: the SDDP prices water against its own Spain. It runs nuclear at full 7.4 GW and the
# CHP / waste / mini-hydro group as a flat 2,600 / 700 / 400 MW (the [chp] annual defaults),
# while the market chain has used observed daily values since October 2026. The SDDP's Spain then
# carries ~21 TWh more cheap supply than REE's 2024 and almost no gas (5.7 vs 32.1 TWh), so its
# prices — and water values — are too low (hydro_state/diagnose_sddp.py). This file makes the
# long-term model see the supply the short-term model sees. Nothing here is fitted to prices.
#
#   julia --project=. hydro_state/build_stage_supply.jl
#
# Writes Data/hydro_state/es_stage_supply_2024.csv: one row per SDDP stage (weekly from
# [bellman].bgn_date, [midterm4].n_stages rows) with the weekly mean of
#   nuclear_avail, coal_avail, chp_gas_mw, chp_waste_mw, chp_minihydro_mw, n_days
# Stages after the last dated day (2025, the end of the horizon) repeat the same calendar week
# of 2024 (n_days = 0 marks them).
using TOML, Dates, Statistics, CSV, DataFrames

root = normpath(joinpath(@__DIR__, ".."))
cfg = TOML.parsefile(get(ENV, "SPAIN_CONFIG", joinpath(root, "config.toml")))
bgn = Date(cfg["bellman"]["bgn_date"])
nst = Int(cfg["midterm4"]["n_stages"])
nuc = cfg["da"]["nuclear_availability_by_date"]
coal = cfg["da"]["coal_availability_by_date"]
chp = cfg["chp"]["by_date"]

function week_mean(t)
    days = [string(bgn + Day(7 * (t - 1) + k)) for k in 0:6]
    have = filter(d -> haskey(nuc, d) && haskey(coal, d) && haskey(chp, d), days)
    isempty(have) && return nothing
    (nuclear_avail = mean(Float64(nuc[d]) for d in have),
     coal_avail = mean(Float64(coal[d]) for d in have),
     chp_gas_mw = mean(Float64(chp[d]["gas_mw"]) for d in have),
     chp_waste_mw = mean(Float64(chp[d]["waste_mw"]) for d in have),
     chp_minihydro_mw = mean(Float64(chp[d]["minihydro_mw"]) for d in have),
     n_days = length(have))
end

rows = Any[week_mean(t) for t in 1:nst]
n_dated = count(!isnothing, rows)
for t in 1:nst
    rows[t] === nothing || continue
    src = mod1(t, 52)                       # same calendar week of 2024
    rows[src] === nothing && error("stage $t: no dated week $src to repeat")
    rows[t] = merge(rows[src], (n_days = 0,))
end
df = DataFrame(rows)
insertcols!(df, 1, :stage => 1:nst, :week_start => [bgn + Day(7 * (t - 1)) for t in 1:nst])
out = joinpath(root, "Data", "hydro_state", "es_stage_supply_2024.csv")
mkpath(dirname(out))
CSV.write(out, df)
println("Wrote $(nrow(df)) stages ($n_dated from dated days) -> ", relpath(out, root))
println("2024 means: nuclear ", round(mean(df.nuclear_avail[1:52]); digits = 3),
        ", CHP gas ", round(mean(df.chp_gas_mw[1:52])), " MW, waste ",
        round(mean(df.chp_waste_mw[1:52])), " MW, mini-hydro ", round(mean(df.chp_minihydro_mw[1:52])), " MW")
