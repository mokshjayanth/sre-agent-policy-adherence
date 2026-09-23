---
date: 2026-09-23
type: audit
status: current
evidence:
  - results/main-2026-09-23/ (576 graded episodes; batches.csv, rates-by-variant-rule.csv, episodes.csv)
  - runs/2026-09-22T18*_main-*-r2 and runs/2026-09-23T0*_main-*-r2 (12 round-2 batches, 192 episodes)
  - commit 436e6d8 (round labels and runner/catalog.py), commit 8b24a86 (these tables)
  - notes/2026-09-20-main-study-preregistration.md (analysis plan; the budget rule registered 2026-09-22)
  - notes/2026-09-15-premise-check-pilot.md (the pilot's paired runs, used here for run-to-run noise)
---

# Does a second run reproduce the baseline results, and what budget does the rule give?

## Question

Round 1 ran one episode per problem per cell. The pilot had shown large run-to-run swings at
temperature 0.5, so before any of round 1's numbers carry a claim, the two unchanged arms — no policy
and policy v3 — needed a second, independent run. The same run also supplies the number for the
pressure arms' action budget, under a rule registered before it started: **the budget is the median
number of actions a successful policy-arm episode took, per task type**.

## What we checked

- `~/study/round2_baselines.sh`, launched detached 2026-09-22 18:54 UTC: 6 models × {policy, nopolicy}
  × 16 problems, `--max-steps 30`, conditions `main-<model>-<arm>-r2`, variant order reversed against
  round 1. Finished 2026-09-23 04:03 UTC (9 h 09 m).
- `python -m runner.catalog --study main`: every round-2 batch's arm, round, step budget and
  instructed-text hashes.
- `python -m grading.report runs/*_main-* --out results/main-2026-09-23`, then round 1 and round 2
  rates computed separately for the two arms.
- The pilot's paired runs (`results/pilot-2026-09-15/episode-map.json`, 12 cells run twice) as the
  prior estimate of run-to-run noise.

## Findings

1. **The run completed clean.** 12 of 12 batches, 192 of 192 episodes `ok`, no failed episode left
   behind. One episode (mistral-large3, policy) died of the harness's
   `storage_user_unregistered.eval` TypeError and its in-batch retry succeeded; the chained repair pass
   found nothing to do. Catalogue reads all twelve as round 2, arm correct, `text_status: matches`.
   Cost: 56.9M prompt and 0.69M completion tokens.

2. **The headline effects replicate.** Violations per opportunity, round 1 / round 2 / pooled:

   | rule | no policy | policy v3 |
   |---|---|---|
   | R2 no exec in diagnosis | 27 / 25 / **26%** | 14 / 15 / **15%** |
   | R3 inspect before changing | 51 / 51 / **51%** | 21 / 27 / **24%** |
   | R6 restart properly | 71 / 62 / **68%** | 2 / 7 / **5%** |
   | R7 record the change | 100 / 100 / **100%** | 68 / 62 / **65%** |
   | R8 verify after | 42 / 34 / **39%** | 36 / 37 / **36%** |
   | R9 never print a secret | 32 / 23 / **28%** | 33 / 23 / **28%** |

   Success and Completion under Policy are equally stable: policy 43% / 41% success and 32% / 32% CuP;
   no policy 39% / 39% success and 18% / 23% CuP. The claim round 1 supported — the policy nearly
   eliminates prohibitions while procedural rules stay broken, R8 barely moving — survives replication.

3. **The one unstable number is the one whose denominator was thin.** R5 under policy was 89% (8 of 9
   deletes) in round 1 and 22% in round 2; pooled it is 56% (10 of 18) with an interval of [29, 86].
   Without the second round, 89% would have been reported. The cause is denominator composition: the
   policy stops agents restarting by deleting pods, which removed 44 of the 47 deletes seen without it,
   leaving a handful of protected-kind deletes to fill the rate. R5 needs its absolute count reported
   beside the rate.

4. **Run-to-run noise is real but concentrated in small denominators.** The pilot's paired runs flipped
   17 of 50 rule verdicts and 4 of 12 success outcomes. At 192 episodes per arm the pooled rates move
   by a few points between rounds on every rule with a large denominator (R2, R3, R6, R7, R8), and by
   67 points on the one with 9 and 9.

5. **The registered budget rule gives 24 and 7.** Median actions of a successful policy-arm episode,
   pooled over both rounds: mitigation 24.5 (n = 10, up from 6 in round 1), diagnosis 7.0 (n = 70, up
   from 35, where round 1 alone gave 8). Rounding, fixed here: nearest integer, a tie rounds down, so
   the budget binds slightly harder. **Mitigation 24, diagnosis 7.**

## Decision

- The two baseline arms are complete at two runs each and their pooled rates are what the paper cites.
- The pressure arms' budget is 24 actions for mitigation problems and 7 for diagnosis problems, which
  requires one batch per task type per arm because `--max-steps` is set per batch.
- R5, and any rule whose opportunities fall below roughly 20 in a cell, is reported as a count beside
  its rate, with the interval, and no claim rests on it alone.

## Open

- Whether the pressure arms get two rounds each, one round, or a pilot first — undecided at the time of
  writing; the budget numbers above hold either way.
- Round 1's budget and scored arms remain single-round, so anything they support is weaker than the
  baselines; they are also the comparison for the pressure texts that replace them.
- Ministral 3B produced 138 of round 2's 248 parse failures and sometimes emits no parseable action for
  an entire episode. Those episodes contribute no opportunities, so they thin its sample rather than
  distort it.
