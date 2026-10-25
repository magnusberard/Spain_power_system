# Redispatch realism (RD1–RD11)

Make the redispatch stage resolve technical constraints the way REE does (P.O. 3.2) and
settle them the way REE settles them (P.O. 14.4), so the model can say how much redispatch
cost a flexible asset such as Soto de Ribera would save. Plan and evidence:
<https://claude.ai/artifact/D4d82mY8p93qBQh4Rt2vef> (vault: `redispatch-model-vs-ree`).

None of this changes the day-ahead or intraday prices: the redispatch still runs after the
market stages, as REE's does after OMIE. Every switch is off by default, so existing runs
reproduce unchanged.

Built in checkpoints, each reviewed before the next:

| Checkpoint | Steps | What | Status |
|---|---|---|---|
| 1 | RD1, RD2 | settle the redispatch like REE; take the losses out of the load | built, checks pass |
| 2 | RD3, RD4 | reactive power only from running units; 2024 rules for wind/solar reactive power | built, checks pass |
| 3 | RD8, RD9, RD5 | phase I/II stage on the day-ahead schedule: daily unit commitment, must-run by voltage area | built; RD8 also inside the market chain (`[redispatch.phase1].in_chain`, 21 Oct, being tested) |
| 4 | RD10, RD11 | REE's objective, pay-as-bid mark-ups; storage at opportunity cost | built |
| 5 | RD6, RD7 | N-1 on critical corridors; upward reserve in real time | built; RD6 off (too strict with one rating), RD6b seasonal post-outage limits added 21 Oct (being tested) |

Measured against REE with `compare_ree.py` (volume, cost, phase I/II apart, price per MWh, REE's phase I
by cause, hour-of-day shape with `--profile-out`, voltage zones with `--zones`).

## Running a month or the year on Solstorm

The realism redispatch costs 20–30 min per day per process (locally, MUMPS). Days are independent
(standalone redispatch, `from_saved = "BAL"`), so on Solstorm they run in parallel lanes and reuse
the market results of an existing run — no market stage is re-run. Node rules for master
students (vault `solstorm-cluster`): `compute-5-*` only (20 cores, 96 GB), at most 5 nodes, never
a busy node. Estimates with MA57: one month ≈ 30 min on one node (12 lanes); the year ≈ 2 h on 5 nodes.

1. **Log in** (off campus: NTNU VPN first), then go to a free compute node:
   ```
   ssh <user>@solstorm-login.iot.ntnu.no
   ssh compute-5-<n>          # check it is free first: uptime   (load well below 20)
   ```
2. **Code** (once; later only the `git pull`):
   ```
   cd /storage/users/$USER
   git clone https://github.com/magnusberard/Spain_power_system.git   # skip if you have it
   cd Spain_power_system && git fetch && git checkout redispatch-realism && git pull
   source scripts/solstorm_env.sh ma57
   julia --project=. -e 'import Pkg; Pkg.instantiate(); Pkg.precompile()'
   ```
3. **HSL for MA57** (once): copy your licensed HSL_jll folder to the cluster (from the PC,
   PowerShell: `scp -r C:\Users\magnu\HSL_jll.jl.v2026.8.4 <user>@solstorm-login.iot.ntnu.no:/storage/users/<user>/`),
   then on the node:
   ```
   julia --project=. -e 'import Pkg; Pkg.develop(path="/storage/users/'$USER'/HSL_jll.jl.v2026.8.4/HSL_jll.jl.v2026.8.4")'
   ```
   (Do not commit the changed Manifest.toml. Without HSL, use `IPOPT=mumps`, ~1.5× slower.)
4. **Source run**: a split-run folder of Lars Erik's full-year run (it has `chunks.txt` and
   `FROM_TO/` chunk folders with `bal_dispatch.csv`, `da_dispatch.csv`, `market_prices.csv`):
   ```
   SRC=/storage/users/<lars-erik>/results/<run>      # ask him which; check: head $SRC/chunks.txt
   ```
5. **One month first** (December, one node):
   ```
   FROM=2024-12-01 TO=2024-12-29 IPOPT=ma57 \
     redispatch_realism/solstorm_start_realism.sh $SRC /storage/users/$USER/results/realism_dec 1/1
   tail -n 3 /storage/users/$USER/results/realism_dec/lane-*.log          # progress
   ls /storage/users/$USER/results/realism_dec/*/summary.csv | wc -l     # finished days
   ```
6. **The year** (only after the month checks out): on up to 5 free nodes, one command each,
   `1/5` … `5/5` (FROM/TO default to 2024-01-01 … 2024-12-29):
   ```
   IPOPT=ma57 redispatch_realism/solstorm_start_realism.sh $SRC /storage/users/$USER/results/realism_2024 1/5
   ```
7. **Check against REE on the cluster** (the raw results stay there). Copy the reference data
   once from the PC (PowerShell):
   ```
   scp C:\Users\magnu\dev\spain-model-runs\reference\esios_2024.js <user>@solstorm-login.iot.ntnu.no:/storage/users/<user>/ref/
   scp -r C:\Users\magnu\dev\esios_download\i90 <user>@solstorm-login.iot.ntnu.no:/storage/users/<user>/ref/
   ```
   then on a node:
   ```
   module load Python/3.11.5-GCCcore-13.2.0
   python3 redispatch_realism/compare_ree.py /storage/users/$USER/results/realism_dec \
     --bids redispatch_realism/bids_fitted.csv --storage-at-da \
     --esios /storage/users/$USER/ref/esios_2024.js --i90 /storage/users/$USER/ref/i90 \
     --out /storage/users/$USER/results/realism_dec/vs_ree.csv
   ```
   and copy `vs_ree.csv` back (`scp <user>@solstorm-login.iot.ntnu.no:/storage/users/<user>/results/realism_dec/vs_ree.csv .`).
   `python3 scripts/merge_runs.py <merged> <out>` joins the days into one folder if needed.

Locally the same lanes run with `LANES=2` (memory: ~3 GB per lane on 16 GB).

## Checks: is each component working?

`check.py` prints PASS/FAIL per test and exits non-zero on a failure. Three kinds:

- **logic**: no model run, synthetic inputs with known answers (seconds).
  `python redispatch_realism/check.py logic`
- **same A B**: with every new switch off, the branch gives the same redispatch as `main`
  (same solved hours, every unit within 0.5 MW). Run once per checkpoint on one week.
- **rdN A B**: A = switch off, B = switch on, same days; tests what the component must change
  and that no hour that solved in A fails in B.

How close the result is to REE is reported, not pass/fail: `settle.py --esios`.

| Component | logic (no run) | on = does its job (A off, B on) |
|---|---|---|
| RD1 settle | 8 tests: up/down, border and pseudo-units out, both cost formulas, mark-ups, the marginal = EC + p_DA·net identity | — |
| RD2 loss_share | — | load scaled by one constant; net up (up − down) < 25 % of A's; less up; AC losses about unchanged |
| RD3 Q only when running | network builder: a unit below Pmin gets qmin = qmax = 0 | no unit below 5 % of capacity has \|Q\| > 1 Mvar; hours that become infeasible are listed with their buses |
| RD4 RES power factor | — | wind/solar \|Q\| ≤ tan(acos(pf))·P in every hour |
| RD9 unit commitment | tiny 3-unit case with a known optimum | no unit between 0 and its minimum load; starts respect min up/down times |
| RD5 must-run by area | — | every area/hour meets its requirement; voltage-cause up appears at the listed nodes |
| RD8 phase I/II stage | — | phase II takes back phase I's added energy (net ≈ 0 per hour); DA price file byte-identical |
| RD10 objective, bids | objective value equals settle.py's extra cost on the same schedule | €/MWh up rises toward the fitted mark-up |
| RD11 storage cost | — | pumped storage within its daily energy band; up from pumped storage falls |
| RD6 N-1 | 3-bus case: a contingency forces a known redispatch | no listed contingency overloads a line above its rating |
| RD7 reserve | — | online upward headroom ≥ requirement in every real-time hour |

