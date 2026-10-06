# Extending the 2024 case beyond the two validation days

**Finding.** `Data/ES_old/{load,Solar,Wind}` and `Data/crossborder.csv`
originally covered only the two hand-validated study days (8 July, 2
December 2024). The pipeline in `omie_conversion/` and `entsoe_download/`
reproduces those two days' data **exactly** from bulk-downloadable public
sources (OMIE + ENTSO-E), and extends coverage to every day from
**2024-01-01 to 2024-12-29** (364 days — all of 2024 except 30–31
December, see "Why not all 366 days"). `run_market_chain.jl`'s
`TARGET_DAYS` can cover that whole range, but is currently set to the two
reference days while it's rolled out gradually and checked at each step —
see "Rolling out beyond the two reference days" below.

This note records the formula, what was validated against what, and what is
still known-imperfect, so a future run knows exactly how much to trust each
piece.

## Why not all 366 days

- **2024-01-02 now has every input** (2026-10-02). It used to be blocked
  with 1 January because the gas SRMC needs that day's MIBGAS quote and the
  previous day's EUA settlement, and both price files started on 2 January.
  The December 2023 quotes were added (MIBGAS trading day 31/12/2023
  GDAES_D+1 "Last Price" 31.18 EUR/MWh from MIBGAS's 2023 file; EUA
  29/12/2023 77.98 EUR/t, the same Investing.com series), and
  `[bellman].bgn_date` moved to `2024-01-01` with the SDDP retrained.
- **2024-01-01 has every input too** (2026-10-05), all from real data:
  `Data/ES_old` from the OMIE technology report + ENTSO-E day-ahead
  exchange (removed from `EXCLUDED_DATES`; reproducing 2024-01-02 the same
  way gave identical values); nuclear 0.957 / coal 0.101 availability; CHP
  gas 1 023.7 / waste 463.5 / mini-hydro 1 116.8 MW (OMIE group 2 604 MW,
  low on a holiday); `Data/ES` factors from `forecast_updates/run_spain.py`
  with the gates window starting on 2023-12-31 (the code skips the first
  day of its window). Only the 1 January files were written: the longer
  window would move the other days' factors by at most 0.0013.
- **2024-12-30, 2024-12-31**: no input data generated; the forecast factors
  also need ENTSO-E data into January 2025 (the window's last day is
  skipped the same way).
- A separate, now-resolved blocker used to also stand in the way of January
  onward: `midterm_sddp4.jl` also hits a real leap-day bug (`profile_row`
  re-stamps every date onto the non-leap reference year 2023 to read an
  annual profile's day-of-year row, which crashes on a real 29 February —
  only reachable once `bgn_date` moves into or before a leap year). Fixed by
  falling back to 28 February's row on a real leap day.

## Rolling out beyond the two reference days

All the per-day input data is generated for the full 363-day range, but
`run_market_chain.jl`'s `TARGET_DAYS` is being rolled out gradually: 7 days
(15–21 September) → one month (August) → the mid-term model retrained and
re-validated → the reconstruction method itself rewritten (below) → a second
7-day window (8–14 April), each step checked before widening further.

- **August surfaced a real gap**: the nuclear/coal per-day calibration had
  only ever been written for the two original reference days, so every
  other day was silently falling back to the flat annual default instead of
  its own computed availability — this produced `LOCALLY_INFEASIBLE` hours
  on 2024-08-05. Fixed by backfilling the calibration for the full range.
- **The mid-term SDDP model was retrained** with `bgn_date = "2024-01-03"`
  (was `2024-07-02`) to cover the whole year — see `README.md`'s "Mid-term
  SDDP" workflow and "Known limitations" for the retrain's validation
  result against the two reference days. Retrained again on 2026-10-02 with
  `bgn_date = "2024-01-01"`: DA, ID2 and ID3 prices on both reference days
  unchanged; on 8 July CID/BAL rise from ~33 to ~47 EUR/MWh because the
  day's start volume (8.95 TWh) falls on a different step of the binding-cut
  water value (52.9 instead of 36.8 EUR/MWh). The old and new cut curves
  have nearly the same steps; with 60 iterations they are coarse, so the
  water value at a given volume can jump between retrains.
