# hydro_state — the 2024 reservoir state from observation

New files only: `midterm_sddp4.jl`, `bellman.jl`, `run_market_chain.jl` and `config.toml` are
unchanged. The market chain picks the result up through a config copy (`SPAIN_CONFIG`), so
week-by-week runs on Solstorm work as before.

## The problem

The mid-term SDDP that gives the market chain its water values, starting volume and daily hydro
budget starts 2024 at 30 % of the Spanish reservoir (`SS_SeasonalStorage.csv`) and replays one
climate year (1982). It saves water through the spring and empties the reservoir in winter.
REE's data show the opposite: the reservoir was 51 % full at the end of December 2023 and 76 %
full in May 2024, and 2024 was a wet year (producible index 1.43 in January, 1.70 in March).
In the 2024 runs this gives 1.9 TWh too little hydro in May and 1.3 TWh too much in
December. Gas takes the opposite swing, and the price follows.

## The rule that keeps this from fitting 2024

| The model may be given | The model must never be given |
|---|---|
| Observed **state**: the reservoir level on the start date | Real hydro **generation** or real **prices** |
| Observed **exogenous input**, revealed when it happens: this week's inflow | **Future** inflows (perfect foresight) |
| | Free parameters tuned until the price fits |

Nothing in this folder reads hydro generation or prices. The policy is trained only on the
climate-year scenarios, so it never knows future inflows. In the simulation each week's inflow
is revealed when that week is decided, the same information structure as the baseline.

## What each step does

| Step | Switch in `hydro_state.toml` | What changes |
|---|---|---|
| W1 data | — | `fetch_ree_hydro.py`: REE reserves and producible, monthly, 2014–2024 (REData, open, no token) |
| W2 start level | `[observed].observed_start` | ES starts at REE's fill at the end of the month before `bgn_date`, as a fraction of the model's reservoir size |
| W3 cut coverage | `[training].es_start_fills` | extra SDDP iterations from a spread of ES starting levels, so the water value is accurate at the fills the observed path reaches, not only near the 30 % path |
| W4 inflow | `[observed].inflow = "index"` | ES inflow each week = the model's own climatological inflow for that week × REE's producible index for that month |

Using the **index** (2024 / historical mean) rather than REE's GWh keeps the observed inflow on
the same scale and seasonal shape the policy was trained on. REE's producible also covers
run-of-river, which the model treats separately. Using a **fill fraction** for the start
level, not GWh, keeps the reservoir's position relative to full the same, and that position is
what drives the water value (spill risk). REE's capacity is about 18.5 TWh; the model's is 16.4 TWh.

Each switch can be turned off on its own (give each variant its own `label`). That separates
the effects: start level only, + inflow, + extra training.

## Why this is the standard approach, not a 2024 fit

- Long-term hydro scheduling starts from the **current reservoir state** and treats future
  inflows as **uncertain**. It is re-run as the state is observed: Pereira & Pinto (1991),
  SDDP; Gjelsvik, Mo & Haugstad (2010), long- and medium-term planning based on SDDP; the
  same structure as EMPS (Wolfgang et al. 2009, Energy 34(10)) and as FanSi upstream of
  PowerVision (Koks et al. 2026, §2.1–2.2).
- The water value depends on the reservoir level. A full reservoir with a risk of spill is worth
  less (Førsund 2015, *Hydropower Economics*). The cuts only represent that where training
  visited (Shapiro 2011, EJOR 209), hence W3.
- Inflows carry over from month to month (a wet winter predicts a wet spring). Conditioning the
  scenarios on that (PAR(p), Maceira & Damázio 2006) is a later step (W5). Feeding 2024's
  inflows in advance would be foresight, so it is not done.

## Run

```bash
python hydro_state/fetch_ree_hydro.py                    # W1, once (data is committed)
julia --project=. hydro_state/midterm_observed.jl        # W2–W4: ~45–60 min the first time
julia --project=. hydro_state/midterm_observed.jl reuse  # re-simulate/export from the saved cuts
python hydro_state/compare_reservoir.py --omie <spain-model-runs>/reference/real_hourly_2024.csv.gz
SPAIN_CONFIG=hydro_state/config_observed.toml julia --project=. run_market_chain.jl
```

The first run trains the baseline policy (as `midterm_sddp4.jl` would), writing the baseline
path to `results/hydro_state/baseline_*.csv` for comparison. The market-chain config copy
`hydro_state/config_<label>.toml` is the base config with `[bellman]` pointed at
`Data/hydro_state/*_<label>.csv`. On Solstorm, pass it as the config in the week scripts.

## How to judge it (decide before looking at prices)

1. **Reservoir path vs REE**, month by month (`compare_reservoir.py`). Only the start value is
   an input, so the rest of the year is a real test. Errors are reported for January–June and
   July–December separately: choose settings on one half, judge them on the other.
2. **Monthly hydro release vs OMIE** (shape; OMIE includes run-of-river and pumped output).
3. **Price**: full-year market runs (Solstorm), each half-year MAE and correlation vs OMIE, on
   a fixed solar/wind input. A small grid (accepted/offered × baseline/hydro-state) separates
   the two effects.

## Known limits and open points

- REE's monthly reserve is taken as the level at the **end** of that month (the 2023-12 value
  starts 2024). If REE means the monthly mean, the start shifts by about half a month
  (51 % vs 58 %). [open: check against REE's daily publication]
- Only Spain's inflow is observed. Portugal, France and the rest of Europe keep the replayed
  climate year, and so do demand, wind and solar inside the mid-term model. This changes one
  thing at a time on purpose.
- The end-of-horizon target (June 2025) is still `end_fill × the dataset's 30 % volume`. It is
  far from 2024, but it is an assumption.
- **The winter water value (W6) is not addressed here.** In January the hydro volume is right
  but the price is too low, because the water value sits well below the gas cost. Diagnose
  before changing anything: SDDP convergence (the gap between the lower and upper bound after
  60 iterations), the gas price path in the SDDP, the end penalty. No markup.
- The vault notes: `wiki/code/midterm-sddp-hydro.md`, `wiki/syntheses/model-vs-real-2024.md`,
  `wiki/syntheses/offered-vs-accepted-2024.md`.
