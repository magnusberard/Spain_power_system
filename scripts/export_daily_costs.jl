# Daily 2024 costs exactly as the model computes them (fuel_prices.jl)
using TOML, Dates
repo = ARGS[1]; cfg = TOML.parsefile(ARGS[2]); out = ARGS[3]
include(joinpath(repo, "fuel_prices.jl"))
fp = load_fuel_prices(cfg; root = repo)
cc = load_coal_srmc(cfg)
open(out, "w") do io
    println(io, "date,gas_056,gas_058,gas_060,gas_fuel_th,coal")
    for d in Date(2024,1,1):Day(1):Date(2024,12,31)
        g(e) = gas_srmc_eta(fp, e, d)
        println(io, join([string(d), g(0.56), g(0.58), g(0.60), gas_fuel_cost_th(fp, d), coal_srmc(fp, cc, d)], ","))
    end
end
println("wrote ", out)
