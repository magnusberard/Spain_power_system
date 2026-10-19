# ============================================================
# Hydro state from observation: mid-term SDDP re-simulated on the observed 2024
# reservoir level and inflows (W2–W4 in hydro_state/README.md)
#
# Why: the baseline mid-term model starts 2024 at 30 % of the ES reservoir and
# replays one climate year (1982), so it saves water through the spring and
# releases it in winter — the opposite of 2024 (REE: 51 % full at the end of
# December 2023, 76 % in May). The market chain takes its daily hydro budget and
# its starting volume from that path, so the error lands in the price.
#
# What this does, with midterm_sddp4.jl itself unchanged:
#   1. includes midterm_sddp4.jl under a config copy that redirects every output
#      to results/hydro_state/, so nothing tracked is overwritten. It trains the
#      baseline policy (or reloads results/midterm4_cuts.json with "export");
#   2. W3: trains further from a spread of ES starting levels, so the cuts are
#      accurate at the fills the observed path reaches;
#   3. W2 + W4: simulates the trained policy from REE's observed start level,
#      with the observed inflow of each week ([observed].inflow);
#   4. writes cuts / volume / turbine / exchange schedules in the formats the
#      market chain reads, plus hydro_state/config_<label>.toml pointing
#      [bellman] at them, and a weekly diagnostic CSV.
#
# The policy never sees future inflows: it was trained on the climate-year
# scenarios only, and within the simulation each week's inflow is revealed when
# that week is decided — the same information structure as the baseline. Nothing
# here reads real hydro generation or prices.
#
# Run:  julia --project=. hydro_state/midterm_observed.jl            (train + export)
#       julia --project=. hydro_state/midterm_observed.jl reuse      (reload the cuts
#            of a previous run of this script, skip all training)
# Env:  SPAIN_CONFIG       base config (default config.toml)
#       HYDRO_STATE_CONFIG settings (default hydro_state/hydro_state.toml)
# ============================================================

using TOML, Dates

const HS_ROOT = normpath(joinpath(@__DIR__, ".."))
const HS_SETTINGS_PATH = get(ENV, "HYDRO_STATE_CONFIG", joinpath(@__DIR__, "hydro_state.toml"))
const HS = TOML.parsefile(HS_SETTINGS_PATH)
const HS_LABEL = String(HS["label"])
# Variants that differ only in the simulation (start level, inflow) share one trained policy:
# train_label names it (default: label). Variants with a different system must not share it.
const HS_TRAIN_LABEL = String(get(HS, "train_label", HS_LABEL))
const HS_REUSE = "reuse" in ARGS
const HS_RESULTS = joinpath(HS_ROOT, "results", "hydro_state")
const HS_DATA = joinpath(HS_ROOT, "Data", "hydro_state")
const HS_CUTS_JSON = joinpath(HS_RESULTS, "cuts_$(HS_TRAIN_LABEL).json")        # after W3
const HS_TRAIN_JSON = joinpath(HS_RESULTS, "train_$(HS_TRAIN_LABEL).json")      # before W3
mkpath(HS_RESULTS); mkpath(HS_DATA)
# Trained policies committed to the repo (Data/hydro_state/policies/, for the variants worth
# keeping) seed results/hydro_state on a fresh clone, so `reuse` works without retraining.
for (src, dst) in ((joinpath(HS_DATA, "policies", "train_$(HS_TRAIN_LABEL).json"), HS_TRAIN_JSON),
                   (joinpath(HS_DATA, "policies", "cuts_$(HS_TRAIN_LABEL).json"), HS_CUTS_JSON))
    if !isfile(dst) && isfile(src)
        cp(src, dst)
        println("hydro_state: seeded $(basename(dst)) from Data/hydro_state/policies/")
    end
end

# ── 1. base config copy: same system, outputs redirected to results/hydro_state ──
const HS_BASE_CONFIG = get(ENV, "SPAIN_CONFIG", joinpath(HS_ROOT, "config.toml"))
hs_cfg = TOML.parsefile(HS_BASE_CONFIG)
get(get(hs_cfg, "scenario", Dict()), "label", "2024") == "2024" ||
    error("hydro_state is for the 2024 path only ([scenario].label = \"2024\")")
for (k, f) in (("cuts_out", "baseline_BellmanValuesOUT.csv"), ("volume_out", "baseline_Volume.csv"),
               ("turbine_out", "baseline_TurbineSchedule.csv"), ("exchange_out", "baseline_ExchangeSchedule.csv"))
    hs_cfg["midterm4"][k] = "results/hydro_state/$(HS_TRAIN_LABEL)_$f"
