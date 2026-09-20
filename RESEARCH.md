# Research design

**Last updated:** 2026-09-16 · **Owner:** MJ

The research design decisions currently in force. Evidence for each is in the linked notes.
Changes are appended as dated `## Correction` sections, and git history keeps every revision.

## Research question

What does success-optimising post-training do to an SRE agent's adherence to an instructed
operational policy that the training reward does not enforce? Measure the change, not the
level. The question grew out of planning that began in August 2026.

Why it's open: work that post-trains SRE agents optimises task success and doesn't measure
compliance (AOI, arXiv:2603.03378), and work that measures compliance doesn't train (SOCpilot,
arXiv:2605.05501; OpenSec, arXiv:2601.21083). REDAgentBench (arXiv:2608.10669) describes
violations that follow the agent stating the constraint, the recognition–execution gap.
JourneyBench (arXiv:2601.00596, identifier unverified) names training for adherence as
unexplored.

## Decisions

### D1. Environment: AIOpsLab

AIOpsLab, pinned as the `third_party/aiopslab` submodule, on a kind cluster created from
`configs/kind-config-x86.yaml` (`CLAUDE.md`). Chosen over building a custom incident environment:
SRE agent benchmarks already exist; AIOpsLab runs on a live cluster, with a mitigation tier in
which agent actions change state; and the policy layer is a prompt plus detectors, so it doesn't
need an environment of its own. Workarounds for harness bugs are confined to
`runner/harness_fixes.py`.

### D2. Scope and split

- In scope: detection, localization and mitigation problems; analysis is out. Adherence is scored
  on the action stream across all in-scope task types.
- Split by fault type, adopting AOI's published partition: 31 training and 41 test problems in
  scope, recorded per problem in `configs/problem-table.csv`. The claim is worded as "unseen fault
  types, seen injection mechanisms". The no-op problems are reported separately, as a false-alarm
  check (`notes/2026-09-14-fault-type-split.md`).
- Tuning and model selection use training-split problems only. There is no validation set.
- Counts come from the pinned registry (89 registered, 87 without the two Flower problems), not
  from the literature.

### D3. Conditions

Every condition runs through the same unchanged instrument (D4).

| Condition | Definition | Role | Status |
|---|---|---|---|
| B1 | Qwen3.5-4B, plain prompting, served locally with vLLM | Floor | Chosen (`notes/2026-09-14-b1-model-trial.md`) |
| B2 | B1's model with engineered prompting | The "just prompt better" control; required | Not designed |
| B3 | An open-weight model whose licence allows training on its outputs, built-in thinking off | Ceiling reference; source of T1's training data | Shortlist: Kimi-K2.5, GLM-5 |
| T1 | B1's model with LoRA SFT on successful B3 trajectories | First training rung | Not started |
| T2 | T1 with GRPO | Second training rung | Reward open (O1) |

- B1 is larger than the 1–3B size first planned: the only 1–3B candidate tested, Qwen3.5-2B,
  didn't produce actions the harness can parse.
- T1 and T2 settings are fixed before training, following AOI: LoRA rank 64, alpha 128, learning
  rate 1e-5, GRPO group size 4, batch 16, 3 epochs. Only the final checkpoint is evaluated, and
  nothing is chosen on adherence (`notes/2026-09-14-operational-policy-v1.md`).
- Training data comes only from runs of this instrument.

### D4. Instrument

- The agent (`agents/openai_compatible.py`) follows AIOpsLab's ReAct client, with four changes
  applied identically to every condition: a per-turn line showing the action fenced, a
  64,000-token context limit, a 16,000-token cap on each observation, and system and task
  messages that are never trimmed (`notes/2026-09-14-agent-prompt-and-context.md`,
  `notes/2026-09-14-observation-cap-and-context-budget.md`, `notes/2026-09-14-b1-model-trial.md`).
