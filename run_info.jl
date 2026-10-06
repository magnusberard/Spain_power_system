# ============================================================
# run_info.jl — record what a run was made from
# ============================================================
# Writes <results>/run_info.json when a run starts (code version, uncommitted
# files, study days, config, solver, who ran it) and completes it when the run
# ends (finish time, runtime, solved AC hours). A copy of the config goes to
# config_used.toml and, if the working tree had uncommitted changes, their diff
# to run_info_diff.patch, so the run can be reproduced later.
#
# scripts/publish_run.py reads run_info.json to label a run in the results
# viewer (github.com/Leide0022/spain-model-runs). Nothing here changes results;
# if git is not available the code fields are left empty.

import JSON
using Dates

# Output of a git command in this repo, or "" if git is missing or fails.
function git_out(args::String...)
    try
        cmd = Cmd(`git -C $(@__DIR__) $(collect(args))`; ignorestatus = true)
        return strip(read(pipeline(cmd; stderr = devnull), String))
    catch
        return ""
    end
end

function run_info_user()
    name = git_out("config", "user.name")
    isempty(name) ? get(ENV, "USERNAME", get(ENV, "USER", "")) : name
end

function write_run_info(results::AbstractString, info::AbstractDict)
    open(joinpath(results, "run_info.json"), "w") do io
        JSON.print(io, info, 2)
    end
end

"""
    write_run_info_start(results; days, config_path, extra = Dict())

Record the run's starting point in `results/run_info.json` and return the Dict,
which `write_run_info_end!` completes when the run is done.
"""
function write_run_info_start(results::AbstractString; days, config_path::AbstractString,
                              extra::AbstractDict = Dict{String,Any}())
    # porcelain lines are "XY path"; the status letters can be preceded by a space
    dirty = [String(split(strip(l); limit = 2)[end])
             for l in split(git_out("status", "--porcelain", "--untracked-files=no"), '\n') if !isempty(strip(l))]
    isempty(dirty) || write(joinpath(results, "run_info_diff.patch"), git_out("diff", "HEAD"))
    isfile(config_path) && cp(config_path, joinpath(results, "config_used.toml"); force = true)
    day_strings = sort!(string.(collect(days)))
    info = Dict{String,Any}(
        "schema"            => 1,
        "started"           => Dates.format(now(), "yyyy-mm-dd HH:MM:SS"),
        "ran_by"            => run_info_user(),
        "host"              => gethostname(),
        "branch"            => git_out("rev-parse", "--abbrev-ref", "HEAD"),
        "commit"            => git_out("rev-parse", "--short", "HEAD"),
        "commit_message"    => git_out("log", "-1", "--format=%s"),
        "uncommitted_files" => dirty,
        "days"              => day_strings,
        "first_day"         => isempty(day_strings) ? "" : first(day_strings),
        "last_day"          => isempty(day_strings) ? "" : last(day_strings),
        "config"            => basename(config_path),
        "julia"             => string(VERSION),
    )
    merge!(info, extra)
    write_run_info(results, info)
    return info
end

"""
    write_run_info_end!(results, info; ac_solved = nothing, ac_total = nothing)

Add the finish time, runtime and solved AC hours to `info` and rewrite run_info.json.
"""
function write_run_info_end!(results::AbstractString, info::AbstractDict; ac_solved = nothing, ac_total = nothing)
    t0 = DateTime(info["started"], "yyyy-mm-dd HH:MM:SS")
    t1 = now()
    info["finished"] = Dates.format(t1, "yyyy-mm-dd HH:MM:SS")
    info["runtime_min"] = round(Dates.value(t1 - t0) / 60_000; digits = 1)
    info["ac_hours_solved"] = ac_solved
    info["ac_hours_total"] = ac_total
    write_run_info(results, info)
    return info
end