- **The April week surfaced a real, structural finding, not a data bug**:
  5 of 168 hours (~3%) failed with `LOCALLY_INFEASIBLE` in the AC
  redispatch. Checked directly in the Ipopt logs — both inspected failures
  show `EXIT: Converged to a point of local infeasibility. Problem may be
  infeasible.` with a small residual constraint violation (0.003–0.02) after
  100+ iterations: the solver got stuck on a genuinely hard nonconvex
  instance, not evidence the hour is truly infeasible. Re-running the exact
  same week after the reconstruction rewrite below reproduced the identical
  5 failing hours (12 Apr h21; 13 Apr h13, h14, h19; 14 Apr h19) — confirming
  this is a solver characteristic independent of the input data.

## The reconstruction formula

```
domestic = Coal + Nuclear + CCGT + Hydro + Wind + SolarThermal + SolarPV
           + Cogeneration/Waste/SmallHydro
load  = domestic + max(0, day-ahead scheduled FR→ES exchange)
                  + max(0, day-ahead scheduled PT→ES exchange)
wind  = Wind
solar = SolarThermal + SolarPV
```

Validated to an **exact match** (0.000 MW, every hour) against
`Data/OMIE/actual_generation_{July_8,Dec_2}.csv` for Wind and Solar, and to
within a small, fully-attributed residual for load (see "Known gaps"
below).

The two import terms are ENTSO-E's **day-ahead scheduled commercial
exchange** (documentType `A09`, contract type `A01` — not documentType
`A11`, which is always real-time *actual* physical flow and does **not**
reproduce these columns; that was tried and ruled out first). Clamped at
zero because OMIE's own published import columns read zero during export
hours rather than going negative — the load series already has the export
netted out (see `method_export_relocation.md`).

## Where `domestic`'s eight terms come from

**Current method**: OMIE's own **"Energía horaria por tecnologías"** report
(file-access report code `INT_PBC_TECNOLOGIAS_H`, system code `1` = Spain),
fetched by `omie_conversion/fetch_omie_technology.py` and cached in
`OMIE_data/tecnologias/`. This is OMIE's **own pre-aggregated national
total per technology per hour** — no per-unit lookup needed at all.

This replaced an earlier method (below) that reconstructed the same eight
totals from OMIE's per-unit day-ahead schedule (`pdbf_YYYYMMDD.1`) via a
unit-code → technology lookup table. The replacement was verified before
switching over:

- **Exact match** (0.0000 MW) against `Data/OMIE/actual_generation_July_8.csv`,
  all 24 hours, all 13 columns — confirming the URL/report genuinely is the
  same underlying data, just accessed a different way.
- **Same 23/24/25-hour DST pattern** as `pdbf` (checked against 31 March,
  27 October, and a normal day in 2024), so the existing `to_24()` needed no
  changes.
- **Historical coverage confirmed working back through 2022 and 2023**
  (spot-checked at three dates), unlike the unit list below, because this
  report is **date-parameterized and permanently archived per day** by
  OMIE's own server — not a live-only snapshot with a Wayback-Machine-shaped
  hole in it.
- Re-validated against both reference days after switching: 2 December
  exact; 8 July's load off by the same 4.3 MW as before (the single known
  Storage blip, unchanged — not a regression).
- **Eliminates the unit-mapping gap entirely, not just reduces it.** The
  previously-worst day for unmapped units (2 January 2024, ~6,977 MW /
  ~0.9% of that day's generation) is now exactly 0 MW unmapped, with the
  same result across the whole re-generated year.

`domestic`'s eight terms are the report's `CARBÓN`, `NUCLEAR`,
`CICLO COMBINADO`, `HIDRÁULICA`, `EÓLICA`, `SOLAR TÉRMICA`,
`SOLAR FOTOVOLTAICA`, and `COGENERACIÓN/RESIDUOS/MINI HIDRA` columns —
the same three columns excluded before (`FUEL-GAS`, `AUTOPRODUCTOR`,
`ALMACENAMIENTO`) remain excluded, unchanged (see "Known gaps" below). This
is still **day-ahead cleared** data, not real-time settlement — the report
code (`PBC` = "Programa Base de Casación," the same family as `pdbf`)
confirms it, and this matters directly for the `gas_mw` discussion below:
switching to this report did not and could not resolve that discrepancy,
since both the old and new methods read the same kind of (day-ahead)
number.

### Superseded: the per-unit + unit-technology-map method

Kept here for context, since `omie_conversion/unit_technology_map_merged.csv`,
`build_unit_map.py`, and `parse_unit_list.py` are still in the repo (harmless
to keep; no longer used by `convert_omie_to_model_data.py`).

OMIE's "LISTADO DE UNIDADES OFERTANTES VIGENTES" (list of currently active
bidding units, code → technology) exists only as a **live, continuously
overwritten snapshot** — OMIE has no historical/dated version of this file,
in the file-access system or anywhere else on their site. The only
historical coverage available at all was via the Wayback Machine, plus
whatever dated copies a person happened to have downloaded and kept — four
snapshots were found this way (5 May 2022, 24 Jun 2024, 12 Jul 2024,
10 Sep 2025), merged with a primary/fallback-only rule (close-to-2024
snapshots win ties; the 2022 one only fills codes none of the close
snapshots have, never overrides them, since a unit code can be reused for a
different unit years later).

