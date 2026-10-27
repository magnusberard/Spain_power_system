# Write a copy of config.toml for one stage of a split run.
#
# A split run (scripts/run_markets_sequential.sh, scripts/run_redispatch_only.sh)
# first clears the market stages for the whole period in order, then runs the
# network redispatch for each chunk on its own. Both need a config copy that
# differs from config.toml in a few switches only; this script writes it, editing
# the text in place (comments and layout are kept). Julia, not Python, so it runs
# wherever the model runs (Solstorm's compute nodes have no python3 without a module).
#
#     julia scripts/make_run_config.jl <out.toml> --stage markets|redispatch
#                                      [--gas on|off] [--res-input accepted|offered]
#
#   --stage markets      [redispatch] enabled = false
#   --stage redispatch   [redispatch] enabled = true, from_saved = "BAL"
#   --gas on             the gas/coal switches, all off in config.toml:
#                        [costs.gas_unit_efficiency] enabled, [unit_commitment]
#                        enabled, [costs.coal_srmc] enabled, [fleet] enabled and
#                        [islands] exclude_from_market and remove_isolated (Ceuta)
#                        (the coal fleet without its
#                        availability factor needs the island plants out of the
#                        market and the closed plants removed), and [redispatch]
#                        frozen_fuels = ["Nuclear", "Biomass"] (coal redispatchable)
#   --markup on          [costs.markup] enabled (generation tax + RSI mark-ups)
#   --hydro LABEL        [bellman] volume/turbine/bellman files from Magnus's
#                        hydro_state variant LABEL (e.g. aligned_rc_observed):
#                        Data/hydro_state/{Volume,TurbineSchedule,BellmanValuesOUT}_LABEL.csv
#                        (branch hydro-state, hydro_state/midterm_observed.jl)
#   --res-input X        [run] res_input = "X"
#   --participation P    [participation] (§23): active = 1.0 everywhere (as in
#                        config.toml), measured = CID shares measured from REE
#                        e·sios (load 0.07, wind 0.07, solar 0.06; IDA2/IDA3 1.0),
#                        passive = 0.0 in ID2, ID3 and CID
#   --balancing B        [balancing].eligible: all (as in config.toml) or
#                        qualified = the units REE qualifies for balancing
#                        (P.O. 3.2 §6.2): CCGT, gas turbines, coal, reservoir hydro,
#                        pumped storage, batteries
#
# Scenario configs ([scenario].label other than "2024", e.g. the 2035 runs) set
# their own switches in config.toml, so --gas, --markup and --hydro (2024 options:
# 2024 closed plants and coal price, 2024 hydro state) stop the script there.

const REPO = normpath(joinpath(@__DIR__, ".."))

# [participation] per --participation: (stage, value) lines to set
const PARTICIPATION = Dict(
    "active"   => [],
    "measured" => [("cid", "{ load = 0.07, wind = 0.07, solar = 0.06 }")],
    "passive"  => [(st, "{ load = 0.0, wind = 0.0, solar = 0.0 }") for st in ("id2", "id3", "cid")])
const BAL_QUALIFIED = "[\"Gas:Combined_cycle\", \"Gas:Gas_turbine\", \"Coal\", \"Hydro:reservoir\", \"Hydro:pumped_storage\", \"Battery\"]"

const GAS_ON = [("costs.gas_unit_efficiency", "enabled", "true"),
                ("unit_commitment", "enabled", "true"),
                ("costs.coal_srmc", "enabled", "true"),
                ("fleet", "enabled", "true"),
                ("islands", "exclude_from_market", "true"),
                ("islands", "remove_isolated", "true"),           # Ceuta (G0116), not connected in 2024
                # coal now has its own on/off and runs at full size: the redispatch
                # must be able to move it (REE redispatches coal for grid limits,
                # e.g. Asturian coal at night); only nuclear and biomass stay frozen
                ("redispatch", "frozen_fuels", "[\"Nuclear\", \"Biomass\"]")]

"Set `key = value` in [section] (the first such line before the next header)."
function set_key(lines, section, key, value)
    inside = false
    for (i, line) in enumerate(lines)
        m = match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", line)
        if m !== nothing
            inside = strip(m.captures[1]) == section
            continue
        end
        inside || continue
        k = match(Regex("^(\\s*" * key * "\\s*=\\s*)([^#]*?)(\\s*#.*)?\$"), line)
        if k !== nothing
            lines[i] = k.captures[1] * value * something(k.captures[3], "")
            return
        end
    end
    error("config.toml: no '$key' in [$section]")