end
# [system].es_stage_supply_file: the SDDP's Spain gets the weekly supply the market chain uses
# (midterm_sddp4.jl hook, off by default). This changes the system, so it needs its own training.
const HS_STAGE_FILE = String(get(get(HS, "system", Dict()), "es_stage_supply_file", ""))
HS_STAGE_FILE == "" || (hs_cfg["midterm4"]["es_stage_supply_file"] = HS_STAGE_FILE)
# [system].es_rule_curve_file: seasonal envelope on the ES reservoir (midterm_sddp4.jl hook,
# off by default); also a different system, so it needs its own training.
const HS_RULE_FILE = String(get(get(HS, "system", Dict()), "es_rule_curve_file", ""))
HS_RULE_FILE == "" || (hs_cfg["midterm4"]["es_rule_curve_file"] = HS_RULE_FILE)
# [system].es_inflow_source / es_inflow_ree_file: the ES inflow dataset the SDDP trains on
# ("edf_ree" = EDF climate years with REE's 2014–2023 monthly shape); also a different system.
for k in ("es_inflow_source", "es_inflow_ree_file")
    haskey(get(HS, "system", Dict()), k) && (hs_cfg["midterm4"][k] = String(HS["system"][k]))
end
haskey(get(HS, "system", Dict()), "es_rule_curve_penalty") &&
    (hs_cfg["midterm4"]["es_rule_curve_penalty"] = Float64(HS["system"]["es_rule_curve_penalty"]))
const HS_TMP_CONFIG = joinpath(HS_RESULTS, "midterm_config_$(HS_LABEL).toml")
open(io -> TOML.print(io, hs_cfg), HS_TMP_CONFIG, "w")
ENV["SPAIN_CONFIG"] = HS_TMP_CONFIG

# midterm_sddp4.jl trains unless ARGS has "export", and both read/write the one shared file
# results/midterm4_cuts.json. Cuts trained on one system are not valid for another, so this
# variant's own copy (train_<train_label>.json) is swapped into that slot for the run and the
# slot's previous content is put back afterwards.
const HS_SLOT = joinpath(HS_ROOT, "results", "midterm4_cuts.json")
const HS_SLOT_BACKUP = joinpath(HS_RESULTS, "slot_backup_$(getpid()).json")
isfile(HS_SLOT) && cp(HS_SLOT, HS_SLOT_BACKUP; force = true)
empty!(ARGS)
if isfile(HS_TRAIN_JSON)
    cp(HS_TRAIN_JSON, HS_SLOT; force = true)
    push!(ARGS, "export")
else
    HS_REUSE && error("reuse: $HS_TRAIN_JSON not found — run without reuse first")
    rm(HS_SLOT; force = true)
end
println("hydro_state: including midterm_sddp4.jl ($(isempty(ARGS) ? "train" : "export"), policy '$HS_TRAIN_LABEL')")
try
    include(joinpath(HS_ROOT, "midterm_sddp4.jl"))
    isfile(HS_TRAIN_JSON) || cp(HS_SLOT, HS_TRAIN_JSON)
finally
    if isfile(HS_SLOT_BACKUP)
        mv(HS_SLOT_BACKUP, HS_SLOT; force = true)
    else
        rm(HS_SLOT; force = true)
    end
end
include(joinpath(HS_ROOT, "bellman.jl"))

const HS_VMAX_ES = reservoirs["ES"].vmax
const HS_STATE_ES = Symbol("vres[ES]")

# ── 2. W3: more cuts, trained from a spread of ES starting levels ──────────────
# Cuts from any starting level are valid for the same model: the terminal target
# (END_FILL × the dataset's v0) is fixed when the model is built, so changing the
# root state only changes which states the forward passes visit.
if HS_REUSE || isfile(HS_CUTS_JSON)
    isfile(HS_CUTS_JSON) || error("reuse: $HS_CUTS_JSON not found — run without reuse first")
    SDDP.read_cuts_from_file(model, HS_CUTS_JSON)
    println("hydro_state: reloaded $HS_CUTS_JSON (policy '$HS_TRAIN_LABEL'), training skipped")
else
    fills = Float64.(HS["training"]["es_start_fills"])
    iters = Int(HS["training"]["iterations_per_start"])
    root0 = copy(model.initial_root_state)
    for f in fills
        model.initial_root_state[HS_STATE_ES] = f * HS_VMAX_ES
        @printf "hydro_state W3: %d iterations from ES fill %.0f %%\n" iters 100f
        SDDP.train(model; iteration_limit = iters, add_to_existing_cuts = true,
                   print_level = 0, log_file = joinpath(HS_RESULTS, "sddp_$(HS_LABEL).log"))
    end
    merge!(model.initial_root_state, root0)
    @printf "hydro_state W3: lower bound after extra training %.4e EUR\n" SDDP.calculate_bound(model)
    SDDP.write_cuts_to_file(model, HS_CUTS_JSON)
