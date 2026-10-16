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
#                        [islands] exclude_from_market (the coal fleet without its
#                        availability factor needs the island plants out of the
#                        market and the closed plants removed)
#   --res-input X        [run] res_input = "X"

const REPO = normpath(joinpath(@__DIR__, ".."))

const GAS_ON = [("costs.gas_unit_efficiency", "enabled", "true"),
                ("unit_commitment", "enabled", "true"),
                ("costs.coal_srmc", "enabled", "true"),
                ("fleet", "enabled", "true"),
                ("islands", "exclude_from_market", "true")]

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

function main(args)
    usage = "julia scripts/make_run_config.jl <out.toml> --stage markets|redispatch [--gas on|off] [--res-input accepted|offered] [--config file]"
    isempty(args) && error(usage)
    out = args[1]
    opt = Dict("--gas" => "off", "--config" => joinpath(REPO, "config.toml"))
    i = 2
    while i <= length(args)
        args[i] in ("--stage", "--gas", "--res-input", "--config") && i < length(args) || error(usage)
        opt[args[i]] = args[i+1]
        i += 2
    end
    stage = get(opt, "--stage", "")
    stage in ("markets", "redispatch") || error(usage)
    opt["--gas"] in ("on", "off") || error(usage)
    res = get(opt, "--res-input", "")
    res in ("", "accepted", "offered") || error(usage)

    raw = read(opt["--config"], String)
    crlf = occursin("\r\n", raw)
    lines = split(replace(raw, "\r\n" => "\n"), "\n"; keepempty = true) .|> String
    if stage == "markets"
        set_key(lines, "redispatch", "enabled", "false")
    else
        set_key(lines, "redispatch", "enabled", "true")
        set_key(lines, "redispatch", "from_saved", "\"BAL\"")
    end
    opt["--gas"] == "on" && for (sec, key, val) in GAS_ON
        set_key(lines, sec, key, val)
    end
    res == "" || set_key(lines, "run", "res_input", "\"$res\"")
    text = join(lines, "\n")
    crlf && (text = replace(text, "\n" => "\r\n"))
    mkpath(dirname(abspath(out)))
    tmp = out * ".tmp"
    write(tmp, text)
    mv(tmp, out; force = true)
    println("wrote $out (stage $stage, gas $(opt["--gas"])$(res == "" ? "" : ", res_input " * res))")
end

main(ARGS)
