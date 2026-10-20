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
| 1 | RD1, RD2 | settle the redispatch like REE; take the losses out of the load | built, RD2 not yet run |
| 2 | RD3, RD4 | reactive power only from running units; 2024 rules for wind/solar reactive power | — |
| 3 | RD8, RD9, RD5 | phase I/II stage on the day-ahead schedule: daily unit commitment, must-run by voltage area | — |
| 4 | RD10, RD11 | REE's objective, pay-as-bid mark-ups; storage at opportunity cost | — |
| 5 | RD6, RD7 | N-1 on critical corridors; upward reserve in real time | — |

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
python redispatch_realism/settle.py $R/rd2_A
python redispatch_realism/settle.py $R/rd2_B
```

`from_saved = "BAL"` reuses the saved market schedule, so only the AC stage reruns (one week,
168 AC hours). What to look at in B against A: up − down drops from ≈ the losses to ≈ 0, pumped
storage up falls, and every hour that solved in A still solves in B.