end

# ── 3. observed state and inflow (W2, W4) ──────────────────────────────────────
ree = CSV.read(joinpath(HS_ROOT, HS["observed"]["ree_file"]), DataFrame; types = Dict(:month => String))
ree_fill  = Dict(r.month => r.fill_total for r in eachrow(ree))
ree_index = Dict(r.month => r.producible_index for r in eachrow(ree))
ym(d::Date) = Dates.format(d, "yyyy-mm")

v0_es = if HS["observed"]["observed_start"]
    # REE's monthly reserve is taken as the level at the end of that month, so the
    # start uses the month before bgn_date; start_fill_month overrides it (sensitivity).
    m = String(get(HS["observed"], "start_fill_month", ym(BGN_DATE - Day(1))))
    haskey(ree_fill, m) || error("no REE reserve for $m in $(HS["observed"]["ree_file"])")
    @printf "hydro_state W2: ES start = REE fill %.1f %% at end of %s → %.2f TWh (dataset: %.2f)\n" 100ree_fill[m] m ree_fill[m]*HS_VMAX_ES/1e6 reservoirs["ES"].v0/1e6
    ree_fill[m] * HS_VMAX_ES
else
    reservoirs["ES"].v0
end

w_sim = findfirst(==(SIM_YEAR), YEARS)
inflow_mode = String(HS["observed"]["inflow"])
inflow_mode in ("index", "climate_year") || error("[observed].inflow must be \"index\" or \"climate_year\"")
if inflow_mode == "index"
    # Climatological ES inflow per week and block (mean over the training
    # scenarios), scaled by that month's REE producible index. Months outside
    # the REE file (2025, the end of the horizon) keep the climatology (index 1).
    clim = dropdims(mean(INF[:, :, 1, :]; dims = 2); dims = 2)
    week_index = [get(ree_index, ym(BGN_DATE + Day(7 * (t - 1) + 3)), missing) for t in 1:N_STAGES]
    for t in 1:N_STAGES
        INF[t, w_sim, 1, :] .= clim[t, :] .* coalesce(week_index[t], 1.0)
    end
    n_obs = count(!ismissing, week_index)
    @printf "hydro_state W4: ES inflow = climatology × REE producible index on %d of %d weeks\n" n_obs N_STAGES
end

inc = Dict("vres[$r]" => (r == "ES" ? v0_es : reservoirs[r].v0) for r in RZ)
sims_obs = SDDP.simulate(model, 1, Symbol[];
    sampling_scheme = SDDP.Historical([(t, w_sim) for t in 1:N_STAGES]),
    custom_recorders = recorders, incoming_state = inc)

# ── 4. export (same formats as midterm_sddp4.jl's exporter) ────────────────────
out_path(stem) = joinpath(HS_DATA, "$(stem)_$(HS_LABEL).csv")
rel(p) = replace(relpath(p, HS_ROOT), '\\' => '/')

# Cuts: a_0 = FR slope, a_1 = ES slope, the EU term folded into b along THIS
# simulation's EU path (as the baseline exporter does along its own).
veu = [sims_obs[1][t][:veu][NB + 1] for t in 1:N_STAGES]
SDDP.write_cuts_to_file(model, HS_CUTS_JSON)
raw_obs = Dict{Int,Vector{Any}}(parse(Int, nd["node"]) => nd["single_cuts"]
                                for nd in JSON.parsefile(HS_CUTS_JSON))
cuts_df = DataFrame(Timestep = Int[], a_0 = Float64[], a_1 = Float64[], b = Float64[])
for (t, cs) in raw_obs
    t == N_STAGES && continue
    for c in cs
        push!(cuts_df, (t - 1, c["coefficients"][key("FR")], c["coefficients"][key("ES")],
                        bfun(c) + c["coefficients"][key("EU")] * veu[t]))
    end
end
push!(cuts_df, (N_STAGES - 1, 0.0, 0.0, 0.0))
sort!(cuts_df, :Timestep)
CSV.write(out_path("BellmanValuesOUT"), cuts_df)

nH = N_STAGES * 168
vol_df = DataFrame(Timestep = 0:nH)
for c in ("Hydro|Reservoir_FR_0", "Hydro|Reservoir_ES_0", "Hydro|Pumped Storage_ES_0",
          "Hydro|Pumped Storage_FR_0", "Battery|Lithium-Ion_FR_0", "Battery|Lithium-Ion_PT_0")
    vol_df[!, c] = zeros(nH + 1)
