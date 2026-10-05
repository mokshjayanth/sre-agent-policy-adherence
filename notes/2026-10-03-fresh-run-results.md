---
date: 2026-10-03
type: audit
status: current
evidence:
  - results/fresh-2026-10/ (selection, graded tables, analysis tables, hand-check labels; README there)
  - analysis/check_selection.py, analysis/registered_tests.py, analysis/secondary.py, analysis/reporting.py, analysis/paper_numbers.py
  - notes/2026-09-20-main-study-preregistration.md (H1–H6, analysis plan), notes/2026-09-23-ladder-round1-registration.md (rungs)
  - commits a2fc773, 88713f1, 42b9fa5 (the three plans); grading/grade.py unchanged since 1e26114
---

# What do the fresh run's 1,056 episodes show for the registered hypotheses?

## Question

The fresh run (`notes/2026-09-27-fresh-run.md`) finished on 2026-10-01 with every episode certified. This
note records what the registered analysis found, so the paper's claims trace to a committed note and
committed tables rather than to a planning document.

## What we checked

- **Selection.** `analysis/check_selection.py` builds the 1,056 episodes from the three plan files and
  checks them against the catalogue, each batch's recorded settings, the attempt folders and the
  verifier's per-episode output (`results/fresh-2026-10/verification/`): 84 batches, exactly one per
  planned condition; 178 other batches in `runs/` excluded; 2 attempts that died of harness errors set
  aside (the re-runs are used). Prints `SELECTION OK`.
- **Grading.** `python -m grading.report` over the 84 batches (`results/fresh-2026-10/graded/`). Violation
  detection (`grading/grade.py`) is unchanged since the registration commit `1e26114`.
- **Registered tests** (`analysis/registered_tests.py`), the rest of the analysis plan
  (`analysis/secondary.py`, `analysis/reporting.py`), and every further number the paper uses
  (`analysis/paper_numbers.py` → `analysis/paper-numbers.csv`).
- **Hand check** (registered): 20 episodes drawn after grading with seed 20261002, read against the grader;
  4 of them re-labelled blind by the author (`results/fresh-2026-10/labels/`).
- All outputs were regenerated on 2026-10-03 after the scripts moved into `analysis/`; every file came out
  byte-identical.

Rates are violations per opportunity; intervals are 95% bootstrap over problems, differences paired on
problems (`grading/report.py`). Families: procedures R3, R7, R8; prohibitions R1, R2, R5, R6, R9 (H1's list).

## Findings

1. **The policy's effect is rule-specific** (`graded/rates-by-variant-rule.csv`,
   `graded/differences-by-rule.csv`; the `nopolicy` rows there are no policy minus policy). No policy →
   policy: R6 58.4% → 6.5% (73/125 → 8/124); R7 100% → 68.8%; R9 33.8% → 22.4%; R8 40.3% → 29.8%;
   R2 27.5% → 20.0%; R3 30.0% → 21.8%; R1 1.5% → 0.5%; R4 0 in both. R5: deletes fall from 74 to 11, so its
   rate (11/74 → 7/11) isn't comparable. Success 39.1% → 44.3%, CuP 19.3% → 27.1% (`analysis/per-arm-summary.csv`).
2. **H1 holds in every model** (`analysis/h1-policy-arm-family-by-model.csv`): policy-arm prohibitions vs
   procedures — gpt-oss-120b 0.7% vs 26.0%, Ministral 3 3B 12.5% vs 67.0%, 8B 12.9% vs 51.8%, 14B 12.8% vs
   45.1%, Mistral Large 3 2.9% vs 24.1%, Qwen3-Next-80B 13.7% vs 47.1%. It also holds in both AOI splits for
   all six models (`analysis/reporting.py`); the split coincides with the app (train = SocialNetwork).
3. **H2 is refuted** (`analysis/h2-differences-family-*.csv`): no model's procedural rate rose under
   Budget-15 or Scored; pooled +1.6 [−7.7, +11.5] and +0.8 [−6.2, +6.7]. Exception by rule: R3 rose under
   Budget-15 (+9.8 [+0.7, +20.4]) and Scored (+8.8 [+3.2, +16.2]).
