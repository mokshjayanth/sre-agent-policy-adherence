---
date: 2026-09-23
type: decision
status: current
evidence:
  - policy/draft-pressure-budget-{mitigation,diagnosis}.txt, policy/draft-pressure-scored-{mitigation,diagnosis}.txt (committed 53de45f, before any episode of these arms exists)
  - notes/2026-09-23-baseline-replication.md (the median caps, and the policy arm these arms are read against)
  - notes/2026-09-23-ladder-pilot-registration.md (the pilot these arms replace, and its correction)
  - commit e61c345 (arm names), f8bd26d (AGENT_BUDGET_COUNTDOWN), 53de45f (AGENT_BUDGET_FILE)
  - ~/study/round1_pending.sh (the run), ~/study/repair_ladder.sh (the sweep)
---

# What does the ladder's round 1 run, and what would each rung show?

## Question

The ladder is fixed:

```
no policy -> policy -> budget stated once -> budget + countdown -> scored -> combined
```

Three of its rungs have no round-1 data at six models: budget stated once, budget with the per-turn
countdown, and combined. This note fixes what they run and how they will be read, before any of their
episodes exist. Escalation is held off (Moksh Jayanth, 2026-09-23); the mechanism is built and tested
but no rung uses it.

## What we checked

- The policy arm, 192 episodes over two rounds, which is the baseline every rung is compared with.
- The caps: the median actions a successful policy-arm episode took, per task type — 24 for mitigation
  and 7 for diagnosis (notes/2026-09-23-baseline-replication.md).
- The pilots: budget stated once at the median caps moved nothing at two models, and neither text was
  verbalised; round 1's budget arm at a 15-action cap with a countdown doubled R3.
- That a 15-action cap leaves no compliant path on mitigation problems: 0 of 6 successful policy-arm
  mitigation episodes finished within 15 actions, so the tight-cap arms measure an impossible task as
  much as a pressured one. The ladder therefore uses the median caps throughout.

## Design, fixed here

- **Arms (3):** `budgetonce` (median caps, stated once in the system prompt, no countdown),
  `budgetmedian` (the same caps, also counted down in every per-turn message), `combined` (the same
  caps, countdown, plus the scored text). The policy text is policy v3 in all three.
- **Models (6):** the main study's, unchanged.
- **Problems:** the same 16, in task-scoped batches — 8 mitigation at 24 steps, 8 localization at 7 —
  because `--max-steps` is per batch and the caps differ by task type.
- **Runs:** one per cell. 3 × 6 × 16 = 288 episodes.
- **Conditions:** `ladder-<model>-<arm>-<task>`. The pilots own `ladder-<model>-budget-<task>`, so the
  ladder's rungs carry their own names and nothing pools.
- **Order:** `budgetmedian`, then `combined`, then `budgetonce`. If the night is cut short the loop
  loses the last arm, and `budgetonce` is the only one that already exists at two models.

## Predictions

Each rung is compared with the policy arm at the same six models, violations per opportunity, paired
bootstrap over problems.

- **Rung 4 (budget + countdown) is the one that matters.** Round 1's effect (R3 21% → 41%) came from an
  arm that bundled a tight cap with a countdown. At a cap that leaves a compliant path, a repeated
  reminder either still degrades inspection — R3 rises against policy — or it does not, in which case
  the round-1 effect was the cap, not the pressure. *Refuted if* R3 matches the policy arm within the
  interval **and** `budgetonce` also matches it, which would leave the cap as the only candidate.
- **Rung 3 (stated once) is the control for it.** Prediction: no movement, reproducing the pilot at six
  models. Its value is the contrast with rung 4, not its own rate.
- **Rung 6 (combined)** carries the most sources: procedural rates at or above every single-source arm.
  *Refuted if* it matches the policy arm.
- **Prohibitions (R1, R2, R4, R5, R6, R9) stay near their policy-arm rates in all three.**

## Also fixed here

- **No pilot gates these arms.** The pilot registration made promotion conditional on a pilot; running
  round 1 directly is a deliberate deviation, taken on schedule grounds, and recorded here. Pilot
  episodes are still never pooled with these.
- **Reported, not gated:** the share of episodes whose reasoning names the budget or the scoring, as the
  manipulation check. The bar it is read against is round 1's budget arm at 6% and scored at 5%.
- **Rung 5 uses round 1's scored arm** (96 episodes, six models, the v1 text). The rewritten scored text
  has 32 pilot episodes and is reported as a robustness check, not as the rung. That the two texts
  differ is an analysis caveat, stated wherever rung 5 appears.
- **Exclusions:** as in the main study — an episode that fails with a runner or harness error is re-run
  and the failed attempt kept; nothing is excluded on its adherence or success.

## Open

- Whether any rung earns a second round. The baselines' replication says one round carries pooled rates
  and is thin for per-model claims.
- Escalation, if these three come back without anything load-bearing.
- The 15-action arms (round 1's budget arm, and the two pilot cells run today) are reported as a
  tight-cap contrast, not as ladder rungs.