## Checkpoint 1

**RD1 — `settle.py`** (new, Python only). Reads a finished run and reports energy up/down per
unit against the anchor schedule, the AC grid losses, and the cost two ways: the extra cost REE's
way (against the day-ahead price) and the marginal valuation the viewer shows today. With
`--esios` it prints REE's phases I, II and real time over the same hours.

```
python redispatch_realism/settle.py results/<run> --esios ../spain-model-runs/reference/esios_2024.js
```

December 2024 (`results/2024_by_month/2024-12`, 696 solved hours, no mark-ups):

| | Up GWh | Down GWh | Extra cost M€ |
|---|---|---|---|
| Model (single stage on BAL) | 366.1 | 172.9 | −23.2 (marginal valuation −8.7) |
| of which grid losses | 193.3 | | |
| REE phase I | 805.5 | 151.1 | 136.7 |
| REE phase II | 14.3 | 668.8 | −57.0 |
| REE real time | 390.4 | 61.1 | 118.6 |

Up − down equals the losses (193.2 vs 193.3 GWh), and marginal − extra cost equals the losses
at the day-ahead price, so the two cost measures reconcile. The extra cost is negative mainly
because pumped storage is turned up at ~0 €/MWh against a ~75 €/MWh day-ahead price (RD11).

**RD2 — `[redispatch].loss_share`** (hook in `run_market_chain.jl`, two call sites, plus
`config.toml`). OMIE demand is bought at busbars with the losses in it (Orden ITC/3353/2010), so
the AC load flow counted them twice. The redispatch load is scaled by `1 − loss_share`; the market
stages are untouched. December's own share is 0.0101. Test once the machine is free:

```
# run from a checkout of this branch; R = the results folder that holds the December run
R=/c/Users/magnu/dev/Spain_power_system/results
# A and B: two copies of the December run (the standalone load flow rewrites the redispatch outputs in place)
cp -r $R/2024_by_month/2024-12 $R/rd2_A; cp -r $R/2024_by_month/2024-12 $R/rd2_B
# two copies of this branch's config.toml, both with [redispatch] from_saved = "BAL";
# A keeps loss_share = 0.0, B sets loss_share = 0.0101
SPAIN_DAYS=2024-12-02:2024-12-08 SPAIN_CONFIG=$R/rd2_A/config_A.toml SPAIN_RESULTS=$R/rd2_A julia --project run_market_chain.jl
SPAIN_DAYS=2024-12-02:2024-12-08 SPAIN_CONFIG=$R/rd2_B/config_B.toml SPAIN_RESULTS=$R/rd2_B julia --project run_market_chain.jl
python redispatch_realism/check.py rd2 $R/rd2_A $R/rd2_B     # pass/fail
python redispatch_realism/settle.py $R/rd2_B --esios ../spain-model-runs/reference/esios_2024.js
```

`from_saved = "BAL"` reuses the saved market schedule, so only the AC stage reruns (one week,
168 AC hours). What to look at in B against A: up − down drops from ≈ the losses to ≈ 0, pumped
storage up falls, and every hour that solved in A still solves in B.

### Check results, 2–4 Dec 2024 (72 AC hours, from December's saved BAL schedule)

| Check | Result |
|---|---|
| `same main A` (branch, all switches off, vs main adc81f4) | PASS 3/3, largest difference 0.000 MW |
| `rd2 A B2` (loss_share 0.0101) | PASS 5/5: load × 0.9899 exactly; net up 16.5 → −1.5 GWh; up 39.0 → 28.0 GWh; AC losses 16.5 → 16.7 GWh. Failed hours 3 → 3, but different ones (4 Dec h04/06/07 fixed, h09/19/21 newly failed): Ipopt is a local solver, so the rule is "B fails no more hours than A" |

## Checkpoint 2

**RD3 — `[redispatch].q_requires_online`** (hook in `data_preparation.jl`, passed by the two
redispatch calls). A synchronous unit the anchor leaves below 1 % of installed gives no reactive
power; load shedding gives reactive power only in proportion to the load it sheds. Before, in
December 2024, load-shedding units supplied half of all reactive power while shedding 81 MWh.
`test_rd3.jl`: 15/15 PASS on the network builder.

**RD4 — `renewable_power_factor = 1.0` for 2024** (config note only; the knob already existed).

Run checks, same 72 hours:

| Check | Result |
|---|---|
| `rd3 A B3` | idle units give no reactive power PASS (189 idle units, max 0.00 Mvar); load shedding proportional PASS; **failed hours 3 → 22 FAIL** |
| `rd4 A B34` | wind/solar \|Q\| ≤ 0 · P PASS (1,761 → 0 Mvar); with RD3 too, failed hours 3 → 24 |

Against REE over the same solved hours (`settle.py --esios`):