This worked, and reproduced the two reference days exactly — but had a real
data gap: **no snapshot from anywhere in 2023**, so a unit that started up,
shut down, or changed classification during that ~2-year window had no
dated snapshot from its actual era. Measured impact: 0 MW unmapped exactly
at the snapshot dates, rising to ~6,977 MW (~0.9%) on the worst day
(2 January 2024) found while generating the full year — small, and the
merge logic itself was never the problem, but a real, permanent limitation
(the Wayback Machine has nothing from 2023 for this page either — checked
directly). The technology-report method above sidesteps this entirely,
since it needs no unit identification at all.

## `crossborder.csv`

Extended the same way, using ENTSO-E's **actual** (not day-ahead) physical
flow data (documentType `A11` — the correct source for the AC redispatch,
which needs what really happened, not what was scheduled). The file format
uses the `Day` column as plain ISO dates (`"2024-07-08"`), which scales to
any number of days without a growing label dictionary; `crossborder.jl` and
`plotting/exports_ramp_2024.py` match.

**Gotcha hit and fixed**: `build_crossborder_csv.py` **overwrites the whole
file** rather than merging in a new date range — running it a second time
for just the new January–June range silently wiped out the already-generated
July–December rows. Recovered via git (uncommitted at the time) and fixed by
re-running it for the full combined range in one call. Always pass the
complete `--from-date`/`--to-date` range you want the file to end up
containing, not just the new part.

## Per-day calibration (`config.toml`)

- **`[da.nuclear_availability_by_date]` / `[da.coal_availability_by_date]`**:
  computed the same way the original two days were (peak OMIE-cleared MW ÷
  nameplate, now sourced from the technology report above) — mechanical, no
  new data source, no known caveats. Backfilled for all 364 days;
  `add_nuclear_coal_calibration.py` gained a `--force` flag to recompute and
  replace already-present dates (needed for the reconstruction-method
  switch, since this was a redo, not a gap-fill) — the two original
  hand-derived reference days are hard-coded as protected and are never
  touched by `--force`.
