# Write the config for a redispatch-realism run on top of an existing run's
# market results (standalone redispatch, [redispatch] from_saved = "BAL").
#
#     julia redispatch_realism/make_config.jl <out.toml> [--source <config of the source run>]
#                                             [--n1 on] [--bids <bids.toml>] [--no-realism]
#
# The redispatch has to run with the market-side settings of the run whose
# schedules it reads (e.g. a GAS=on run frees coal and takes the islands out),
# so the source run's config (its config_redispatch.toml or config_used.toml) is
# laid over this branch's config.toml — the branch supplies the new keys the
# source config predates — and then the redispatch-realism switches are set:
#   RD2 loss_share 0.0101 · RD3 q_requires_online · RD4 renewable_power_factor 0.98
#   (RD 413/2014 art. 7 e) and Annex III: 0.98 inductive to 0.98 capacitive; was 1.0 until 22 Oct)
#   RD9 startups · RD5 mustrun · RD7 reserve · RD8 phase1 · RD10/11 objective "ree"
#   with the fitted bids (CCGT 0.89, coal 0.94, storage 0.59 up mark-up), tie-break 5
#   generator-bus voltage band 0.975–1.05 pu, and REE's band per voltage level at generator
#   buses (P.O. 1.4: 400 kV 0.975–1.05, 220 kV 0.932–1.114)
# --n1 on adds RD6 (preventive N-1 in phase I) with P.O. 1.1's rules: one circuit or
# transformer per outage (n1_outage = "element") and seasonal post-outage limits
# (RD6b).  --in-chain runs phase I inside the market chain (needs the markets, so
# from_saved = "").  Written with TOML.print: comments are not kept.
using TOML

const REPO = normpath(joinpath(@__DIR__, ".."))

"Lay `src` over `base` (recursively for tables; other values, arrays included, replaced)."
function overlay!(base::AbstractDict, src::AbstractDict)
    for (k, v) in src
        if v isa AbstractDict && get(base, k, nothing) isa AbstractDict
            overlay!(base[k], v)
        else
            base[k] = v
        end
    end
    return base
end

function set!(cfg, path::String, value)
    keys = split(path, ".")
    t = cfg
    for k in keys[1:end-1]
        t = get!(t, String(k), Dict{String,Any}())
    end
    t[String(keys[end])] = value
end

const BIDS = [Dict("type" => "Gas:Combined_cycle", "up_markup" => 0.89),
              Dict("type" => "Gas:Gas_turbine", "up_markup" => 0.89),
              Dict("type" => "Coal", "up_markup" => 0.94),
              Dict("type" => "Hydro:pumped_storage", "up_markup" => 0.59),
              Dict("type" => "Hydro:reservoir", "up_markup" => 0.59)]

function main(args)
    isempty(args) && (println(read(@__FILE__, String)[1:1200]); return)
    out = args[1]
    opt(name) = (i = findfirst(==(name), args); i === nothing ? nothing : args[i + 1])
    cfg = TOML.parsefile(joinpath(REPO, "config.toml"))
    src = opt("--source")
    src === nothing || overlay!(cfg, TOML.parsefile(src))
    set!(cfg, "redispatch.enabled", true)
    set!(cfg, "redispatch.from_saved", "BAL")
    set!(cfg, "redispatch.only", "")
    if !("--no-realism" in args)
        set!(cfg, "redispatch.loss_share", 0.0101)
        set!(cfg, "redispatch.q_requires_online", true)
        set!(cfg, "redispatch.objective", "ree")
        set!(cfg, "redispatch.power_flow", "AC")
        set!(cfg, "redispatch.water_value", "constant")
        set!(cfg, "generators.renewable_power_factor", 0.98)
        set!(cfg, "network.gen_bus_vmin", 0.975)
        set!(cfg, "network.gen_bus_vmax", 1.05)
        set!(cfg, "network.voltage_limits_by_kv", Dict("400" => [0.975, 1.05], "220" => [0.932, 1.114]))
        set!(cfg, "network.voltage_limits_scope", "generator")
        for t in ("startups", "mustrun", "reserve", "phase1")
            set!(cfg, "redispatch.$t.enabled", true)
        end
        set!(cfg, "redispatch.startups.candidate_min_mw", 100.0)
        set!(cfg, "redispatch.bids.tie_break_eur_mwh", 5.0)
        set!(cfg, "redispatch.bids.by_type", BIDS)
        set!(cfg, "redispatch.phase1.n1", opt("--n1") == "on")
        if opt("--n1") == "on"
            set!(cfg, "redispatch.phase1.n1_outage", "element")
            set!(cfg, "redispatch.phase1.n1_seasonal_ratings", true)
        end
        if "--in-chain" in args
            set!(cfg, "redispatch.phase1.in_chain", true)
            set!(cfg, "redispatch.from_saved", "")
        end
    end
    b = opt("--bids")
    b === nothing || overlay!(cfg, TOML.parsefile(b))
    mkpath(dirname(abspath(out)))
    open(out, "w") do io
        println(io, "# Written by redispatch_realism/make_config.jl from config.toml",
                src === nothing ? "" : " + $src", "; comments are not kept.")
        TOML.print(io, cfg; sorted = true)
    end
    println("wrote $out")
end

main(ARGS)
