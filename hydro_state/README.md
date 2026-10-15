# hydro_state — the 2024 reservoir state from observation

## Status and handover (2026-10-15, Magnus → Lars Erik)

Branch `hydro-state` (pushed, not merged), based on `main` `0558164`. The full write-up is in the
vault: `wiki/code/model-changes-hydro-state.md` (§15), `wiki/syntheses/hydro-state-2024.md` (results)
and `work/issues/hydro-seasonal-water-value.md` (next steps, commands).

| Variant | Policy trained | Simulated | Reservoir check | Price test | Verdict |
|---|---|---|---|---|---|
| `observed` | yes | yes | yes | yes | rejected (water value ~22) |
| `aligned` | yes (policy in `Data/hydro_state/policies/`) | yes | yes | yes | passes on price, wrong reason |
| `aligned_observed` | = `aligned` | yes | yes | yes | right reservoir in H1, narrow fail |
| `aligned_rc` | yes (policy in `Data/hydro_state/policies/`) | yes | **not yet** | **not yet** | — |
| `aligned_rc_observed` | = `aligned_rc` | **not yet** | — | — | — (the candidate) |

**Next (about 1 h, no training needed):**
```bash
HYDRO_STATE_CONFIG=hydro_state/hydro_state_aligned_rc_observed.toml julia --project=. hydro_state/midterm_observed.jl reuse   # ~5 min
python hydro_state/compare_reservoir.py --label aligned_rc --omie <spain-model-runs>/reference/real_hourly_2024.csv.gz
python hydro_state/compare_reservoir.py --label aligned_rc_observed --omie <same>
bash hydro_state/run_da_parallel.sh hydro_state/config_aligned_rc_observed.toml results/hydro_state/runs/aligned_rc_observed 7   # ~25 min
bash hydro_state/run_da_parallel.sh hydro_state/config_aligned_rc.toml results/hydro_state/runs/aligned_rc 7                     # ~25 min
python hydro_state/compare_prices.py results/hydro_state/runs/aligned_rc_observed <spain-model-runs>/runs/2024-01-01_2024-offered
python hydro_state/compare_prices.py results/hydro_state/runs/aligned_rc <same>
```
The `reuse` run seeds `results/hydro_state/{train,cuts}_aligned_rc.json` from
`Data/hydro_state/policies/` on a fresh clone. `compare_reservoir.py` compares against the
baseline path of the 2026-10-13 runs, committed as `Data/hydro_state/reference_baseline_*.csv`. Note
that this is **not** the same as the tracked `Data/Volume_Scen0_OUT_sddp4.csv`: that file comes from
an earlier training of the same baseline (the ES level differs by up to 0.45 TWh, 0.15 TWh on
average), so SDDP retrains are not bit-for-bit reproducible.

**Pitfalls:**
- `hydro_state/config_<label>.toml` are full copies of the `config.toml` they were generated from
  (`0558164`). After merging a newer `main` (e.g. `50f7ec6`, island switches) regenerate them
  (`... midterm_observed.jl reuse` rewrites the config copy from the current `config.toml`), or they
  silently lack the new settings.
- Run the two day-ahead tests one after the other. Two at once ran the PC out of memory (Claude Code
  killed the run), and a sleeping PC stretched a 25-min test to 2 h.
- `results/midterm4_cuts.json` is shared with plain `midterm_sddp4.jl`. The script swaps its own
  policy in and restores the slot (checked by SHA-1), but a killed run can leave it swapped. Compare
  it with `results/hydro_state/train_observed.json`, which is the baseline policy.

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

## Results so far (label `observed`, commit `a8577d3`, 2026-10-13)

Reservoir path (`compare_reservoir.py`), fill error vs REE: Jan–Jun 34.7 → 11.7 pp, Jul–Dec
14.7 → 13.6 pp. 2024 inflow 34.1 TWh vs REE producible 35.2 TWh; no spill. The release
**timing is not fixed**: April–May 1.9 / 0.7 TWh (OMIE hydro 4.1 / 2.9), November–December
4.5 / 5.8 TWh (2.6 / 2.5). The fill overshoots to 87 % in June (REE 72–76 %).

Day-ahead price, full year, day-ahead only, offered solar/wind (`compare_prices.py`, against the
published "2024, offered solar/wind" run `539be8c`, which this setup reproduces to 0.04 €/MWh):

| | Real | Baseline | Observed | MAE baseline → observed |
|---|---|---|---|---|
| Jan–Jun | 39.1 | 53.5 | 42.3 | 29.4 → 27.9 |
| Jul–Dec | 86.1 | 67.1 | 45.0 | 31.6 → 46.3 |
| Year | 62.6 | 60.3 | 43.7 | 30.5 → 37.1 (correlation 0.56 → 0.40) |