- **`[chp.by_date]`**: three-way split of OMIE's cogeneration/waste/
  mini-hydro group — waste and mini-hydro from ENTSO-E generation by fuel
  type (minus the OMIE-cleared equivalent for mini-hydro), gas CHP as the
  remainder of the group (see the `[chp]` comments in `config.toml`).
  - `waste_mw` and `minihydro_mw` reproduce both reference days almost
    exactly (within ~1%) and are computed per-day for the full range.
  - `gas_mw` is the **remainder of the OMIE group** once the other two
    blocks are taken out:

    ```
    gas_mw = OMIE "COGENERACIÓN/RESIDUOS/MINI HIDRA" daily mean − waste_mw − minihydro_mw
    ```

    This reproduces both reference days (8 July: 3,410.5 − 730 − 420 =
    2,260.5 MW vs. 2,260; 2 December: 3,918.6 − 650 − 350 = 2,918.6 MW vs.
    2,920) and the paper's 54 / 70 GWh/day (Spanish model paper, §5.1.1).
    It is consistent with the paper's own validation: the model clears "the
    cogeneration group 81.8 against 81.9" GWh on 8 July, which only holds
    if the three blocks were sized to add up to the group (2,260 + 730 +
    420 MW × 24 h = 81.8 GWh). Written for every day by
    `add_chp_calibration.py --gas-from-config`, from the `waste_mw` /
    `minihydro_mw` already in `config.toml`; the two reference days keep
    their hand-derived values.

    **Caveat — the paper's wording.** §5.1.1 describes the split as "taking
    differences against the OMIE programme" for each ENTSO-E category, which
    read literally for gas would be ENTSO-E Fossil Gas − OMIE cleared CCGT.
    That formula does not reproduce the paper's own numbers (see below);
    the remainder of the group does. The method was therefore recovered
    from the numbers, not from the prose — worth confirming with Ehsan.

    **Why "ENTSO-E Fossil Gas − OMIE cleared CCGT" fails.** It came out
    consistently ~1.8–2.4× too high (8 July: 4,015 MW; 2 December:
    7,053 MW), with both inputs independently verified. It nets OMIE's
    **day-ahead cleared** CCGT against ENTSO-E's **actual delivered** Fossil
    Gas, and in Spain much of the CCGT output is committed after the
    day-ahead, so that output stays in the remainder and is mislabelled as
    cogeneration. ENTSO-E's per-generation-unit report (documentType `A73`)
    for the named CCGT plants shows the size of the gap:

    | | OMIE day-ahead CCGT | ENTSO-E actual CCGT (named units) |
    |---|---|---|
    | 8 July | 0.39 GWh | 57.59 GWh |
    | 2 Dec | 123.05 GWh | 244.51 GWh |

    **Full-year spread.** Over the 363 days `gas_mw` has a median of
    2,277 MW and a mean of 2,293 MW (the flat 2,600 MW default it replaces
    sat above most of the year), with monthly means from 1,761 MW (April) to
    ~2,620 MW (November–December). Gas, waste and mini-hydro add up to the
    OMIE group on every day (within 0.1 MW). The low tail comes from the
    mini-hydro upper bound, not the gas formula: on wet spring days
    "ENTSO-E Hydro − OMIE Hydropower" also picks up hydro traded after the
    day-ahead and reaches 1,200–1,900 MW, and gas, as the remainder, drops
    accordingly — 13 days fall below 1,500 MW, the lowest being 2024-04-06
    (30.5 MW, mini-hydro 1,927 MW) and 2024-04-09 (444 MW). On 24 days
    mini-hydro is 0 and gas is correspondingly a little high. Accepted as
    is: the group total, and therefore the cheap supply the market sees, is
    exact; only the gas/hydro split (flexibility below the 22 EUR/MWh gas
    offer, and CO₂ accounting) is affected on those days. Per-day figures:
    `results/chp_gas_mw_report.csv` from the script's report.

## Forecast-update factors (`Data/ES`)

`Data/ES/{load,Solar,Wind Onshore}/<d>_<m>_<yyyy>.csv` hold, per hour, a
factor per market gate (`DA, ID2, ID3, CID, BE`); the chain multiplies the
`Data/ES_old` day-ahead baseline by it. They come from Wouter Koks'
forecast-update model (Spanish model paper §3.5; vendored in
`forecast_updates/`, see `UPSTREAM.md`): a linear regression trained on
2022–2024 ENTSO-E data predicts, at each gate time, the coming hours from the
day-ahead forecast, the last five observed values and their forecast errors,
and time features; `BE` is the realised value.

**Regenerated 2026-10-04** (`forecast_updates/run_spain.py`, train on
2022–2024, gates 2024-01-01..2024-12-30, normalize 2024-01-02..2024-12-29;
2024-01-01 added 2026-10-05 from gates 2023-12-31..2024-12-30), replacing
the files shipped with the repo:

- **Reproduction check first.** Re-running upstream's own method
  (`--method ratio`, UTC days) matches the shipped files to 0.03 % (load) –
  0.5 % (wind, solar) of the baseline MW on average; exact equality is not
  possible (ENTSO-E revises its data; package versions).
- **Spanish local time.** 361 of the 363 shipped files were indexed in UTC
  (only 8 July and 2 December in local time), but the chain reads the 24 rows
  as local hours, so their factors sat 1 h (winter) / 2 h (summer) early. The
  regenerated files are local days; clock-change days are mapped to 24 rows
  with the `to_24` rule above.
- **No division by a near-zero forecast (`--method floor`).** Upstream divides
  each gate by the model's own DA-gate forecast. When that is close to zero
  the factor explodes: on 2024-04-28 13:00 the DA-gate wind forecast was
  35 MW, the BE factor 15, and the chain's 2 022 MW baseline became the whole
  30 434 MW fleet. The factor is now
  `1 + (gate − DA) / max(DA, 5 % of installed capacity)` (installed capacity
  from ENTSO-E for the year): identical to upstream wherever DA is above 5 %
  of capacity (97 % of wind stage-hours), bounded where it is not
  (2024-04-28 13:00 BE: 2 920 MW). The model's own installed-capacity cap
  (`prepare_network`) only stops values above the fleet, so it did not catch
  this.