- Sampling follows AIOpsLab's reference client: temperature 0.5, top_p 0.95, 1,024 output tokens.
  Episodes run for up to 30 steps (`notes/2026-09-14-step-budget-and-termination.md`).
- Every batch records its environment, and every episode records the messages the model received
  and how the episode ended (`README.md`, `notes/2026-09-14-trajectory-record-review.md`).

### D5. Policy layer

- The policy is instructed in the prompt and enforced neither by the environment nor by grading.
  It is identical for every condition.
- Every rule is checkable mechanically from the action stream, and no rule may make a known fix
  impossible.
- Violations are counted per opportunity, or per episode for per-episode obligations. Attempts
  count, with executed and refused attempts recorded separately.
- The current text, `policy/draft-v1.txt`, is a draft (O3)
  (`notes/2026-09-14-operational-policy-v1.md`).

### D6. Metrics

- Success: avg@k as the headline and best@k as secondary, over 5 runs per problem.
- Adherence: violation rate per rule and per opportunity, for each condition.
- Also reported per condition: how episodes end, steps, tokens, and how often the observation cap
  fired. TTD is not compared across serving stacks.
- Blast radius is not measured until post-episode cluster state is recorded.

### D7. Rejected alternatives

- Enforcing the policy architecturally, as AOI does with role separation and a command whitelist:
  it would remove the variable under study.
- LLM-judge step rewards, and AOI's Compressor and Evolver: each adds a model to the loop.
- Qwen3-14B for the ladder: training at this agent's context length exceeds one 48 GB GPU. An
  inference-only run could later connect results to AOI's.
- Closed API models as the source of T1's training data, because of terms on training with their
  outputs.
- An instance-level split, which leaks variants of a fault; a mechanism-level split, which would put
  whole apps on one side.
- Agent traces from outside this instrument as training data: uncontrolled provenance.

### D8. Standing rules

- Negative results are results.
- The policy layer and B2 are never cut.
- Hypotheses and design choices are committed before the results they concern, and nothing is
  backdated.

## Open decisions

- **O1. T2's reward:** task success only, or success combined with adherence. The research question
  concerns a policy the reward does not enforce.
- **O2. Pre-registered hypotheses,** committed before any policy run.
- **O3. The policy's final text and placement.** Proposed placement: appended to the system message.
- **O4. B2's design,** and B3's choice after a short trial on training-split problems.
- **O5. Whether T2 fits one 48 GB GPU** with vLLM's sleep mode, to be measured on the g6e.
- **O6. `redeploy_without_pv`'s fix path** against the policy's namespace-scope and deletion rules.
- **O7. Instrumentation not yet designed:** post-episode cluster state (for blast radius) and
  gameability probes.

## Correction (2026-09-16): an evaluation-only first study

Evidence and reasoning: `notes/2026-09-16-evaluation-only-scope.md`.

- **Research question.** For the first study, replaced by: how does pressure toward task success
  change an SRE agent's adherence to an instructed operational policy that task scoring does not
  enforce, and does the change depend on the kind of rule? Measure the change, not the level. The
  post-training question above is kept as a possible second study and is not scheduled.
- **D2.** The fault-type split no longer separates training data from evaluation data. Design work
  (policy text, pressure variants, pilots) still uses training-split problems only. Whether the
  main evaluation covers all in-scope problems or only the test split is open (O9).
- **D3.** The ladder (B1–T2) is retired for the first study. Conditions are models × prompt
  variants: no policy, policy, and pressure with and without the policy. Models are chosen across
  sizes by the format floor and cost per episode (O8). B2's role, answering "just prompt better"
  against trained conditions, no longer applies.
- **D5.** The policy text in use is `policy/draft-v2.txt` (`notes/2026-09-15-premise-check-pilot.md`).
  A revision is planned so that each rule's scope by task type can't be misread (O3).
- **D6.** Harness success is reported next to adherence, and problems whose success check doesn't
  discriminate are identified and reported separately. Runs per problem are set within budget (O8).
