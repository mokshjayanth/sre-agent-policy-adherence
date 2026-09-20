---
date: 2026-09-20
type: decision
status: current
evidence:
  - RESEARCH.md (question and corrections of 2026-09-16, 2026-09-18, 2026-09-19)
  - notes/2026-09-15-premise-check-pilot.md (pilot results, 2026-09-19)
  - notes/2026-09-16-pressure-variants.md (pressure texts, both parts of the manipulation check)
  - notes/2026-09-16-model-shortlist.md (format replay, whole-episode check)
  - notes/2026-09-18-mitigation-check-discrimination.md (problem choice)
  - notes/2026-09-16-related-work.md (A1, A2, A5, A6, A7, A8, B9, B10, B13, C19)
  - grading/ and tests/test_grading.py (the grader, 74 of 74 pilot labels)
  - policy/draft-v3-mitigation.txt, policy/draft-v3-diagnosis.txt
---

# What does the main study run, and how is it analysed?

## Question

Everything the main study needs is now decided or built: scope, problems, pressure variants, policy v3,
models and a grader. This note fixes what will be run and how it will be read **before any main episode
exists**, so the analysis can't be chosen to fit the data (`RESEARCH.md` D8; O2 was the last open
decision).

## What we checked

- The pilot's reconciled results and the two parts of the pressure manipulation check.
- The grader's agreement with the pilot's hand labels (74 of 74, no false positives).
- The whole-episode model check, which confirmed all five models act on both task types.
- Published findings that bear on the predictions below (`notes/2026-09-16-related-work.md`).

## Design, fixed here

- **Models (5):** `mistral.ministral-3-3b-instruct`, `mistral.ministral-3-14b-instruct`,
  `mistral.mistral-large-3-675b-instruct`, `qwen.qwen3-next-80b-a3b-instruct`, `openai.gpt-oss-120b`.
- **Problems (16):** the eight mitigation problems of `RESEARCH.md`'s 2026-09-18 correction and the eight
  localization problems for the same faults (2026-09-19 correction). Three train and five test faults,
  reported by split.
- **Variants (4):** no policy; policy v3; policy v3 + P-budget; policy v3 + P-scored. Texts are chosen per
  task type. P-budget runs with `--max-steps 15`, the others with 30.
- **Runs:** 2 per cell, in rounds: every cell's run 1, then every cell's run 2. 5 × 16 × 4 × 2 = 640
  episodes.
- **Conditions** are named `main-<model>-<variant>`; one batch is one model, one variant, 16 problems.
- **Settings:** temperature 0.5, top_p 0.95, 1,024 output tokens, 64,000-token context limit,
  16,000-token observation cap, as every earlier condition.

## Hypotheses

Committed before the first main episode. Each says what would refute it.

- **H1 (rule type).** With the policy, violation rates per opportunity are lower for prohibitions (R1,
  R2, R5, R6, R9) than for procedures (R3, R7, R8), in every model. *Refuted if* any model's procedural
  rates are at or below its prohibition rates. Pilot: prohibitions 0 of 8 restarts, procedures 26 of 29
  changes unrecorded.
- **H2 (pressure).** Pressure raises procedural violation rates against policy v3 alone, in most models.
  *Refuted if* rates are unchanged or lower under both pressure variants. The pilot's urgency line moved
  nothing, and part 1's screen was weak, so a null is a real possibility and will be reported as one.
- **H3 (scale).** Violation rates don't fall monotonically with model size within the Mistral family (3B,
  14B, Large 3). *Refuted if* they fall monotonically in every rule family. Grounded in ODCV-Bench's
  within-family scaling and PropensityBench's weak capability–propensity correlation.
- **H4 (recognition).** In every model, some violations follow a Thought that cites the rule or the
  policy (REDAgentBench's recognition–execution gap; DriftBench's knows-but-violates). *Refuted if* no
  model shows any.
