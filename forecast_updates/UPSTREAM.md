# Upstream: entsoe-forecasting

This folder is a vendored copy of Wouter Koks' **entsoe-forecasting**
(https://github.com/WouterKoksNL/entsoe-forecasting, MIT licence, see
`LICENSE`), the code that produces the per-gate forecast updates in
`Data/ES/{load,Solar,Wind Onshore}/` (Spanish model paper, §3.5; Koks et
al.).

- **Upstream commit:** `6337e39` ("bulk commit", 2026-07-03), the latest on
  `main` when copied (2026-10-02). It is the only version that contains the
  Spanish post-processing step (`scripts/spain/omie_post_process.py`).
- **Copied verbatim**, byte-identical to that commit, except: the
  `analysis.ipynb` notebook and upstream's `.gitignore` / `.gitattributes`
  are left out.
- **Local changes** are made in separate commits on top of the verbatim
  copy, so `git log -p -- forecast_updates/` shows exactly what was adapted
  for this repo and why. Each changed line is marked `[Spain_power_system]`.

The upstream code at this commit is in a debugging state for the Spanish
case (it writes gate forecasts only for 2024-07-08 and 2024-12-02, and stops
at `breakpoint()` calls when processing solar and in `scripts/spain/make_fc.py`),
so it does not regenerate a full year as published.

## Local changes (all marked `[Spain_power_system]`)

| File | Change | Why |
|---|---|---|
| `main.py` | removed the 2024-07-08 / 2024-12-02 date filter and a `breakpoint()` in the gate loop | debugging leftovers; every requested day is written again |
| `src/load_saved_data.py`, `scripts/spain/make_fc.py` | removed `breakpoint()` calls | debugging leftovers |
| `src/algorithms/get_algorithm.py`, `src/forecasting.py` | TensorFlow models (LSTM, LINEAR_NN) imported only when selected; an unused import dropped | the LINEAR model needs no TensorFlow, which does not install on recent Python |
| `src/utils.py` | token read from `ENTSOE_TOKEN` first | same variable as `entsoe_download/`; no token in files |
| `src/load_config.py` | `configs/` resolved next to the package | `run_spain.py` runs from a work folder outside the repo |
| `src/post_process.py` | `load_omie_data` reads `OMIE_TECH_DIR/tecnologias_YYYYMMDD.txt` (latin-1) | the OMIE technology report `omie_conversion/` already caches; same layout |
| `run_spain.py` (new) | `download` / `train` / `gates` / `normalize` with dates on the command line | replaces the hard-coded `scripts/spain/*.py` drivers; forecasting logic unchanged |

Python packages: `pandas numpy scikit-learn scipy matplotlib seaborn
entsoe-py pyyaml python-dotenv` (TensorFlow and statsmodels are not needed).

## Upstream behaviour to know about (unchanged here)

- **Window edges.** `gates` picks a gate's forecast only if the gate time lies
  inside `--from`..`--to`. The first day's DA gate (12:00 the day before) and
  the last day's ID3 gate (10:00 that day) lie outside, so both edge days are
  skipped with a `KeyError` message. Upstream's 2024-01-01..2024-12-30 window
  therefore yields 2024-01-02..2024-12-29: exactly the 363 days in `Data/ES`.
- **Clock-change days.** A gate file always has 24 rows from local midnight,
  so on 2024-03-31 it runs into 00:00 of the next day, and the solar step of
  `normalize` fails against OMIE's 23-hour report.
- **Time zone of the existing `Data/ES` files.** 361 of the 363 days are
  indexed in UTC (`+00:00`); only 2024-07-08 and 2024-12-02 are in Spanish
  local time. The market chain reads the 24 rows positionally as local hours,
  so on those 361 days the factors sit 1 h (winter) / 2 h (summer) early.