4. **H3 isn't refuted by its wording, but procedures fall monotonically with size** in the Mistral family
   (3B 67.0, 8B 51.8, 14B 45.1, Large 3 24.1); prohibitions don't (12.5, 12.9, 12.8, 2.9)
   (`analysis/h3-policy-arm-mistral-family.csv`). Same with the registered three models only.
5. **Ladder** (`analysis/ladder-differences-*.csv`): Budget-once, Budget-countdown and Combined moved no
   procedural rule (R3 −2.9, +0.8, +2.4; procedures −3.4, +0.5, +0.3; all intervals include 0). Rung 3
   (no movement from a stated budget) confirmed; rung 4 (countdown moves R3) and rung 6 (combined moves
   procedures) refuted. Pooled prohibitions are lower in every pressure arm, but that is mostly weighting:
   Ministral 3 8B supplies 251 of 619 policy-arm R2 opportunities and issues fewer commands under pressure.
6. **Success and CuP** (`analysis/table3-arms.csv`): under the policy, mitigation success 22.9% and CuP 3.1%
   (3/96); diagnosis 65.6% / 51.0%. Mitigation CuP is 2–4% in every policy arm, 0% without the policy.
   avg@2 / best@2 for policy mitigation 22.9% / 39.6%; both runs succeed for 6.2% of problem–model pairs.
   Budget-15 mitigation success 4.2% (−18.8 [−30.2, −10.4]): only 2 of the 22 successful policy-arm
   mitigations took ≤ 15 actions. Budget-once loses success at the median cap (mitigation −10.4
   [−16.7, −4.2], diagnosis −30.2 [−44.8, −13.5]); Budget-countdown and Combined show no clear loss
   (`analysis/paper-numbers.csv`); step-limit endings 54, 45, 34 of 96.
7. **H4 holds in five models; unmeasured in gpt-oss** (`analysis/h4-recognition.csv`): violations whose
   own Thought cites a rule — 3B 109/350, Large 3 26/188, Qwen 32/333, 14B 23/331, 8B 5/334, gpt-oss
   0/167. gpt-oss's reasoning is returned outside the content the agent records, so its 0 is not evidence
   of absence.
8. **H5 holds where testable** (`analysis/h5-cells.csv`, `analysis/paper-numbers.csv`): over the 66
   model × arm × task cells with both kinds of episode, violating episodes succeed less in 37, more in 16,
   equally in 13; in diagnosis, less in 28 of 34. Pooled mitigation looks the other way (violating 41/285,
   14.4%, vs clean 11/115, 9.6%) because clean mitigation episodes mostly did nothing: in the policy-bearing
   arms 61% (59/97) of them executed no change. Among those that executed a change, clean 11/38 (29%) vs
   violating 59/325 (18%).
9. **H6 is partly supported, descriptively** (`analysis/h6-context.csv`): R3 violations occur at larger
   prompts (median 20.3K vs 13.9K tokens), R7 shows no difference (as predicted), R8 shows none (prediction
   fails). Position confounds it.
10. **Dose-response (registered)** (`analysis/paper-numbers.csv`): skipped records rise across the episode in
    the countdown arm (R7 54% → 80%, middle to last third) and equally without any countdown (policy arm
    60% → 67% → 75% by third of its 30 steps). No evidence the countdown drives it.
11. **Manipulation check is weak** (`analysis/per-arm-summary.csv`): episodes whose Thought names the budget
    — Budget-15 9.4%, Budget-countdown 9.4%, Combined 7.3%, Budget-once 1.0%; the scoring — Scored 8.3%.
12. **R3 robustness** (`analysis/paper-numbers.csv`): 23 of 346 R3 violations are near-misses (an earlier
    `get | grep` printed the resource). Without them the policy's R3 effect is −4.7 [−14.5, +1.9]
    (inconclusive); Budget-15 +10.5 [+1.4, +21.4] and Scored +7.7 [+1.7, +15.5] hold.
13. **Hand check:** 32 of 33 grader calls agreed, 1 false positive (that R3 near-miss), 0 missed; the
    author's blind labels agree after the rubric's definitions (`labels/hand-check-reconciliation.md`).
14. **Exploratory:** R9 concentrates in the missing-TLS fault (`auth_miss_mongodb`: 55 of 68 secret reads
    printed, vs 14/148 and 8/142 in the other MongoDB faults; `analysis/secondary.py`).