end

"The value text of `key` in [section] (comment removed), or nothing."
function get_key(lines, section, key)
    inside = false
    for line in lines
        m = match(r"^\s*\[([^\[\]]+)\]\s*(#.*)?$", line)
        if m !== nothing
            inside = strip(m.captures[1]) == section
            continue
        end
        inside || continue
        k = match(Regex("^\\s*" * key * "\\s*=\\s*(\"[^\"]*\"|[^#\\s]+)"), line)
        k === nothing || return k.captures[1]
    end
    return nothing
end

function main(args)
    usage = "julia scripts/make_run_config.jl <out.toml> --stage markets|redispatch [--gas on|off] [--markup on|off] [--hydro LABEL] [--res-input accepted|offered] [--participation active|measured|passive] [--balancing all|qualified] [--config file]"
    isempty(args) && error(usage)
    out = args[1]
    opt = Dict("--gas" => "off", "--markup" => "off", "--participation" => "active", "--balancing" => "all",
               "--config" => joinpath(REPO, "config.toml"))
    i = 2
    while i <= length(args)
        args[i] in ("--stage", "--gas", "--markup", "--hydro", "--res-input", "--participation", "--balancing", "--config") &&
            i < length(args) || error(usage)
        opt[args[i]] = args[i+1]
        i += 2
    end
    stage = get(opt, "--stage", "")
    stage in ("markets", "redispatch") || error(usage)
    opt["--gas"] in ("on", "off") || error(usage)
    opt["--markup"] in ("on", "off") || error(usage)
    res = get(opt, "--res-input", "")
    res in ("", "accepted", "offered") || error(usage)
    haskey(PARTICIPATION, opt["--participation"]) || error(usage)
    opt["--balancing"] in ("all", "qualified") || error(usage)

    raw = read(opt["--config"], String)
    crlf = occursin("\r\n", raw)
    lines = split(replace(raw, "\r\n" => "\n"), "\n"; keepempty = true) .|> String
    label = strip(something(get_key(lines, "scenario", "label"), "2024"), '"')
    if label != "2024"
        used = [o for (o, set) in (("GAS=on", opt["--gas"] == "on"), ("MARKUP=on", opt["--markup"] == "on"),
                                   ("HYDRO", get(opt, "--hydro", "") != "")) if set]
        isempty(used) || error("[scenario] label = \"$label\": $(join(used, ", ")) only for 2024 runs; " *
                               "this config sets its own switches. Start again without them.")
    end
    if stage == "markets"
        set_key(lines, "redispatch", "enabled", "false")
    else
        set_key(lines, "redispatch", "enabled", "true")
        set_key(lines, "redispatch", "from_saved", "\"BAL\"")
    end
    opt["--gas"] == "on" && for (sec, key, val) in GAS_ON
        set_key(lines, sec, key, val)
    end
    opt["--markup"] == "on" && set_key(lines, "costs.markup", "enabled", "true")
    hyd = get(opt, "--hydro", "")
    if hyd != ""
        for (key, f) in (("volume_file", "Volume"), ("turbine_file", "TurbineSchedule"), ("bellman_file", "BellmanValuesOUT"))
            path = "Data/hydro_state/$(f)_$(hyd).csv"
            isfile(joinpath(REPO, path)) || error("$path not found (copy it from the hydro-state checkout)")
            set_key(lines, "bellman", key, "\"$path\"")
        end
    end
    res == "" || set_key(lines, "run", "res_input", "\"$res\"")
    for (st, val) in PARTICIPATION[opt["--participation"]]
        set_key(lines, "participation", st, val)
    end
    opt["--balancing"] == "qualified" && set_key(lines, "balancing", "eligible", BAL_QUALIFIED)
    text = join(lines, "\n")
    crlf && (text = replace(text, "\n" => "\r\n"))
    mkpath(dirname(abspath(out)))
    tmp = out * ".tmp"
    write(tmp, text)
    mv(tmp, out; force = true)
    println("wrote $out (stage $stage, gas $(opt["--gas"]), markup $(opt["--markup"])$(hyd == "" ? "" : ", hydro " * hyd)$(res == "" ? "" : ", res_input " * res), participation $(opt["--participation"]), balancing $(opt["--balancing"]))")
end

main(ARGS)