| | A (today) | B3 (RD3) | B34 (RD3+RD4) | REE, same hours (B34's 48) |
|---|---|---|---|---|
| Up, GWh | 40.3 (69 h) | 108.3 (50 h) | 237.4 (48 h) | 91.0 |
| Extra cost, M€ | −3.67 | +0.52 | +10.33 | 20.53 |
| Gas up / wind+solar down, GWh | 1.8 / 0.2 | | 101.2 / 143.2 | phase I mostly gas and coal up; phase II renewables down |

With RD3+RD4 the model's redispatch takes REE's shape — gas up, renewables down — but 2.6×
REE's volume: with no free reactive power and no start-ups, it holds voltage by shifting energy
among the running units. RD9 (start-ups at minimum load) is meant to replace part of that.

### RD9 voltage start-ups, 2 Dec 2024 (24 AC hours)

| Check | B9 (RD3 + RD9) vs B3 | B49 (RD3 + RD4 + RD9) vs B34 |
|---|---|---|
| fewer failed hours | PASS 7 → 4 | PASS 7 → 2 |
| started units at ≥ minimum load | PASS (24 starts in solved hours) | PASS (40) |
| started units give reactive power | PASS (100 %) | PASS (100 %) |

All start-ups are 00–06 h, all to absorb a reactive surplus (−128 to −302 Mvar), all CCGTs —
REE's night pattern. But **none is a unit REE started**: on 2 Dec 00–06 h REE ran 13 CCGTs in
phase I (12.3 per hour, all coded SOT) spread over Spain — Port of Barcelona, Cartagena 1 and 3,
Málaga, Besòs 3 and 5, Sagunto, As Pontes, Sabón, Aceca 4, Castellón, San Roque 2 and Soto de
Ribera 5 — while the model started 8 per hour (the max_rounds cap) all in south-west Andalucía
(Palos ×3, La Rábida ×2, Arcos ×2, Villarrubia): each round starts a unit next to the largest
surplus, which in our grid is always there. REE's start-ups look like a requirement per voltage
area, which an AC snapshot of our approximate grid does not reproduce. Next: RD5, a must-run per
area calibrated on I90, with RD9 kept as the physics fallback.

### RD10/RD11 REE's cost rule, 2 Dec 2024

C10 = B49 (RD3+RD4+RD9) + `objective = "ree"` with fitted mark-ups (CCGT 0.89, coal 0.94);
CALL = C10 + RD2. Settled with the same rule (`settle.py --bids … --down-refund da --storage-at-da`).

| | B49 | C10 | CALL | REE, same hours |
|---|---|---|---|---|
| solved hours | 22/24 | 24/24 | 23/24 | |
| up, GWh | 119 | 125 | 108 | 39 |
| extra cost, M€ | | 2.61 | 1.65 | 8.30 |
| up by type, GWh | gas 52, hydro 33, pumped 32 | gas 11, hydro 61, pumped 52 | gas 5, hydro 58, pumped 45 | almost all CCGT/coal |

The cost rule helps the AC solves (all 24 hours), but hydro, pumped storage and wind priced at
exactly p_DA up and down can be swapped for free (only the 0.5 €/MWh tie-break), so the model
holds voltage with large near-free hydro/pumped/wind moves instead of REE's few paid gas starts:
3× REE's volume at a third of its cost. Next: calibrate `[redispatch.bids]` — REE paid pumped
storage 1.59 × p_DA in phase I in 2024 (I90), i.e. an up mark-up ≈ 0.6, and test a larger
tie-break (REE's least-energy rule).

### RD5 must-run by voltage zone, 2 Dec 2024 (Z5 = CALL + RD5)

2024 zones from I90 (`build_voltage_zones.py`): 17 zones, 85 member units; a zone needed voltage
action in 8,463 of 8,784 hours (Cartagena 82 %, Bahía de Bizkaia 75 %, Soto de Ribera 23 %).

Z5 solved 23/24 hours; 61 zone start-ups plus 36 from the RD9 loop. The start-ups are now in
REE's zones (Cartagena, Barcelona, Málaga, Sabón, Sagunto, San Roque, Aceca) instead of only
south-west Andalucía, and 3 units match REE's (Málaga, Sabón 3, Sagunto). Extra cost 4.20 M€
(REE 8.16, same hours), up 114 GWh (REE 37.5). Within a zone the model started the cheapest
members, mostly small industrial plants `generations.csv` lists as combined cycles (Martorell
Seat, Barcelona Cartonboard, Cartagena and Castellón refineries); REE starts the large CCGTs.
Fixed afterwards: `[redispatch.startups].candidate_min_mw = 100` (the day-ahead unit commitment's
threshold) removes 19 such units from the 70 zone CCGT/coal members.

### RD8, RD7 and everything on, 2 Dec 2024

All exit 0. Settled like the model (`--bids`, `--down-refund da`, `--storage-at-da`).

| | P8 (CALL + RD8) | R7 (CALL + RD7) | FULL (CALL + RD8 + RD5 + RD7) | REE |
|---|---|---|---|---|
| phase I (DC, day-ahead) | optimal, **nothing to do** | — | optimal: 9 units committed (one start each), 6.7 GWh up, 1.05 M€ | 20.1 GWh, 5.8 units/h, 224 €/MWh |
| real-time AC: solved hours | — | 24/24 | 23/24 | |
| real-time AC: up, GWh | — | 90.3 | 90.0 | |
| extra cost, M€ | — | 6.11 | 5.16 + 1.05 (phase I) = 6.2 | 8.15–8.30 |
| reserve met every solved hour | — | yes | yes | |

P8: on the DC model of the day-ahead schedule there is nothing to fix — no overloads, and DC has
no voltage — consistent with REE's base-case overloads being 0.25 % of phase I. With the zones
(FULL), phase I commits units once for the day, 3 of them REE's (Sagunto, Sabón 3, Málaga); the
other committed units include the small industrial plants excluded since by `candidate_min_mw`.
FULL reaches about three quarters of REE's cost, but still 2.5× its volume, mostly hydro, pumped
storage and wind moves in the AC stage (next: storage mark-up ≈ 0.6 and a larger tie-break).
To check: RD7 started 2 units in most hours although the running providers' headroom in the
solution (3.5–13 GW) far exceeds the requirement (1.0–1.6 GW) — the pre-solve count is stricter.

### Calibration run CAL, 2 Dec 2024

CAL = FULL + storage up mark-up 0.59 (REE paid pumped storage 1.59 × p_DA in phase I, 2024),
tie-break 5 €/MWh (was 0.5), `candidate_min_mw = 100`, RD7 `offline_hydro_counts = true`.

| | FULL | CAL | REE, same 21 hours |
|---|---|---|---|
| solved hours | 23/24 | 21/24 (h01, h02, h04 fail) | |
| up: real time + phase I, GWh | 90 + 6.7 | 85.5 + 11.5 | 33.7 |
| extra cost, M€ | 5.2 + 1.05 | 8.5 + 1.8 = 10.3 | 7.85 |
| real-time starts zone / RD9 / reserve | 8 / 33 / 21 | 8 / 35 / 0 | |
| phase I units (REE's) | 9 (3), incl. industrial plants | 9 large CCGTs (5: Sagunto, El Fangal, Sabón 3, Málaga, Besòs 3) | 16 |

Phase I now picks REE's plants, RD7 no longer forces thermal starts, and the cost is REE's size
(30 % above, but through hydro/pumped storage at 1.59 × p_DA rather than gas). The volume did not
fall: mark-ups and the tie-break change what the moves cost, not how many the AC model needs —
they are voltage-driven. Suspect: `[network].gen_bus_vmin/vmax = 0.98/1.03` pu, much tighter than
REE's operating range (~0.95–1.05 pu at 400 kV); next test is a single config change.

### Week 2–8 Dec 2024, everything on (W1c/W2c, with the phase I anchor fix)

All 168 hours solve. Model / REE: volume 158 %, cost 86 % (46.6 vs 54.0 M€), phase I volume 86 %
(183 vs 214 GWh), phase I units 6.0 vs 7.9 per hour, weekend rise reproduced. Real time matches
REE on 2–3 Dec (little phase I) but is 45–59 GWh/day against REE's 1–19 on 4–8 Dec: pumped storage
up 22–42 GWh and solar/wind down 25–30 GWh per day. Cause: phase I's changes are computed against
the day-ahead schedule but added to the saved balancing schedule, which the intraday markets have
re-traded — they do not fit unit by unit and the real-time stage undoes the mismatch. In Spain
phase I precedes the intraday markets, so their schedules include it. Clean fix: phase I inside the
market chain between DA and ID2 (needs the market stages to run; may move intraday prices — the
open design decision). Until then, phase I results are valid; real time is valid on low-phase-I days.

### Phase I inside the market chain, 2–8 Dec 2024 (21 Oct)

`[redispatch.phase1].in_chain = true` (off by default; `make_config.jl --in-chain`): phase I runs after
each day's DA; ID2–BAL start from DA + phase I's changes (PDVP) and keep its started units on at
minimum load (UC_COMMIT; also without gas unit commitment); the real-time stage then starts from BAL
unchanged. Hooks in `run_market_chain.jl`: the switch, one call after the DA, `uc_bounds_for` also with
UC off, and `add_xb_group_constraints!` / `rd_is_market_unit` moved unchanged above the market loop.

Full chain, both runs with the December run's market settings and every realism switch (CH0: phase I
after the markets, CH1: inside the chain; band 0.975–1.05). CH0 reproduces the saved December run
exactly (DA, ID2, BAL schedules 0.00 MW, every price).

| 2–8 Dec 2024 | W1c/W2c (after, band 0.95–1.05) | CH3 (in chain, 0.95–1.05) | CH0 (after, 0.975–1.05) | CH1 (in chain, 0.975–1.05) | REE |
|---|---|---|---|---|---|
| extra cost | 46.6 M€ | 53.3 M€ | 55.3 M€ | 63.6 M€ | 54.0 M€ |
| phase I up / cost | 183.3 GWh / 37.3 M€ | 183.3 / 37.3 | 183.3 / 37.3 | 183.3 / 37.3 | 214.4 GWh / 38.2 M€ (+ phase II −12.3) |
| real-time up / cost | 292 GWh / 9.2 M€ | **282 / 16.0** | 577 / 18.0 | **536 / 26.3** | 87 GWh / 28.1 M€ |
| € per MWh up | 98 | 115 | 73 | 88 | 179 |
| real-time hour-of-day correlation with REE | −0.01 | −0.04 | −0.06 | −0.13 | |

(Corrected 21 Oct: the first version of this table showed CH1's real time as 716 GWh. `settle.py` added
phase I's changes to the balancing schedule also for in-chain runs, where it already holds them, so
phase I was counted twice; it now reads `in_chain` from the run's `config_used.toml`.)

- DA unchanged in CH1 (0.00 MW). Intraday prices fall: ID2 −5.4 €/MWh on average (max −25), ID3 −3.4,
  CID −2.1, BAL −1.7 (phase I's started units bring must-run energy into those gates).
- **In the chain, real time falls a little** (−3 % at 0.95, −7 % at 0.975), no longer turns wind and solar
  up (54 → 0 GWh: that was the mismatch), and the price per MWh moves toward REE's. But the phase I/BAL
  mismatch is not the main driver of the overshoot. Real time swaps wind and solar down (170–330 GWh) for
  pumped storage and hydro up (250–500 GWh) at midday, in every variant; REE's real time that week was
  almost only combined cycles turned up (I90DIA08: 85 GWh; pumped storage 0).
- **The generator-bus lower voltage limit is the largest driver:** W1c/W2c and CH0 differ only in
  `gen_bus_vmin` (0.95 vs 0.975), and real time doubles. In CH0, 24 % of generator bus-hours sit at the
  0.975 limit, mostly at 220 kV buses, where REE's own lower limit is 205 kV = 0.93 pu (P.O. 1.4).
  Next: a band per voltage level (vault issue `generator-voltage-band`, option C), and CH3 = CH1 with
  0.95 to see the in-chain step on its own.

### Real time by cause, and the reactive-power audit (22 Oct)

**Validate by cause, not by total.** REE's real-time up that week by cause (e·sios): too little upward
reserve 83.3 GWh (96 %), N-1 3.1, **voltage 0.3**. `compare_ree.py --relaxed <run with voltage limits
0.90–1.10>` splits the model's real time into voltage-driven (run − relaxed) and other. VL1 vs VLX:
voltage-driven 310 GWh vs REE's 0.3, other 29 vs REE's 86.5. VL3 vs VL3X (VL3 with limits 0.90–1.10,
167/168 hours): voltage-driven 55 GWh, other 26. So VL3's total of 81 GWh matching REE's 87
is a coincidence of totals: the model's real time is voltage redispatch, REE's is reserve. In VL3,
400 kV generator buses still sit at the **lower** limit in 13 % of hours (most at 22–23 h); REE's 2024
problem is **overvoltage** in off-peak and shoulder hours. The model's reactive-power balance is biased
toward shortage.

**Audit of the reactive-power assumptions** against independent sources (not against the 2024 redispatch):

| Item | Model | Rule or evidence | Verdict | Direction |
|---|---|---|---|---|
| Wind/solar reactive power | RD4: power factor 1.0; VL3: free within ±0.98 | RD 413/2014 art. 7 e) i) and Annex III: range 0.98 inductive to 0.98 capacitive, set yearly by resolution (BOE consolidated text, 2026; 2024 version to confirm). REE 2024: "rangos fijos de factor de potencia" | 1.0 wrong; ±0.98 is the legal range (in practice a fixed setpoint within it) | 1.0 made the shortage |
| Renewables' connection networks | not modelled | REE 2024 voltage report: they generate reactive power "de un orden de magnitud de miles de Mvar", uncompensated, causing overvoltage at low renewable output | missing | a missing source of reactive power |
| Loads / distribution exchange | power factor 1.0 (no reactive power) | P.O. 7.4 (2000) §6.1.3: peak draw ≤ 33 % of P, valley no injection into transmission, shoulder in between; REE: distribution cables inject at low load | inside the rule, real exchange unknown | unknown; needs REE data |
| Synchronous generators | MVA circle at rated power factor 0.9 (≈ ±0.48 P at full load) | P.O. 7.4 (2000) §6.1.1: obligatory ±15 % of P (cos 0.989) from minimum load to full, voltage-dependent (annex 6); more is optional and paid | generous against the obligation | less shortage: the shortage exists despite it |
| Shunt reactors | all 15.5 Gvar on in every hour | P.O. 7.4 §6.1.2: transmission owners operate reactors; REE connects them at low load | operation wrong; switchable test (VL4) not yet understood | more absorption by day |
| Capacitors, tap changers, line opening | none / taps fixed at 1.0 | P.O. 7.4 §6.1.2 lists all of them as the transmission owner's tools | missing | the model can only move energy |
| Voltage band | REE per level (P.O. 1.4), generator buses | P.O. 1.4 §3.2 | correct | — |

Prime suspects for the remaining shortage: the missing reactive generation of renewables' connection
networks and distribution cables, and reactors that are always on. Sources: BOE-A-2014-6123 (RD 413/2014,
consolidated); BOE 18 Mar 2000 núm. 67 (P.O. 7.4); REE (2024) informe justificativo del nuevo servicio de
control de tensión.

### Step C: voltage in phase I, week 2–8 Dec 2024 (22 Oct)

`[redispatch.phase1].ac_check`: an AC check of every hour on phase I's schedule, starting units there
(RD9's loop). C1 = VL3 + ac_check with RD5's zones; C2 = the same with RD5 off entirely (pending).

| | VL3 (no AC check) | C1 | REE |
|---|---|---|---|
| phase I up / cost | 183 GWh / 37.3 M€ | **237 / 38.8** | 214 GWh / 38.2 M€ (+ phase II −12.3) |
| phase I daily shape vs REE | 0.94 | 0.79 | peak 05 h |
| real-time up / cost | 81 GWh / 4.0 M€ | **26.5 / 4.3** | 87 GWh / 28.1 M€ |
| real time: storage up / wind+solar down | 38 / 12 GWh | 6 / 6 | 0 / 0.2 |
| hours solved | 167 | 168 | |

- Voltage leaves real time: C1's 26.5 GWh is VL3's non-voltage residual (VL3X: 25.5), so the
  voltage-driven part fell from 55 GWh to about zero (REE: 0.3); the storage/wind/solar swap is gone.
- What remains in real time is the missing reserve mechanism (26.5 vs REE's 86.5 GWh): step E.
- Phase I is now 110 % of REE's. With no N-1 (off) and no distribution cause (30 % and 12 % of REE's
  phase I), the model's voltage part of phase I (~237 GWh) is about twice REE's (125 GWh): consistent
  with the audit's finding that the model's reactive balance leans toward shortage.

**C2 (AC check, RD5 off entirely)**: phase I 328 GWh (153 % of REE) for only 14.2 M€, mostly hydro
(297 GWh up; gas 23) with 113 committed unit-hours (C1: 1,005; gas 167 GWh up). Without REE's zone
counts the AC check meets the voltage need with hydro, which is too freely available in the model's
redispatch (no water budget in phase I, RD11 only prices it); REE's phase I is mostly gas. Real time
38.8 GWh, 162/168 hours (6 stopped at Ipopt's iteration limit). Not yet usable for a counterfactual.

**E1 (C1 + tertiary reserve, P.O. 1.5 §4.3)**: identical to C1 (real time 26.5 GWh, no reserve
starts). The requirement averages 2,843 MW (aFRR 1,202 + largest unit 1,107 + 2 % of demand 534), but
counted headroom averages 16,447 MW (minimum 3,230) because stopped reservoir and pumped hydro count in
full (`offline_hydro_counts`). The tertiary rule never binds; REE's shortage that week most likely came
from the supplementary reserve (forecast errors, §4.4; step E2, needs e·sios forecasts) and from hydro
being less available than the model assumes.

### Start-ups counted once, and phase II's down bids (C3, 23 Oct)

C3 = C1 + up mark-ups net of start-ups (RD10b: CCGT 0.46, coal 0.50) + phase II down bids (RD12,
`bid_da`), 2–8 Dec 2024, run in two lanes (2–5 and 6–8 Dec), 168/168 hours.

| 2–8 Dec 2024 | C1 | C3 | REE |
|---|---|---|---|
| phase I/II up / down | 237 / 216 GWh | 231 / 211 | 214 / 219 GWh |
| phase I + II cost | 38.8 M€ (150 %) | **30.8 M€ (119 %)** | 25.95 M€ |
| phase I starts | 132 | 137 | |
| real-time up / cost | 26.5 GWh / 4.3 M€ | 45.5 / 7.7 | 87 GWh / 28.1 M€ |
| real time: gas up / down; hydro up | — | 18 / 28; 24 GWh | combined cycles up 85 GWh |

Counting start-ups once brings phase I + II from 150 to 119 % of REE with the same decisions. Real
time grew: with the lower up mark-up, gas-for-gas moves are cheaper (18 up / 28 down), and hydro rose
24 GWh because the water budget (RD13) was not yet on. Next: C3 + RD13.

### Water budget on (C4, 23 Oct) — and why the budget must not touch reserve

C4 = C3 + `[redispatch.hydro_budget]` (tolerance 0), 2–8 Dec 2024, 168/168 hours.

| 2–8 Dec 2024 | C3 | C4 | REE |
|---|---|---|---|
| phase I/II up / down | 231 / 211 GWh | 234 / 214 | 214 / 219 GWh |
| phase I + II cost | 30.8 M€ (119 %) | 35.1 M€ (135 %) | 25.95 M€ |
| real-time up / cost | 45.5 GWh / 7.7 M€ | 55.8 / 16.5 | 87 GWh / 28.1 M€ |
| real time: gas up; hydro up | 18; 24 GWh | 30; 24 GWh | combined cycles 85 GWh |
| real-time starts for reserve (RD7) | 0 | 63 | |

Totals are now 96 % of REE's volume and cost, but by phase they moved away (phase I + II 135 %).
The budget itself holds: per hydro unit and day, real time + phase I stay within 1.0 GWh of the
BAL schedule (11 of 1,393 unit-days above it). Phase I turned reservoir hydro down 71 GWh, and the
24 GWh of real-time hydro up is that water given back later the same day.

The 63 reserve starts are a side effect: the cap lowered each hydro unit's pmax, so its headroom
dropped out of the reserve check (RD7/E1) and gas was started instead. A water budget limits
energy; reserve held but not used costs no water. **Fixed (code, 23 Oct):** the cap is now a
constraint `pg ≤ cap` in the solve (`hydro_budget_constrain!`), pmax stays physical
(`test_rd13.jl`: 17 tests, incl. a DC OPF on PowerModels' case5 where the cap binds). C4 ran on the
old code. How much hydro headroom REE really counts for reserve stays open: REE starts CCGTs for
reserve, so it does not count all of it; step E2 uses REE's own reserve requirement (e·sios 626,
P.O. 3.9) instead of guessing that share.

### December 2024 on Solstorm (dec_C4, dec_C2b, 23–24 Oct)

1–29 Dec 2024 from Lars Erik's full-year run 4 (`2024_r4_hydro_offered`, split run), one node
each, 12 lanes, 29/29 days solved; settings as C4 (`AC=on HB=on`) and C2b (`AC=on ZONES=off HB=on`),
on the code before the RD13 fix (`22f7a09`). Results copied back and compared locally.

| 1–29 Dec 2024 | dec_C4 (zones) | dec_C2b (no zones) | REE |
|---|---|---|---|
| phase I/II up | 1,256 GWh (156 %) | 1,076 GWh (134 %) | 806 GWh |
| phase I + II cost | 118.1 M€ (148 %) | 76.2 M€ (96 %) | 79.7 M€ |
| phase I up by fuel | gas 1,131, hydro 13 | gas 899, coal 44, hydro 54 | mostly gas |
| phase I starts | 555 | 148 | |
| real-time up | 229 GWh (59 %) | 233 GWh (60 %) | 390 GWh |
| daily phase I volume vs REE, correlation | 0.65 | 0.45 | |

Per week, phase I up (model / REE, GWh):

| week | dec_C4 | dec_C2b | REE |
|---|---|---|---|
| 2–8 Dec (the test week) | 256 | 238 | 214 |
| 9–15 Dec | 265 | 227 | 131 |
| 16–22 Dec | 314 | 259 | 202 |
| 23–29 Dec | 364 | 335 | 221 |

- **Without REE's zones, phase I now starts gas, not hydro** (C2b: hydro 54 of 1,076 GWh; before the
  water budget it was 297 GWh in one week). So the voltage need can come from the grid alone.
- **But phase I is too large outside the test week** (134–174 % of REE in 9–29 Dec): the week the
  settings were checked on fits, the rest of the month does not. Christmas week, with low demand,
  has the most. Suspects: the reactive balance leaning toward shortage (audit), and REE's phase I
  depending on conditions the model does not see. Next: the reactive-power sensitivities on one of
  these weeks, and phase I by hour of day per week.
- **Real time is 60 % of REE's**, as in the test week: REE's reserve redispatch is missing (step E2).

### Step E2 groundwork: what drives REE's real-time reserve redispatch (24 Oct)

Data: e·sios 2024 forecasts and actuals (`fetch_esios_forecasts.py`, token in `~/.esios_token`) and
REE's hourly real-time up for "too little upward reserve" (`rtr_up_rsi`, 4.89 of 5.42 TWh in 2024).

- **Not forecast errors.** Hourly correlation with REE's forecast revisions (H+3 vs D+1: demand,
  wind, PV) is +0.00 to +0.01, with the errors (actual vs D+1) −0.05 to −0.13; REE's reserve
  redispatch is the same 470–630 MW in every decile of the revision. The planned E2 (requirement
  from forecast errors) has no support in the data.
- **Ramps.** It peaks at 07–08 h (~1,150 MW) and 19–21 h (~1,900 MW) and follows the residual
  demand (10249) falling over the next 3 hours: r = −0.38; in the two deciles with the steepest
  fall (−6 to −10 GW in 3 h) it averages 1,200–1,330 MW and occurs in 80 % of hours, vs ~250 MW when
  residual demand is flat or rising. Reading: the markets schedule thermal units down/off as solar
  rises or demand falls, and REE keeps combined cycles on for synchronised upward reserve.
- **Model check, December (dec_C2b's BAL schedules):** synchronised headroom of running gas, coal and
  hydro averages 1,005 MW vs REE's requirement (mFRR 1788 + aFRR band) of 2,789 MW; counting only
  running units would be short in 96 % of hours (1,022 GWh vs REE's 355 GWh; r = 0.17). Counting
  stopped hydro in full (today's `offline_hydro_counts = true`, ~14,900 MW) never binds. REE counts
  something in between; next: derive it from REE's own schedule (I90 PDVP) and reserve redispatch,
  not by fitting the share to REE's total.
- **REE's own schedule (PDVP, 8,709 h of 2024):** synchronised upward headroom of running CCGT, coal,
  hydro and pumped turbines (REE capacities from the crosswalk) plus stoppable pumping averages
  14,600 MW (min 5,857), never below mFRR + aFRR (2,492 MW): that requirement is not the trigger.
  But REE's reserve redispatch follows the headroom closely (r = −0.54): 1,589 MW (action in 90 % of
  hours) in the lowest decile (~9,700 MW) down to 19 MW (2 %) in the highest (~18,700 MW); headroom is
  lowest at 19–21 h. So REE keeps a synchronised margin well above the formal requirement. The
  model's December BAL headroom (1,005 MW) is not comparable yet (REE's UGH hydro units carry whole
  portfolios); next: the same headroom with the model's units and capacities via the crosswalk.
- **Counted the same way** (CCGTs unit by unit, 50 units / 24.6 GW on both sides; hydro and pumping
  as totals; REE's UGH hydro portfolios cannot be mapped to model units): over 2024 REE's reserve
  redispatch follows **scheduled hydro** (r = +0.70) and pumping (−0.46), less the CCGT headroom
  (−0.30), hardly the number of CCGTs running (−0.04). Reading: hydro carries the upward reserve;
  when the schedule uses it for energy (evening peak) REE keeps CCGTs on; stoppable pumping at
  midday is reserve. December, model BAL vs REE PDVP per hour: CCGTs running 2.7 vs 14.3 (PDVP
  includes REE's phase I; with the model's ~10 phase I units ≈ 13 vs 14), CCGT headroom 187 vs
  3,345 MW, hydro scheduled 4,522 vs 3,141 MW (+44 %), pumping 316 vs 720 MW.
- Proposed E2 (to agree): requirement = REE's mFRR + aFRR (hourly, data); synchronised thermal
  headroom counts in full; hydro (running or stopped) counts only up to what its daily water budget
  leaves; judged first by timing (evening peak, weak midday) against REE.
- **Replay on dec_C2b (no runs), 1–29 Dec:** the real-time anchor (BAL + phase I) has 21.4 thermal
  units running, 1,682 MW thermal headroom, 804 MW pumping, 697 MW running-hydro headroom, ~14,500 MW
  stopped hydro; need 2,785 MW; REE's reserve redispatch 362 GWh, 59 % of it at 17–22 h.
  Thermal + pumping only (the proposal with the water budget used up): short 727 GWh (2× REE),
  r = +0.41, right in the evening (~1,500 vs 1,280 MW at 17–21 h) but far too much at midday
  (1,200–1,600 vs 125–205 MW at 11–15 h). Adding running hydro: 460 GWh, same midday error. Adding a
  share of stopped hydro: 2 % gives REE's total but is wrong at both times of day; 10 % gets midday
  right (145 vs 165 MW) and leaves the evening 4× too low (331 vs 1,277); half or all of it never
  binds. Stopped hydro varies too little over the day (16 GW midday, 10 GW evening) for any share to
  separate the two. **E2 on hold:** a rule would be calibrated, not derived. The model's evening has
  more reserve than REE's system, likely from phase I's surplus starts (134 % of REE; phase I + real
  time up 1,309 vs REE 1,196 GWh): revisit after the phase I sensitivities.

### Connection-network sensitivity (9–15 Dec, Solstorm, 24 Oct) — and a likely line-data error

C2b settings + the RD13 fix, `[reactors].res_connection_mvar` = 0 / 1,000 / 2,000 / 3,000 (code
`8c59466`), 7/7 days each.

| 9–15 Dec | phase I/II up | phase I + II cost | real-time up | RT voltage starts |
|---|---|---|---|---|
| r0 | 187 GWh | 12.5 M€ (94 %) | 34.6 GWh | 50 |
| r1000 | 241 | 16.4 (124 %) | 44.6 | 83 |
| r2000 | 296 | 20.9 (158 %) | 85.4 | 143 |
| r3000 | 371 | 26.7 (202 %) | 137.7 | 214 |
| REE | 131 | 13.2 | 122 (mostly reserve) | |

- More capacitive Mvar → more redispatch (≈ +60 GWh phase I per 1,000 Mvar). 400 kV buses sit at
  the **lower** limit (16 → 20 % of bus-hours; 2 % at the top) and more so with more Mvar: the OPF
  lowers voltages to cut line charging (∝ V²), i.e. a reactive **surplus**. **Correction:** the
  audit's reading (22 Oct, "buses at the lower limit ⇒ balance leans toward shortage") was wrong.
- **Line data:** `Data/lines.csv` gives 40,713 circuit-km at 400 kV and 35,376 at 220 kV (charging
  35.1 Gvar); REE: 22,013 and 20,189 km (Spain, end 2023; 2012 peninsula 20,104 / 18,317). 1,386 lines
  come in a/b pairs on the same bus pair and 1,310 of them have `circuits = 2` each (the other 790
  rows are mostly 1), and `data_preparation.jl` treats `circuits` as parallel circuits (X / N, B × N):
  a double-circuit line enters as four. Counted once: 25,032 / 23,458 km (1.14× / 1.16× REE). Shared
  input data, so a group issue; on this branch a switch, off by default, to test on 9–15 Dec.

### Duplicate lines counted once (`DEDUP=on`, Solstorm, 24 Oct)

`[network].dedup_ab_lines = true` (`888e4db`, line charging 35.1 → 21.9 Gvar), C2b settings + RD13 fix,
7/7 days and all hours solved in both runs.

| phase I/II up | without | dedup | REE |
|---|---|---|---|
| 9–15 Dec (s915_r0 → s915_dedup) | 187 GWh | 125 GWh | 131 GWh |
| 2–8 Dec (dec_C2b days → s28_dedup) | 238 GWh | 35.5 GWh | 214 GWh |
| AC-check voltage starts (unit-hours) | 30–88 per week | 0 on every day | most of REE's phase I |

- The duplicate lines drove the model's voltage redispatch: with them counted once, the units running
  absorb the remaining line charging and no unit is started for voltage on any day.
- Now the voltage need is too small: REE's phase I is mostly voltage (58 % on 2–8 Dec). 9–15 Dec
  matches REE's total only by coincidence; what remains is gas-for-gas reshuffling of running units
  (11 and 13 Dec: ~30 GWh up / 30 down, 1–2 starts), a separate question.
- Next: the connection-network sensitivity on the corrected grid (DEDUP=on + RESMVAR 1,000 / 2,000 /
  3,000 on 2–8 Dec), judged by cause (night voltage starts, units, daily shape). REE gives only
  "thousands of Mvar", so choosing the value is a calibration within that range.

### Connection networks on the corrected grid (DEDUP=on + RESMVAR, 2–8 Dec, Solstorm, 25 Oct)

| RESMVAR | phase I up | AC-check voltage starts | night 400 kV mean / at upper limit |
|---|---|---|---|
| 0 | 35.5 GWh | 0 | 1.018 pu / 6 % |
| 1,000 | 35.5 | 0 | 1.017 / 6 % |
| 2,000 | 35.6 | 0 | 1.016 / 5 % |
| 3,000 | 35.7 | 0 | 1.014 / 3 % |
| REE | 214 GWh (58 % voltage) | | overvoltage at night |

The Mvar is applied (configs, voltages move) but phase I does not change (identical hour profile, peak
14 h vs REE 05 h, r = −0.52): the running units absorb 3 Gvar more without a start. Synchronous units
get the full MVA circle (S = installed / 0.90) with the reactive box widened to ±S, so a 400 MW CCGT at
~160 MW absorbs ~410 Mvar; P.O. 7.4's obligatory band is ±15 % (~±60 Mvar), typical under-excited
limits about a third of rated MVA. Next: limit synchronous reactive power to (a) P.O. 7.4's ±15 % of
installed MW, (b) a typical capability curve (−0.33 / +0.6 of rated MVA, an assumption).

### Step E design: REE's upward reserve need (P.O. 1.5, 22 Oct)

REE's real time that week was 96 % "too little upward reserve". P.O. 1.5 (BOE-A-2022-4969, in force
in 2024) sets the reserve REE must hold:

- secondary (§4.2): per quarter-hour, at least 500 MW up / 400 MW down; RD7 uses REE's assigned band
  from I90 (mean 922 MW);
- tertiary (§4.3): upward = the largest loss of production from a single failure + 2 % of the
  forecast demand; deliverable within 15 min and held 30 min; secondary + tertiary must cover 99 % of
  historical imbalances;
- supplementary (§4.4): the deficit between REE's own forecasts of demand, wind and solar and the
  market schedules (PDVP, PHF), plus the risk of thermal units starting late (≥ 5 % probability).

RD7 checks only the secondary band, which running units always cover, so it never binds and real
time never starts combined cycles. Step E: requirement = secondary + tertiary + supplementary, the
last from e·sios forecasts (demand, wind, solar) against the model's schedules; providers limited to
what P.O. 1.5 allows (15-minute delivery, 30-minute hold, so storage only within its energy).

### Model data to check with the group (22 Oct)

- `Data/transformers_reactance.csv`: 67 of the 129 220/400 kV transformers are built from 100 MVA
  units (total 71.5 GVA, median bank 300 MVA); real 400/220 kV units are typically several hundred MVA.
  The columns (`n_recommended`, `per_unit_MVA`) suggest a sizing heuristic; no provenance in the repo.
  TR_30aa9055 (2 × 100 MVA, Asturias near Aboño) is the one N-1 overload left. To compare with REE's
  published transformation capacity.
- Solver robustness (step D, from existing runs): VL4's weekly objective is slightly lower than VL1's
  (88.26 vs 88.47 M€), as more freedom should give, but higher in 91 of 168 hours: Ipopt lands in worse
  local optima. Two solutions of nearly equal cost differ by ~70 GWh of real-time volume (339 vs 410),
  so real-time volumes carry that uncertainty. A stronger least-energy-moved rule (REE's tie-break,
  P.O. 3.2 §6.1.3) would narrow it.

### What drives real time: voltage tests, 2–8 Dec 2024 (21 Oct, evening)

All from CH0's saved schedules (phase I after the markets, every realism switch on).

| Run | Change vs CH0 | Real-time up | RT cost | Storage up / wind+solar down | RT daily shape vs REE | Hours |
|---|---|---|---|---|---|---|
| CH0 | — (generator buses 0.975–1.05) | 577 GWh | 18.0 M€ | 320 / 334 GWh | −0.06 | 168 |
| VL1 | band per voltage level, generator buses (`voltage_limits_by_kv`, P.O. 1.4) | 339 | 10.6 | 201 / 204 | −0.01 | 168 |
| VL2 | the same at every bus | 413 | 12.9 | 240 / 242 | 0.07 | 168 |
| VLX | limits 0.90–1.10 at every bus (diagnostic) | 29 | 3.2 | 5 / 3 | −0.56 | 168 |
| **VL3** | **VL1 + wind/solar power factor 0.98** | **81** | 4.0 | 38 / 12 | **0.51** | 167 |
| VL4 | VL1 + switchable reactors (`[reactors].switchable`) | 410 | 12.5 | 259 / 240 | 0.02 | 168 |
| REE | | 87 GWh | 28.1 M€ | 0 / 0.2 (I90DIA08) | | |

- **Voltage drives almost all of real time** (VLX). In CH0/VL1 the generator buses sit at the **lower**
  limit: a reactive-power shortage, which real time covered by running synchronous storage and hydro up
  and curtailing wind and solar.
- **The shortage came mostly from RD4.** RD4 set wind and solar to power factor 1.0 (no reactive power);
  REE's 2024 voltage report says generators followed fixed voltage or power-factor setpoints, and
  RD 413/2014 art. 7 e) i) requires renewables to hold an hourly power factor within its Annex III range,
  at most 0.98 capacitive to 0.98 inductive (to check against the consolidated BOE text). With 0.98
  (VL3) real time is 81 vs REE's 87 GWh and the storage swap is nearly gone. VL3 lets the optimiser
  choose the reactive power within the band, an upper bound: in 2024 it was a fixed setpoint.
- **Still off in VL3:** real time is cheap (4.0 vs 28.1 M€; REE's real time is mostly combined cycles
  started for too little upward reserve, at ~323 €/MWh), and its peak is at 23 h vs REE's 17 h.
- **Switchable reactors (VL4) made real time larger**, although they only add freedom. Not yet understood
  (Ipopt is a local solver; the device absorbs a chosen Mvar instead of b·V²). Off by default.

### RD6b N-1 by P.O. 1.1's rules, 2 Dec 2024 (21 Oct)

P.O. 1.1 (2016) §4.3.2: after a single outage a line must stay within its **seasonal** thermal limit
(+15 % for under 20 min, kept as `n1_emergency_factor`), a transformer within its rating (+10 % in
winter). RDL 17/2022 Annex I sets the seasons (winter Nov–Mar, spring Apr–May, summer Jun–Aug, autumn
Sep–Oct) but leaves the values to the owners. Two changes, both in `redispatch_phase1.jl`:

- `n1_seasonal_ratings` (off by default): post-outage line limits × `n1_line_season_factor`
  (winter 1.18, spring/autumn 1.09, summer 1.0: the model's generic conductor ratings taken as summer
  values, scaled by √(Tc − Ta) with Tc 85 °C and design ambients 15/25/35 °C — an assumption);
  transformers × 1.10 in winter.
- `n1_outage = "element"` (default): an outage trips **one** circuit of a line or one transformer of a
  bank. The network merges parallel elements into one branch, so before, "losing" a 3 × 1,000 MVA
  220/400 kV bank dropped all three at once (an N-3). The elements left in the tripped branch are
  checked against (n − 1)/n of its limit. `test_rd6.jl` checks the formula against an exact
  recomputation of the grid without the tripped circuit (13/13 pass).
- `rd_n1_left.csv` lists the post-outage overloads phase I cannot remove (monitored branch, outage,
  hours, MW over).

| 2 Dec 2024, phase I | N6b: whole branch, one rating | N6s: whole branch, seasonal | N6e: one element, seasonal | no N-1 (V1) | REE |
|---|---|---|---|---|---|
| phase I up | 37.5 GWh | 30.8 GWh | **11.5 GWh** | 11.5 GWh | 20.1 GWh |
| phase I cost | 3.60 M€ | 3.13 M€ | **1.78 M€** | 1.78 M€ | |
| overloads found, first round | 238 | 160 | 63 | | |
| overload left, mean / max | 1,438 / 1,560 MW | 1,180 / 1,300 MW | **188 / 310 MW** | | |

Before the fix, 1.0 of the 1.2 GW left came from two 3 × 1,000 MVA transformer banks tripped whole
(LTGES0441 841 MW over after TR_87714406; LTGES0460 150 MW after TR_4422f4c8). What is left is one
pair: transformer TR_30aa9055 (2 × 100 MVA, 220/400 kV, ES00173–ES00174) after losing 400 kV line
LTGES0920 — 100 MVA units are unusually small for 220/400 kV, so this looks like a data error
(`Data/transformers_reactance.csv`), not a redispatch need. With the fix N-1 is no longer too strict,
but on 2 Dec it adds no phase I volume (11.5 GWh with and without), while REE's N-1 share that day
was about a quarter of 20.1 GWh. Not modelled: REE's finer grid and real line ratings, generator and
busbar outages, double-circuit losses (criterion b). To judge on more days.
`make_config.jl --n1 on` now sets `n1_outage = "element"` and `n1_seasonal_ratings = true`.

### Gap 3: why phase I starts fewer units than REE (2–8 Dec 2024)

Not because the model's day-ahead runs too many gas/coal units in the voltage zones: it runs far fewer
(zone gas/coal units: 814 vs REE's 2,348 unit-hours in the day-ahead, 68.5 vs 501.6 GWh; REE's day-ahead
= I90DIA01 PDVP − I90DIA03 phase I/II). The RD5 zone requirement was met almost fully (1,099
unit-hours needed, 4 short), but it only covers hours in which REE raised a zone unit **for voltage**;
REE's phase I also starts units for N-1 (26 % of its phase I up that week), distribution (10 %) and
other causes (12 %), which the model does not have. One exception: in the Soto de Ribera zone the
December source run spreads the observed coal output pro rata over every coal unit (each ~32 % on 2–3 Dec),
so Soto de Ribera 3, Aboño 1 and La Pereda run in the model's day-ahead while REE ran Soto de Ribera 3
for 1 hour; the zone count is met by the wrong units and phase I starts 20 unit-hours there against
REE's 114. `main`'s coal unit commitment (§16, day-by-day chain) replaces that method: the full-year
realism runs should use a source run made with it.

### RD6 N-1 test N6b, 2 Dec 2024 (V1 settings + soft N-1)

Hard post-outage limits made phase I infeasible (238 overloads, worst 1,388 MW); with soft limits
(3,000 €/MWh) the lazy loop converges in three rounds (238 → 116 → 0 new overloads). Phase I then
moves **37.5 GWh** (11.5 without N-1; REE 20.1 GWh, of which N-1/SCA is roughly a quarter) with the
same 9 started units, and 1,250–1,560 MW of post-outage overload remains in every hour that no
redispatch can remove. N-1 with one fixed rating × nominal is too strict for this grid data; RDL
17/2022 sets seasonal (winter-higher) ratings. RD6 stays off by default; revisit with seasonal ratings.

### Voltage rule (changes a main default)

`[network].gen_bus_vmin/vmax` is now **0.975/1.05 pu** on this branch (main: 0.98/1.03): REE's
normal-operation range for the 400 kV grid, 390–420 kV (P.O. 1.4 §3.2, BOE-A-1998-20053), which
REE's 2024 voltage-control report confirms was still the admissible band in 2024 (P.O. 1.1, 1.3,
1.4). The N-1 voltage limits of the current P.O. 1.1 (2016, BOE-A-2016-3275) are the same as in
1998 (400 kV 380–435 kV after a single outage). Line/transformer loading limits now come from RDL
17/2022 Annex I (seasonal ratings). Copies of the texts in `litterature review/` (BOE1998_…,
BOE2016_…, BOE2022_…, REE2024_…), described in its INDEX.md. This is the one change on the
branch that alters runs with every redispatch-realism switch off (AC voltages and flows), so the
group should agree before merging.