- **Days without ENTSO-E's day-ahead forecast get factor 1** (no forecast
  update): solar 2024-12-07..11, wind 2024-06-02. The model's input on those
  days is filled-in data, which made solar fall from ~9 GW to under 1 GW at
  balancing.

Compared on all 363 days as the chain uses them (stage MW = factor × baseline,
capped at the fleet), against ENTSO-E's realised change (actual − day-ahead
forecast) at balancing:

| | upstream ratio | **floor 5 % (used)** | ENTSO-E forecast as divisor |
|---|---|---|---|
| wind: factors > 2 or < 0.3 (baseline > 200 MW) | 56 | **3** | 11 |
| wind: balancing change vs realised, correlation | 0.88 | **0.92** | 0.91 |
| solar: factors > 2 or < 0.3 | 636 | **101** | 5 976 |
| solar: balancing change vs realised, MAE | 443 MW | **419 MW** | 1 675 MW |
| load | — | identical to ratio | — |

The ENTSO-E-divisor variant fails for solar because ENTSO-E's solar
forecast is ~10 MW at night. The 41 wind stage-hours that still move more
than 5 GW are real forecast misses (e.g. 2024-03-10: actual 9 GW below the
day-ahead forecast). The 5 % is a modelling choice; it only acts in
low-output hours. The comparison scripts are outside the repo
(`forecast_data/_analysis_scripts/compare_variants.py`).

## Known gaps in `load`

Three of `load`'s thirteen OMIE technology components (Fuel-Gas,
Self-producer, Storage) are not modelled — on both reference days they were
~0 (a single 4.3 MW storage blip at one hour on 8 July was the only nonzero
occurrence), so they're assumed negligible everywhere. This hasn't been
checked on every day of the generated range; a day with genuine battery
activity or self-producer generation would be silently under-counted.

## Checking the model's own dispatch against real data

Separate from validating the *input* reconstruction (above), the technology
report can also check the model's *output* — the final AC-redispatch fuel
mix (`results/fuel_mix.csv`) is a genuine model decision, not something
forced to match real data, so comparing it against OMIE's real technology
report for the same days is a real accuracy check. Done once, for the
8–14 April 2024 test week (163 of 168 hours; the 5 `LOCALLY_INFEASIBLE`
hours have no dispatch to compare):

| Fuel | Mean abs diff/hour | % of real weekly total |
|---|---|---|
| Nuclear | 796 MW | 26.7% |
| Coal | 28 MW | ~100% (tiny real base, see below) |
| Wind | 1,102 MW | 17.0% |
| Solar | 781 MW | 12.0% |

Gas/Biomass/Hydro were **not** included in this table — the model's `Gas`
fuel category combines real CCGT dispatch *and* the synthetic CHP gas
block, `Biomass` and part of `Hydro` similarly absorb the CHP waste/mini-hydro
blocks, so comparing them directly against OMIE's `CICLO COMBINADO` /
`COGENERACIÓN...` / `HIDRÁULICA` columns one-to-one is comparing mismatched
categories (an early attempt showed a nonsensical 120,000%+ "error" on Gas
purely from this mismatch). Redoing this properly — separating the CHP
synthetic blocks out of the model's totals before comparing — has not been
done.

**Coal's near-total miss has a concrete, structural explanation, checked
directly**: real coal ran a small, consistent ~245 MW overnight
(00:00–02:00) every night that week and exactly zero the rest of each day —
a pattern consistent with 1–2 units held at a technical minimum rather than
shutting down — while the model dispatched **zero coal for the entire
week**. The per-day coal *availability* calibration itself is not the
problem (244 MW computed vs. ~245 MW real peak, i.e. correct); the gap is
that **the model has no minimum-generation floor for coal**, unlike nuclear
(`[da].nuclear_min_gen_frac = 0.8`). With nothing forcing it to stay
online, the cost-minimizing solver drops coal to zero whenever anything
else is cheaper, which in mild April conditions with ample hydro/wind/solar
is apparently every hour. Not fixed as of this note — flagged as a
modelling gap, not a data gap, pending a decision on whether to add a
`coal_min_gen_frac` mirroring the nuclear one.

## Reproducing / extending this pipeline