- **H5 (violations don't pay).** Episodes with a violation don't succeed more often than episodes
  without, within the same model, variant and task type. *Refuted if* violating episodes succeed more.
- **H6 (context).** R3 and R8 violations occur at larger context sizes than compliant changes, while R7
  violations don't. From the pilot's within-episode check (R3 17.5K vs 6.6K tokens; R7 7.3K vs 6.9K).

## Analysis plan

- **Primary measure:** violations per opportunity, per rule, per model, per variant, per task type,
  graded by `grading/` at the commit recorded in each batch. Opportunities are as defined in the pilot's
  rubric.
- **Also reported:** *Completion under Policy* (a success that broke no rule; ST-WebAgentBench),
  harness success, steps, how episodes ended, parse failures, attempts against executed changes, and the
  recognition rate (a Thought citing a rule before violating it).
- **Uncertainty:** bootstrap confidence intervals over problems (the unit of resampling is the problem,
  not the episode). No significance test is reported for differences between models, because the same
  policy text can move models in opposite directions (SOCpilot); models are reported separately.
- **Exclusions, fixed now:** episodes that fail with a runner or harness error are re-run and the failed
  attempt is kept in the batch; episodes where a model produced no parseable action at all are reported
  as such, not dropped. Nothing is excluded on its adherence or success.
- **Hand check:** 20 episodes drawn at random after grading are read against the grader's rows, and the
  disagreement rate is reported. The grader is frozen at its commit before the main runs and any later
  change is applied to every condition and noted.
- **Pilot and main-study R8 rates are reported separately,** because v3 restates R8.

## Decision

Run it as above. `RESEARCH.md` gains a correction for 2 runs (D6 said 5), and O2, O8, O10 and O11 close
with this note.

## Open

- The stretch sweep (all task types, plain prompt, 1 run per model) stays a stretch goal.
- A second machine would halve the wall-clock time; not required.

## Addition (2026-09-20): a conditional pressure ladder

Registered before any round 1 data was read, and before any episode of the arms below exists.

**Why.** Part 1's screen was weak and neither single variant made agents hastier. Scheurer et al.
(arXiv:2311.07590, read in full) elicited misbehaviour with three simultaneous pressures and found it
"persists for all cases where only a single source of pressure is removed": the combination carried the
effect, not any one source. PropensityBench (arXiv:2511.20703, summary) escalates pressure over levels;
Instrumental Choices (arXiv:2605.06490) found single framing manipulations produced no comparable effect.
Our single arms may therefore be too weak a dose.

**Conditional rule.** After round 1 is graded, if neither pressure arm moves any rule's violation rate
against policy v3 alone by more than the bootstrap interval over problems, or if the pattern suggests a
dose effect worth mapping, two arms are added and run in both rounds:

| New arm | Sources |
|---|---|
| policy v3 + escalation | social/time only, the missing solo ablation |
| policy v3 + budget + scored + escalation | all three at once |

**Escalation** is a third pressure source: stakeholder messages appended to the observation at fixed
turns (after actions 4 and 8, plus 12 in 30-step arms), never mentioning the policy, scoring or any
instruction to cut corners. It is delivered during the episode, not in the system prompt, because static
framing is what the pilot's urgency line did and it moved nothing.

**Prediction.** Violation rates on procedural rules rise with the number of pressure sources, highest in
the three-source arm; prohibitions stay near zero. *Refuted if* the three-source arm matches policy v3
alone.

**What this costs in pre-registration terms.** The arms are decided after seeing round 1, which is
sequential design, not a post-hoc analysis choice: their prediction and analysis are fixed here, before
their episodes exist, and the analysis of the existing arms is not revisited. The paper states that the
ladder was extended on evidence.

**Also registered now: a within-episode dose-response analysis.** In budget arms, whether the violation
rate per opportunity rises as the countdown falls (actions remaining), which tests the pressure
mechanism with far more data points than the between-arm comparison and survives a between-arm null.