March–May improve by 5–13 €/MWh per month; every month from June gets worse. At a
realistic fill, the cuts value water at about 21–25 €/MWh, far below gas, so hydro undercuts gas
all year. **Verdict: rejected on the test half.** The volume is no longer the main error; the
water value is (W6). Next: diagnose the SDDP's own price level and gas path (`midterm_sddp4.jl
resim`) before changing anything; then the timing, through structural limits on how much water the
pooled reservoir can shift between seasons (REE's annual vs multi-year reservoirs, minimum flows;
Arvesen et al. 2025), calibrated on 2014–2023 and tested on 2024.

## W6 diagnosis: the SDDP's own Spain is too cheap (`diagnose_sddp.py`)

From `midterm_sddp4.jl resim` (20 sampled years, baseline cuts), the SDDP's Spanish price
averages 48.9 €/MWh in 2024 against OMIE's 63.0. The most frequent price levels are 22 €/MWh (the
2,600 MW `[chp]` cogeneration block) and 15.4 €/MWh (nuclear). Spain's 2024 balance against REE:
nuclear + CHP + waste 91.4 vs 70.6 TWh, gas + coal 5.7 vs 32.1 TWh. Nuclear runs at full nameplate
and the CHP group at its annual defaults, while the market chain has used the observed per-day
values since October. Water priced against that Spain is cheap at any fill. Cross-border flows
are also off (REE 2024: net import from France 3.0 TWh, net export to Portugal 10.5; the SDDP
shows 9.3 and 23.8).

**Fix (consistency, not fitting):** `build_stage_supply.jl` turns the chain's own per-day tables
into a weekly file, and `midterm_sddp4.jl` reads it through `[midterm4].es_stage_supply_file`.
That hook is off by default and was verified to leave the baseline byte-identical. Caveat: the
spring dip in nuclear availability (0.44–0.70 in April–May) is partly economic curtailment in a
low-price spring, so it is partly a market outcome. The chain already uses it as an input. With
the hook on and the old cuts, the balance moves to 78.3 / 9.9 TWh (about 4.5 TWh of that is
mini-hydro, which REE counts as hydro).

### Results with the supply aligned (2026-10-13 evening, policy `aligned`, hook commit `1f628da`)

The water value along the simulated path (2024 mean) is 22.6 for `observed`, 77.2 for `aligned` and
62.1 for `aligned_observed` (€/MWh). Reservoir fill error against REE, Jan–Jun / Jul–Dec (pp): baseline
34.7 / 14.7, `aligned` 23.4 / 14.2, `aligned_observed` **6.9** / 14.0.

Day-ahead price, full year, same setup as above (MAE vs OMIE, €/MWh):

| | Jan–Jun | Jul–Dec (test) | Nov–Dec | Year | Corr. | Mean (real 62.6) |
|---|---|---|---|---|---|---|
| baseline (published) | 29.4 | 31.6 | 45.7 / 43.6 | 30.5 | 0.56 | 60.3 |
| `observed` | 27.9 | 46.3 | 67.6 / 67.4 | 37.1 | 0.40 | 43.7 |
| `aligned_observed` | 30.7 | 33.1 | 49.7 / 47.9 | 31.9 | 0.51 | 62.4 |
| `aligned` | 32.8 | **26.5** | **31.3 / 31.6** | **29.6** | **0.64** | 71.0 |

Reading: aligning the SDDP's supply with the chain fixes the water-value **level**. Both aligned
variants lift it from ~22 to 62–77 €/MWh and cut the winter error. `aligned` passes the test
half on price, but partly for the wrong reason: it keeps the 30 % start and is nearly empty in
December (12 % vs REE 52 %), which props up the winter price. `aligned_observed` has the right
reservoir in the first half, but it holds too much water into autumn (72 % vs REE 55 % in Sep–Oct),
so its winter price is too low (58–65 vs 104–109), and its spring price is too high (water still
valued at 65–70 €/MWh at 76–87 % fill). The remaining error is the **seasonal shape** of the water
value: the next step is the structural one (annual vs multi-year reservoirs, minimum flows),
calibrated on 2014–2023 and judged on the reservoir path first, then on price.

## Variants

| Settings file | label | System | Start / inflow | Policy |
|---|---|---|---|---|
| `hydro_state.toml` | observed | as baseline | REE / index | own |
| `hydro_state_aligned.toml` | aligned | weekly ES supply | dataset 30 % / climate year | own |
| `hydro_state_aligned_observed.toml` | aligned_observed | weekly ES supply | REE / index | `train_label = "aligned"` |

`midterm_sddp4.jl` reads and writes one shared cuts file, `results/midterm4_cuts.json`. The script
swaps each policy's own copy (`results/hydro_state/train_<train_label>.json`) into that slot and
puts the previous content back afterwards, so cuts from one system never reach another.
`cuts_<train_label>.json` holds the policy after W3. Delete it to retrain after changing
`[training]`.

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