Raw data lives in `OMIE_data/` and `entsoe_download/`, both **outside** this
repo (siblings of it) — they're too large to commit (hundreds of MB) and are
fully re-derivable from public sources, so only the small pipeline scripts
and their (small) output land in git. The ENTSO-E download scripts are in
this repo's own `entsoe_download/` folder, and write their CSVs and `raw/`
cache to the sibling data folder (`../entsoe_download/` from the repo root,
or `$ENTSOE_DIR` if set) — the same place `omie_conversion/` reads from.
They import pandas.

```bash
# 1. OMIE's technology-breakdown report (no login needed, one file per day,
#    permanently archived -- works for any historical date, including 2022/2023)
python3 omie_conversion/fetch_omie_technology.py --from-date 2024-01-01 --to-date 2024-12-31

# 2. ENTSO-E day-ahead exchange (needs ENTSOE_TOKEN) -- for the load formula
python3 entsoe_download/fetch_da_exchange_year.py

# 3. ENTSO-E actual physical flows -- for crossborder.csv
python3 entsoe_download/fetch_crossborder_year.py
python3 omie_conversion/build_crossborder_csv.py --from-date 2024-01-01 --to-date 2024-12-29
#    (always pass the FULL date range you want the file to contain -- this
#     script overwrites the whole file rather than merging, see the
#     crossborder.csv section above)

# 4. ENTSO-E generation by fuel type -- for the CHP calibration
python3 entsoe_download/fetch_chp_entsoe_year.py

# 5. Validate against the two reference days before trusting any of the above
python3 omie_conversion/convert_omie_to_model_data.py --validate

# 6. Write Data/ES_old/{load,Solar,Wind}/
python3 omie_conversion/convert_omie_to_model_data.py --all --from-date 2024-01-01 --to-date 2024-12-29

# 7. Per-day config.toml calibration (--force recomputes/replaces already-present
#    dates instead of skipping them; the two reference days are always protected)
python3 omie_conversion/add_nuclear_coal_calibration.py --from-date 2024-01-01 --to-date 2024-12-29 --force
python3 omie_conversion/add_chp_calibration.py --from-date 2024-01-01 --to-date 2024-12-29 --force
#    gas_mw alone, from the waste/minihydro already in config.toml (needs only
#    OMIE_data/tecnologias/; add --dry-run to just write the report)
python3 omie_conversion/add_chp_calibration.py --from-date 2024-01-01 --to-date 2024-12-29 --gas-from-config

# 8. Retrain the mid-term SDDP model to cover the new range
#    (edit [bellman].bgn_date in config.toml first)
julia --project=. midterm_sddp4.jl

# 9. Forecast-update factors Data/ES (needs ENTSOE_TOKEN for the download only;
#    work folder ../forecast_data). The gates window must start one day
#    before and end one day after the days you want (edge days are skipped).
python3 forecast_updates/run_spain.py download --years 2022 2023 2024
python3 forecast_updates/run_spain.py train
python3 forecast_updates/run_spain.py gates --from 2023-12-31 --to 2024-12-30
python3 forecast_updates/run_spain.py normalize --from 2024-01-01 --to 2024-12-29 --out Data/ES

# 10. Optional, for validation only (the model does not read it): ENTSO-E actual
#     generation per production type, all 17 types, 2020-01-01 to yesterday by
#     default (--from/--to). This is what plants really produced, the reference
#     for the redispatch stage; OMIE's technology report is only the day-ahead
#     programme. Writes ../entsoe_download/generation_entsoe.csv.
python3 entsoe_download/fetch_generation_entsoe.py

# 11. Optional, for validation only: ENTSO-E actual generation per generation
#     unit (A73), measured hourly output of each large unit (about 100 MW and up).
#     One request per day; January 2024 by default (--from/--to). Writes one file
#     per month to ../entsoe_download/generation_per_unit/<yyyy-mm>.csv. Unit names
#     are short codes (SAGU1 = Sagunto), so matching them to the model's plants
#     needs a hand-made table.
python3 entsoe_download/fetch_generation_per_unit.py --from 2024-01-01 --to 2024-12-31
```

All the `entsoe_download/*.py` scripts read `ENTSOE_TOKEN` from the
environment (never from a file) and cache raw API responses in the data
folder's `raw/` (`../entsoe_download/raw/`), so a rerun after an interruption doesn't re-hit the
API for days already fetched. `fetch_omie_technology.py` caches similarly in
`OMIE_data/tecnologias/` and needs no token at all.