### Voltage-band test V1, 2 Dec 2024 — the volume gap was the generator voltage band

V1 = CAL with `[network].gen_bus_vmin/vmax = 0.95/1.05` pu (main's default 0.98/1.03, much
tighter than REE's operating range at 400 kV).

| | CAL (0.98–1.03) | V1 (0.95–1.05) | REE |
|---|---|---|---|
| solved hours | 21/24 | **24/24** | |
| up: real time + phase I, GWh | 85.5 + 11.5 | **19.8 + 11.5** | 39.3 |
| real-time up by type, GWh | hydro 37, pumped 33, gas 13 | **gas 13.0, hydro 4.4, pumped 1.5** | gas/coal |
| real-time starts: zone / RD9 loop | 8 / 35 | 8 / **0** | |
| extra cost, M€ | 8.5 + 1.8 | **2.35 + 1.78 = 4.1** | 8.30 |

With the tight band and no free reactive power, the AC model needed ~3× REE's energy moves to hold
voltages; with REE-like limits the volume is 80 % of REE's, gas-led, every hour solves and RD9's
fallback start-ups are not needed. The cost is now half of REE's; the gap is mainly REE's
real-time constraints (6.6 M€ at 238 €/MWh). The band is a main default used by the group's other
runs: changing it there is a group decision; the redispatch-realism runs set it in their config.

REE's own units for 2–4 Dec (I90DIA03/09, public e·sios archive 34, see
`tmp/scripts/i90_phase1.py`; to become a repo script at checkpoint 3): phase I up 67.2 GWh,
5.8 units per hour on average, weighted 212 €/MWh, peak 01–05 h (≈1.65 GW). Largest: CTGN3,
ABO2 (Aboño, Asturias), CTGN1, BES3, BES5, PBCN2, ESCCC2, CTN3, MALA1, BAHIAB, PGR5, SAGU3,
SROQ2, ACE3 — the structural nodes of Dorado Galatoire et al. (2024).

The FAIL is the finding, not a bug. Without the free sources, the grid cannot hold voltage in the
low-load hours: 17 of the 20 lowest-load hours fail (mean load 22.9 GW in failed hours against
29.5 GW in solved ones), mostly 00–06 h, the window where REE's phase I peaks. Ipopt stops at its
iteration limit there. The cure is RD9 (let the redispatch start units), so `rd3` is expected to
fail on hours until checkpoint 3.

Where the reactive power went (average |Mvar| per hour, A → B3, over the hours both solved):
load shedding 10,294 → 0; synchronous units scheduled off 4,047 → 0; running synchronous units
2,960 → 8,132; wind and solar 1,838 → 3,261 (RD4 removes this); border 440 → 1,214; slack
29 → 992. The slack's free ±9999 Mvar is the last free source and should be capped (next
checkpoint). Energy turned up 31.6 → 108.3 GWh and the extra cost turned positive (−2.93 →
+0.52 M€), still at marginal cost.