- **D7.** Added: post-training in the first study, because it depends on decisions and hardware not
  in place (O1, O5).
- **D8.** "The policy layer and B2 are never cut" becomes "The policy layer is never cut."
- **Open decisions.** O1 and O5 are parked with the second study. O4 is replaced by O8. Added:
  - **O8. Models and runs per problem,** within the Bedrock credit.
  - **O9. The evaluation problem set:** all in-scope problems, or the test split only.
  - **O10. Pressure manipulations,** shown to change behaviour in a replay or mini-pilot before the
    main runs.
  - **O11. The grader** for the main runs, validated against the pilot labels.

## Correction (2026-09-18): the evaluation problem set (O9)

Evidence and reasoning: `notes/2026-09-18-mitigation-check-discrimination.md`.

- **O9 decided.** The main evaluation uses eight mitigation problems whose success checks fail when no
  fix is made, excluding the three used in the pilot: `k8s_target_port-misconfig-mitigation-2` and `-3`,
  `auth_miss_mongodb-mitigation-1` (train); `revoke_auth_mongodb-mitigation-1` and `-2`,
  `user_unregistered_mongodb-mitigation-1` and `-2`, `wrong_bin_usage-mitigation-1` (test). Results are
  reported by split.
- **D6.** Excluded because their checks pass with no fix: `misconfig_app_hotel_res-mitigation-1`,
  `assign_to_non_existent_node_social_net-mitigation-1`, `redeploy_without_PV-mitigation-1`. Excluded
  because it didn't deploy: `astronomy_shop_kafka_queue_problems-mitigation-1`. O6 is moot while
  `redeploy_without_PV` is excluded.

## Correction (2026-09-19): paired localization problems, and a stretch sweep

Decided by Moksh Jayanth on 2026-09-19. Evidence for the problem choice:
`notes/2026-09-18-mitigation-check-discrimination.md`; pressure texts:
`notes/2026-09-16-pressure-variants.md` (correction of 2026-09-19).

- **O9 revised.** The main evaluation adds the localization problems for the same eight faults:
  `k8s_target_port-misconfig-localization-2` and `-3`, `auth_miss_mongodb-localization-1` (train);
  `revoke_auth_mongodb-localization-1` and `-2`, `user_unregistered_mongodb-localization-1` and `-2`,
  `wrong_bin_usage-localization-1` (test). Each fault is then either diagnosed or fixed: diagnosis tasks
  carry the observe-only rules, mitigation tasks the change rules. Localization's check requires
  naming the faulty service, so it can't pass by default.
- **D5.** Instructed texts are chosen per task type: `policy/draft-v3-mitigation.txt` or
  `policy/draft-v3-diagnosis.txt`, and pressure texts that are true of how each type is scored. Placement
  is unchanged (system message).
- **Stretch goal, only if time remains after the main runs:** every in-scope problem, all four task types
  including analysis, with the plain prompt and one run per model, reported as capability context. Neither
  it nor the main runs are comparable to AIOpsLab leaderboard results, which use different agents.

## Correction (2026-09-20): the main study is pre-registered

Design, hypotheses and analysis plan: `notes/2026-09-20-main-study-preregistration.md`, committed before
the first main episode.

- **D6.** Runs per problem: 2, not 5, in two rounds across all cells. avg@k and best@k are reported over
  those 2 runs; uncertainty comes from bootstrapping over problems. Added measures: Completion under
  Policy, the recognition rate, and attempts against executed changes.
- **D3.** Conditions for the main study are `main-<model>-<variant>` over five models and four variants:
  no policy, policy v3, policy v3 + P-budget, policy v3 + P-scored.
- **D5.** The policy in force is `policy/draft-v3-{task}.txt`; adherence is graded by `grading/`, frozen
  at the commit each batch records (O11).
- **Open decisions closed:** O2 (hypotheses), O8 (models and runs), O10 (pressure manipulations),
  O11 (the grader). O3 closes for this study with policy v3.
