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
| 2 | RD3, RD4 | reactive power only from running units; 2024 rules for wind/solar reactive power | built; RD3 works and exposes night voltage hours (needs RD9); RD4 check running |
| 3 | RD8, RD9, RD5 | phase I/II stage on the day-ahead schedule: daily unit commitment, must-run by voltage area | — |
| 4 | RD10, RD11 | REE's objective, pay-as-bid mark-ups; storage at opportunity cost | — |
| 5 | RD6, RD7 | N-1 on critical corridors; upward reserve in real time | — |

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
