# Extending the 2024 case beyond the two validation days

**Finding.** `Data/ES_old/{load,Solar,Wind}` and `Data/crossborder.csv`
originally covered only the two hand-validated study days (8 July, 2
December 2024). The pipeline in `omie_conversion/` and `entsoe_download/`
reproduces those two days' data **exactly** from bulk-downloadable public
sources (OMIE + ENTSO-E), and extends coverage to every day from
**2024-01-03 to 2024-12-29** (363 days — all of 2024 except 4 excluded days,
see "Why not all 366 days"). `run_market_chain.jl`'s `TARGET_DAYS` can cover
that whole range, but is currently set to a narrower test window
(2024-04-08 to 2024-04-14) while it's rolled out gradually and checked at
each step — see "Rolling out beyond the two reference days" below.

This note records the formula, what was validated against what, and what is
still known-imperfect, so a future run knows exactly how much to trust each
piece.

## Why not all 366 days

- **2024-01-01 and 2024-01-02**: excluded because `[bellman].bgn_date` (the
  start of the mid-term hydro model's 78-week horizon) is `2024-01-03`, not
  `2024-01-01`. It isn't 1 January either, because of two separate one-day
  data gaps right at the start of the year: `Data/MIBGAS_Data_2024.csv`'s
  earliest usable gas-price delivery day is 2 January (its first trading
  day, 1 Jan, prices *delivery* on 2 Jan under the D+1 convention), and
  `Data/Carbon Emissions Price.csv`'s earliest EUA settlement is also
  2 January (carbon markets don't trade on New Year's Day). Since
  `gas_srmc(d)` needs the carbon price for `d − 1`, the first day that has
  both a gas price *and* a carbon price for the day before it is 3 January.
- **2024-12-30, 2024-12-31**: excluded on purpose. `Data/ES/{load,Solar,Wind
  Onshore}/` (the per-gate forecast-deviation factors) is missing exactly
  these days (plus 1 Jan), and the method used to generate them (a per-gate
  regression, see the paper's Section 2.5) has no reproducing script in this
  repo.
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
  result against the two reference days.
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
  new data source, no known caveats. Backfilled for all 363 days;
  `add_nuclear_coal_calibration.py` gained a `--force` flag to recompute and
  replace already-present dates (needed for the reconstruction-method
  switch, since this was a redo, not a gap-fill) — the two original
  hand-derived reference days are hard-coded as protected and are never
  touched by `--force`.
- **`[chp.by_date]`**: three-way split derived from ENTSO-E generation by
  fuel type minus the OMIE-cleared equivalent (see the `[chp]` comments in
  `config.toml` for the full derivation).
  - `waste_mw` and `minihydro_mw` reproduce both reference days almost
    exactly (within ~1%) and are computed per-day for the full range.
  - `gas_mw` does **not** reproduce — it comes out consistently ~1.8–2.4×
    higher than the reference days' hand-derived values (e.g. 8 July:
    4,015 MW computed vs. 2,260 MW documented). Both inputs to that
    calculation check out independently against other known-correct figures
    (ENTSO-E Fossil Gas confirmed twice via two different fetch methods;
    OMIE CCGT matches an already-documented reference value), so the gap is
    in the *method*, not in this reproduction.

    **Likely cause, identified but not yet fully resolved:** the formula nets
    OMIE's **day-ahead cleared** CCGT output against ENTSO-E's **actual
    delivered** national Fossil Gas total. Both are still day-ahead numbers
    regardless of which reconstruction method reads them (see above), so
    switching to the technology report changed nothing about this
    discrepancy. CCGT is the most flexible, most heavily
    intraday/balancing/redispatch-adjusted technology on the system, so the
    two can diverge by a large, day-dependent margin. Checked directly via
    ENTSO-E's per-generation-unit report (documentType `A73`) for the named
    CCGT plants on both reference days:

    | | OMIE day-ahead CCGT | ENTSO-E actual CCGT (named units) |
    |---|---|---|
    | 8 July | 0.39 GWh | 57.59 GWh |
    | 2 Dec | 123.05 GWh | 244.51 GWh |

    Re-deriving `gas_mw` against the *actual* CCGT total instead of the
    day-ahead one brings both days to a consistent ~70% of the reference
    value (1,632 MW / 1,993 MW vs. 2,260 MW / 2,920 MW) — a much steadier
    ratio than the original 1.8–2.4×, though not an exact match, likely
    because ENTSO-E's per-unit report only lists units above a size
    threshold and so still undercounts true actual CCGT output. Ruled out
    along the way: a unit-technology misclassification (every named plant
    that *is* in the unit map is correctly tagged `Ciclo Combinado`) and an
    OMIE-visible-cogeneration double-count (real, but a smaller effect than
    the day-ahead/actual gap).

    Explored further, not yet built: whether OMIE's own **intraday** market
    results (a session-based technology breakdown, analogous to the
    day-ahead report above) could narrow this further, since intraday
    trading is OMIE's own data rather than needing to lean on ENTSO-E's
    actual-generation numbers. A likely report code wasn't found (a few
    guesses by analogy to the day-ahead pattern all 404'd, and OMIE's own
    file-access listing doesn't show an obvious match either), and Spain's
    intraday market restructured around the EU's Single Intraday Coupling
    (SIDC) in June 2024 — before which local numbered auction sessions
    dominated, after which continuous trading took over a lot of that
    volume — which is *after* both reference days, so a session-based
    report might only capture part of the picture for them even if found.
    Parked, not pursued further as of this note.

    `gas_mw` is therefore still **left unset** per day, which falls back to
    `[chp].gas_mw`'s global default (2,600 MW) rather than writing a value
    known to disagree with the two reference days. Revisit with whoever
    built the original calibration before deciding whether to apply the
    actual-CCGT-based re-derivation instead.

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
and their (small) output land in git.

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

# 8. Retrain the mid-term SDDP model to cover the new range
#    (edit [bellman].bgn_date in config.toml first)
julia --project=. midterm_sddp4.jl
```

All the `entsoe_download/*.py` scripts read `ENTSOE_TOKEN` from the
environment (never from a file) and cache raw API responses in
`entsoe_download/raw/`, so a rerun after an interruption doesn't re-hit the
API for days already fetched. `fetch_omie_technology.py` caches similarly in
`OMIE_data/tecnologias/` and needs no token at all.