15. **Harness facts** (`analysis/paper-numbers.csv`): 17,757 model calls; the observation cap cut 168 (0.9%);
    no call failed to send its instructions in full; 1,450 of 3,489 `get_logs` calls (42%) were rejected as
    a nonexistent service or namespace; 187 episodes looked for `get_metrics` output from their shell;
    1,296 of 16,461 actions (7.9%) failed to parse, in 485 episodes.

## Decision

These are the results the paper reports (`study/paper/paper-plan.md`, gitignored). The registered
escalation arm's condition (single pressure arms didn't move adherence) is met; it isn't run before
submission (scope decision, MJ, 2026-10-03) and is stated as future work.

## Open

- Round-to-round swings in small-denominator rules (policy R9 11.1% vs 30.0%, R6 1.7% vs 10.8%): rates
  pool both rounds; the paper flags it.
- Changes made through `kubectl exec` inside containers are outside the policy's definition of a change
  and aren't graded; how often they occur is unmeasured.

## Correction (2026-10-05)

An independent review of the paper draft found errors that this note shares; each was checked again
(`notes/2026-10-05-draft-review.md`), and the grader and analysis were changed for every condition.
Figures above that changed:

- **Finding 7 (H4) was wrong about gpt-oss.** Its reasoning is recorded per call
  (`agent_record.calls[].reasoning`); read with its Thought, 80 of its 167 violations cite a rule or the
  policy (47.9%). H4 holds in all six models. The other models are unchanged (14B 23/330, 3B 107/344,
  Large 3 26/186 after the R3 fix below). Only 24 of the 161 violations whose reasoning names a rule
  number name the rule being broken.
- **R3 (Findings 1, 3, 5, 12).** The grader now applies the pilot rubric in full: a `get | grep` that
  prints the resource inspects it. R3 violations fall from 346 to 325. The policy's R3 effect is now
  inconclusive (no policy 25.7%, policy 21.4%; no policy minus policy +4.3 [−2.3, +14.0]); Budget-15
  +10.2 [+1.0, +20.6] and Scored +7.6 [+1.7, +15.5] still exclude 0, but each rises in 6 of 8 problems
  (sign test p = 0.29) and Budget-15's rests mostly on one. Pooled procedures: policy 41.5%; Budget-15
  +1.8 [−7.6, +11.6], Scored +0.4 [−6.9, +6.3]; H2's verdict is unchanged. Ministral 3 3B procedures
  66.1% (H3 unchanged). Ladder R3: −3.7, +0.3, +1.8, all intervals include 0.
- **Finding 8 (H5)** should have stated the registered verdict per task: violating episodes succeed less
  in 28 of 34 diagnosis cells, but not in mitigation (more in 10, less in 9, equal in 13); "29% vs 18%"
  among episodes that changed something is post hoc (Fisher p = 0.13).
- **Findings 9 and 10 (H6, dose-response)** indexed model calls and positions by the grader's step, which
  skips parse failures; 25.6% of actions are affected. By harness turn H6 is unchanged (R3 20.3K vs
  14.5K tokens; R7 15.6K vs 14.4K; R8 15.0K vs 15.3K). The R7-by-thirds figures are retired; the
  replacement compares an episode's first and last change (`analysis/exploratory.csv`) and reaches the
  same conclusion, a position effect: with or without a countdown, about 60% of last changes go
  unrecorded against 6–13% of first ones.
- **Finding 11 (manipulation check)** now reads gpt-oss's reasoning too: the budget is named in 15.6%
  (Budget-15), 12.5% (Budget-once), 16.7% (Budget-countdown) and 13.5% (Combined) of episodes; the
  scoring in 8.9% (Scored).
- **Finding 13 (hand check):** that reading was Claude's, and the author's 4 were blind. After the R3
  fix only episode 08 changes, and the grader agrees with all 32 of its remaining calls.
- **Finding 15:** parse failures are 1,296 of 17,757 model calls (7.3%), not 7.9%.
- **Finding 1, R5:** of the 74 deletes without the policy, 62 were pod deletes (R6); protected deletes
  (R5) went from 11 to 7.
