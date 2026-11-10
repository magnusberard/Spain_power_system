# Config for real time only, replayed on a saved in-chain week (10 Nov 2026): the week's own config_inchain.toml with
#   [redispatch] from_saved = "BAL"            the anchor is the week's bal_dispatch.csv (phase I's DC changes included)
#   [redispatch.phase1] in_chain = false, replay_saved = true
#                                              phase I's effects on real time from rd_phase1*.csv (rd_phase1_replay!)
#   [redispatch.reserve] e2_deliverable        fix A on (--deliverable) or off (to check that the replay reproduces the run)
# Everything else (markets' settings, real time's rules) stays as the week ran. Real time does not feed back into the
# markets or the next week, so a year's real time can be rerun week by week, in parallel.
#
#     julia redispatch_realism/make_rt_replay_config.jl <week>/config_inchain.toml <out.toml> [--deliverable]
using TOML

function main(args)
    length(args) >= 2 || (println(read(@__FILE__, String)[1:900]); return)
    cfg = TOML.parsefile(args[1])
    rd = cfg["redispatch"]
    get(get(rd, "phase1", Dict()), "in_chain", false) || error("$(args[1]) is not an in-chain run: nothing to replay")
    rd["from_saved"] = "BAL"
    rd["phase1"]["in_chain"] = false
    rd["phase1"]["replay_saved"] = true
    get!(rd, "reserve", Dict{String,Any}())["e2_deliverable"] = "--deliverable" in args
    open(args[2], "w") do io
        # no path in the header: merge_runs.py compares config_used.toml byte for byte across the weeks
        println(io, "# Written by redispatch_realism/make_rt_replay_config.jl from the week's config_inchain.toml; comments are not kept.")
        TOML.print(io, cfg; sorted = true)
    end
    println("wrote $(args[2]) (real-time replay, fix A $("--deliverable" in args ? "on" : "off"))")
end

main(ARGS)
