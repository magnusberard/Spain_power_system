# Extending the 2024 case beyond the two validation days

**Finding.** `Data/ES_old/{load,Solar,Wind}` and `Data/crossborder.csv`
originally covered only the two hand-validated study days (8 July, 2
December 2024). The pipeline in `omie_conversion/` and `entsoe_download/`
reproduces those two days' data **exactly** from bulk-downloadable public
sources (OMIE + ENTSO-E), and extends coverage to every day from
**2024-07-01 to 2024-12-29** (182 days). `run_market_chain.jl`'s `TARGET_DAYS`
can cover that whole range, but is currently set to a narrower test window
(2024-08-01 to 2024-08-31) while it's validated month-by-month before running
the full 182 days in one go — see the "Rolling out beyond the two reference
days" note below.

This note records the formula, what was validated against what, and what is
still known-imperfect, so a future run knows exactly how much to trust each
piece.

## Why not all 366 days

- **2024-01-01 through 2024-06-30**: not attempted. `[bellman].bgn_date =
  "2024-07-02"` means no day before 2 July can run at all yet regardless of
  data quality (`bellman.jl` computes a negative stage index). Separately,
  the unit-technology mapping (below) also degrades sharply for dates far
  from the nearest snapshot, and the nearest ones we have are all mid-2024
  onward — so this range would need both the Bellman recalculation *and*
  more unit-list snapshots before it's worth generating. Retraining
  `midterm_sddp4.jl` with `bgn_date = "2024-01-01"` is being attempted on the
  `full_year_sddp` branch, kept separate from the validated `full_year`
  branch because retraining shifts which weekly SDDP stage every day
  (including the already-validated 182) reads its cuts from — the two
  reference days need to be re-checked against the new cuts before that
  branch's results are trusted for anything.
- **2024-12-30, 2024-12-31, 2024-01-01**: excluded on purpose.
  `Data/ES/{load,Solar,Wind Onshore}/` (the per-gate forecast-deviation
  factors) is missing exactly these 3 days, and the method used to generate
  them (a per-gate regression, see the paper's Section 2.5) has no
  reproducing script in this repo.

## Rolling out beyond the two reference days

All the per-day input data below is generated for the full 182-day range, but
`run_market_chain.jl`'s `TARGET_DAYS` is being rolled out gradually rather
than run all at once: 7 days first (15–21 September), then one full month
(August) as a wider check. Running August surfaced a real gap — the
nuclear/coal per-day calibration (below) had only ever been written for the
two original reference days, so every other day was silently falling back to
the flat annual default instead of its own computed availability, which
produced `LOCALLY_INFEASIBLE` hours on 2024-08-05. That has since been
backfilled for all 182 days by re-running
`add_nuclear_coal_calibration.py`; whether it fully explains that specific
day's infeasibility (vs. some other factor) hadn't yet been re-checked as of
this note.

## The reconstruction formula

Validated to an **exact match** (0.000 MW, every hour) against
`Data/OMIE/actual_generation_{July_8,Dec_2}.csv` for Wind and Solar, and to
within a small, fully-attributed residual for load (see "Known gaps"
below):

```
domestic = Coal + Nuclear + CCGT + Hydro + Wind + SolarThermal + SolarPV
           + Cogeneration/Waste/SmallHydro
load  = domestic + max(0, day-ahead scheduled FR→ES exchange)
                  + max(0, day-ahead scheduled PT→ES exchange)
wind  = Wind
solar = SolarThermal + SolarPV
```

`domestic`'s eight terms come from OMIE's **per-unit day-ahead schedule**
(`pdbf_YYYYMMDD.1`, OMIE's file-access category `pdbf`, bulk-downloadable as
one zip per month — `pdbf_YYYYMM.zip`), aggregated by unit code through a
unit → technology lookup (see below). This is the day-ahead **cleared
program**, not real-time settlement — confirmed by the exact match: a
day-ahead figure could not otherwise reproduce a "so-called actual"
reference file to the decimal across 192 data points.

The two import terms are ENTSO-E's **day-ahead scheduled commercial
exchange** (documentType `A09`, contract type `A01` — not documentType
`A11`, which is always real-time *actual* physical flow and does **not**
reproduce these columns; that was tried and ruled out first). Clamped at
zero because OMIE's own published import columns read zero during export
hours rather than going negative — the load series already has the export
netted out (see `method_export_relocation.md`).

## Unit → technology mapping

OMIE's "LISTADO DE UNIDADES OFERTANTES VIGENTES" (list of currently active
bidding units, code → technology) exists only as a **live, continuously
overwritten snapshot** — OMIE has no historical/dated version of this file,
in the file-access system or anywhere else on their site (checked directly,
including the Excel alternative). The only historical coverage available at
all is via the Wayback Machine, plus whatever dated copies a person happens
to have downloaded and kept.

`omie_conversion/unit_technology_map_merged.csv` merges every snapshot found
in `OMIE_data/` (outside this repo — see below):