end
tur_df = DataFrame(Timestep = 0:nH, Turbine_ES_MW = zeros(nH + 1),
                   Turbine_FR_MW = zeros(nH + 1), Turbine_EU_MW = zeros(nH + 1))
xch_df = DataFrame(Timestep = 0:nH, Import_FR_MW = zeros(nH + 1), Import_PT_MW = zeros(nH + 1))
for (t, st) in enumerate(sims_obs[1]), b in 1:NB, j in 0:BLOCK_HOURS-1
    h = (t - 1) * 168 + (b - 1) * BLOCK_HOURS + j
    for (col, k) in (("Hydro|Reservoir_FR_0", :vfr), ("Hydro|Reservoir_ES_0", :ves))
        v = st[k]; vol_df[h + 1, col] = v[b] + (v[b+1] - v[b]) * j / BLOCK_HOURS
    end
    for (col, k) in (("Turbine_ES_MW", :turbes), ("Turbine_FR_MW", :turbfr), ("Turbine_EU_MW", :turbeu))
        tur_df[h + 1, col] = st[k][b]
    end
    xch_df[h + 1, :Import_FR_MW] = st[:impfr][b]
    xch_df[h + 1, :Import_PT_MW] = st[:imppt][b]
end
let st = sims_obs[1][N_STAGES]
    vol_df[nH + 1, "Hydro|Reservoir_FR_0"] = st[:vfr][NB + 1]
    vol_df[nH + 1, "Hydro|Reservoir_ES_0"] = st[:ves][NB + 1]
    for (col, k) in (("Turbine_ES_MW", :turbes), ("Turbine_FR_MW", :turbfr), ("Turbine_EU_MW", :turbeu))
        tur_df[nH + 1, col] = st[k][NB]
    end
    xch_df[nH + 1, :Import_FR_MW] = st[:impfr][NB]
    xch_df[nH + 1, :Import_PT_MW] = st[:imppt][NB]
end
CSV.write(out_path("Volume"), vol_df)
CSV.write(out_path("TurbineSchedule"), tur_df)
CSV.write(out_path("ExchangeSchedule"), xch_df)

# Weekly diagnostic: the path to compare with REE, and the water value on it
# (binding cut of the week's stage at the start-of-week volume, FR term folded
# in as bellman.jl's load_cuts_at_stage does).
cuts_by_stage = Dict{Int,Vector{BellmanCut}}()
for r in eachrow(cuts_df)
    push!(get!(cuts_by_stage, r.Timestep, BellmanCut[]), BellmanCut(r.a_0, r.a_1, r.b))
end
diag = DataFrame(week = Int[], start = Date[], v_es_twh = Float64[], fill = Float64[],
                 inflow_gwh = Float64[], turbine_gwh = Float64[], spill_gwh = Float64[],
                 water_value = Float64[])
for (t, st) in enumerate(sims_obs[1])
    v_start = st[:ves][1]
    v_fr = st[:vfr][1]
    cs = [BellmanCut(c.a0, c.a1, c.b + c.a0 * v_fr) for c in get(cuts_by_stage, t - 1, BellmanCut[])]
    wv = isempty(cs) ? NaN : binding_water_value(cs, v_start)
    infl = sum(INF[t, w_sim, 1, :]) / 1e3
    turb = sum(st[:turbes]) * BLOCK_HOURS / 1e3
    push!(diag, (t, BGN_DATE + Day(7 * (t - 1)), v_start / 1e6, v_start / HS_VMAX_ES,
                 infl, turb, infl - turb - (st[:ves][NB + 1] - v_start) / 1e3, wv))
end
CSV.write(joinpath(HS_RESULTS, "weekly_$(HS_LABEL).csv"), diag)

# Market-chain config copy reading the new hydro files (same base config otherwise).
chain_cfg = TOML.parsefile(HS_BASE_CONFIG)
chain_cfg["bellman"]["bellman_file"] = rel(out_path("BellmanValuesOUT"))
chain_cfg["bellman"]["volume_file"]  = rel(out_path("Volume"))
chain_cfg["bellman"]["turbine_file"] = rel(out_path("TurbineSchedule"))
const HS_CHAIN_CONFIG = joinpath(@__DIR__, "config_$(HS_LABEL).toml")
open(io -> TOML.print(io, chain_cfg), HS_CHAIN_CONFIG, "w")

println("\nhydro_state: wrote")
for p in (out_path("BellmanValuesOUT"), out_path("Volume"), out_path("TurbineSchedule"),
          out_path("ExchangeSchedule"), joinpath(HS_RESULTS, "weekly_$(HS_LABEL).csv"), HS_CHAIN_CONFIG)
    println("  ", rel(p))
end
println("Run the market chain on it with SPAIN_CONFIG=$(rel(HS_CHAIN_CONFIG))")
