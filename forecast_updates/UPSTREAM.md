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