- Close-to-2024 snapshots (24 Jun 2024, 12 Jul 2024, 10 Sep 2025) are merged
  first, oldest-of-those wins ties.
- Anything older (a 5 May 2022 snapshot) is used **only** to fill codes none
  of the close snapshots have at all, never to override them — a unit code
  can be **reused** for a completely different unit years later, so letting
  a distant snapshot win a tie silently corrupts an otherwise-correct
  classification. (Confirmed: including 2022 without this fallback-only rule
  broke the exact match on 8 July that held with just the close snapshots.)

Coverage is best near the snapshot dates and degrades with distance — for
example, unmapped-unit impact averaged 0 MW in June 2024 (the exact snapshot
date) vs. 1,900–4,300 MW/day in January 2024 (6 months before the nearest
close snapshot, and outside the usable range anyway per the Bellman
constraint above). Within the actually-generated range (Jul–Dec), the
worst single day was ~2,079 MW against a day around 600,000+ MWh — under
0.5%. More snapshots spread through the rest of the year, added to
`OMIE_data/` and re-merged, would tighten this further without any other
change.

## `crossborder.csv`

Extended the same way, using ENTSO-E's **actual** (not day-ahead) physical
flow data (documentType `A11` — the correct source for the AC redispatch,
which needs what really happened, not what was scheduled). The file format
changed the `Day` column from the old `"8_Jul"`/`"2_Dec"` labels to plain
ISO dates (`"2024-07-08"`), which scales to any number of days without a
growing label dictionary; `crossborder.jl` and
`plotting/exports_ramp_2024.py` were updated to match.

## Per-day calibration (`config.toml`)

- **`[da.nuclear_availability_by_date]` / `[da.coal_availability_by_date]`**:
  computed the same way the original two days were (peak OMIE-cleared MW ÷
  nameplate) — mechanical, no new data source, no known caveats.
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
    delivered** national Fossil Gas total. `pdbf` is strictly what cleared in
    the day-ahead auction; CCGT is the most flexible, most heavily
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
    the day-ahead/actual gap). `gas_mw` is therefore still **left unset** per
    day, which falls back to `[chp].gas_mw`'s global default (2,600 MW)
    rather than writing a value known to disagree with the two reference
    days. Revisit with whoever built the original calibration before
    deciding whether to apply the actual-CCGT-based re-derivation instead.

## Known gaps in `load`

Three of `load`'s thirteen OMIE technology components (Fuel-Gas,
Self-producer, Storage) are not modelled — on both reference days they were
~0 (a single 4.3 MW storage blip at one hour on 8 July was the only nonzero
occurrence), so they're assumed negligible everywhere. This hasn't been
checked on every day of the generated range; a day with genuine battery
activity or self-producer generation would be silently under-counted.

## Reproducing / extending this pipeline

Raw data lives in `OMIE_data/` and `entsoe_download/`, both **outside** this
repo (siblings of it) — they're too large to commit (hundreds of MB) and are
fully re-derivable from public sources, so only the small pipeline scripts
and their (small) output land in git.

```bash
# 1. OMIE per-unit day-ahead schedules (one zip per month, no login needed)
#    https://www.omie.es/en/file-download?parents=pdbf&filename=pdbf_YYYYMM.zip
#    unzip into OMIE_data/pdbf_YYYYMM/

# 2. Unit-technology snapshots (OMIE has no historical version of this file --
#    Wayback Machine captures, or any dated copy someone happens to have, into
#    OMIE_data/LISTA_UNIDADES*.pdf, parsed with:
python3 omie_conversion/parse_unit_list.py <pdf> OMIE_data/unit_technology_map_<date>.csv
python3 omie_conversion/build_unit_map.py          # merges all snapshots found

# 3. ENTSO-E day-ahead exchange (needs ENTSOE_TOKEN) -- for the load formula
python3 entsoe_download/fetch_da_exchange_year.py

# 4. ENTSO-E actual physical flows -- for crossborder.csv
python3 entsoe_download/fetch_crossborder_year.py
python3 omie_conversion/build_crossborder_csv.py --from-date 2024-07-01 --to-date 2024-12-29

# 5. ENTSO-E generation by fuel type -- for the CHP calibration
python3 entsoe_download/fetch_chp_entsoe_year.py

# 6. Validate against the two reference days before trusting any of the above
python3 omie_conversion/convert_omie_to_model_data.py --validate

# 7. Write Data/ES_old/{load,Solar,Wind}/
python3 omie_conversion/convert_omie_to_model_data.py --all --from-date 2024-07-01 --to-date 2024-12-29

# 8. Per-day config.toml calibration
python3 omie_conversion/add_nuclear_coal_calibration.py --from-date 2024-07-01 --to-date 2024-12-29
python3 omie_conversion/add_chp_calibration.py --from-date 2024-07-01 --to-date 2024-12-29
```

All the `entsoe_download/*.py` scripts read `ENTSOE_TOKEN` from the
environment (never from a file) and cache raw API responses in
`entsoe_download/raw/`, so a rerun after an interruption doesn't re-hit the
API for days already fetched.
