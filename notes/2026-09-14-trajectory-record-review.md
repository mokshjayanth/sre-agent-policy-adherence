---
date: 2026-09-14
type: audit
status: current
evidence:
  - runs/2026-09-14T101254Z_smoke-qwen3-32b-react-thought (the reviewed trajectory)
  - runs/2026-09-14T091300Z_smoke-qwen3-32b-fix, runs/2026-09-14T095605Z_smoke-qwen3-32b-react
  - third_party/aiopslab/aiopslab/orchestrator/parser.py:16-18, :66-70
  - third_party/aiopslab/aiopslab/orchestrator/actions/base.py:94-96
  - third_party/aiopslab/aiopslab/orchestrator/orchestrator.py:157-205
  - third_party/aiopslab/aiopslab/session.py:90-101
  - third_party/aiopslab/aiopslab/orchestrator/problems/registry.py
  - notes/2026-09-12-scoring-surface-audit.md (Q2, Q3)
---

# Can a trajectory record support adherence grading and T1 training data?

## Question

An independent review, written with the research vault in context, read the trajectory from
`runs/2026-09-14T101254Z_smoke-qwen3-32b-react-thought`. It concluded that the action stream
is gradeable, but that the file can't support the paper: it doesn't record what the agent was
instructed, or which model and settings produced it. This note records which of its claims
hold against the code and data, and what changed because of them.

## What we checked

- The reviewed `trajectory.json`: its keys, roles, the type of `results.history`, the final
  env message, each assistant turn's Thought and action, and pod names in observations.
- The same pod names in the two earlier Qwen3-32B smoke batches listed in the evidence.
- The harness's parser (`parser.py`), the `exec_shell` action (`actions/base.py`), and the
  orchestrator loop and session timer (`orchestrator.py`, `session.py`).
- Problem registry keys, read without constructing any problem (construction touches the
  cluster; see `notes/2026-09-14-agent-prompt-and-context.md`, Finding 6).
- `grep` for `random`, `np.random` and `seed` in `aiopslab/generators` and
  `aiopslab/orchestrator/problems`.
- `batch.json` fields from commits `ae3b38b`, `fee0a1f` and `5518a9e`.

## Findings

1. **Actions are recoverable, and no parse failure disappears.** The trajectory has 10
   assistant turns, each a Thought plus one fenced action. The harness rejects any reply
   without exactly one fenced block (`parser.py:16-18`). The error goes back to the agent as an
   env message and is recorded, and `index.jsonl` counts these per problem
   (`runner/trajectory_checks.py`). The review's parser caveat, a regex over `Action:`,
   doesn't match the code. The real risk is a grader that parses differently from the
   executor. A command in an action also may not have run: `exec_shell` refuses `kubectl edit`,
   `edit svc` and `kubectl port-forward` by substring (`actions/base.py:94-96`).
2. **The trajectory didn't record what the model was told.** Its roles are only `assistant` and
   `env`. `batch.json` holds `prompt_sha256` (renamed `prompt_template_sha256` later on
   2026-09-14; see `notes/2026-09-14-step-budget-and-termination.md`), but that hashes the template constants
   (`DOCS + RESP_INSTR + THOUGHT_PLACEMENT`), not each problem's rendered prompt with its
   description, task instructions and API docs. The per-turn text appended to observations
   and what trimming sent weren't recorded either, and T1 training examples need exactly that.
   No run has had a policy yet, so no policy-bearing run lacks it.
3. **Provenance lived only at batch level.** `batch.json` records model, sampling settings,
   prompt hash, serving endpoint and host, and resume refuses to mix them (commits `fee0a1f`,
   `5518a9e`). A trajectory copied out of its batch folder carried only
   `agent_name: "openai-compatible"`.
4. **Runs can't repeat, and there's no seed to fix.** The `grep` above finds nothing, as the
   2026-09-12 audit's Q2 found. The geo pod's name suffix was `qb72m`, `m9d5k` and `dh89n` in
   the three smoke batches, and timestamps and metrics directory names vary too. With sampling
   at temperature 0.5, several samples per problem are needed. Direct evidence:
   `runs/2026-09-14T114820Z_smoke-qwen3-32b-record` repeated the reviewed batch with the same
   model, prompt hash (`a06bc4256898`), sampling settings and context limit. Its first action
   already differed (service name `"hotel-reservation"` instead of `"Hotel Reservation"`). It
   then read logs service by service, never inspected the geo pod, and ran out of its 10 steps
   without submitting (`Invalid Format`), where the reviewed run scored `Correct`. The review's suggestion to fix a
   fault-injection seed doesn't apply. The audit's claim that actions reproduced came from the
   fixed-sequence scripted probe; a correction is appended there.
5. **`results.history` is a broken duplicate.** It is a list of Python repr strings, because the
   harness returns session objects that JSON serialisation turns into `str`, and it repeats the
   top-level `history`.
6. **No cluster-state record.** Grading, fault recovery and app deletion all happen inside
   `start_problem` (`orchestrator.py:179-205`), so the runner can't snapshot state between the
   last action and teardown without wrapping the problem's `eval`.
7. **Problem IDs don't parse cleanly into fault type and app.** 89 IDs are registered; 2 are
   excluded, leaving 87 in scope (`runner/problem_sets.py`), not 86. 82 fit
   `<prefix>-<task>-<variant>`. Seven don't: `container_kill-detection`,
   `container_kill-localization`, `flower_node_stop-detection`,
   `flower_model_misconfig-detection` and three `noop_detection_<app>-1`. Six prefixes name no
   app: `k8s_target_port-misconfig` (12 IDs), `auth_miss_mongodb`, `revoke_auth_mongodb`,
   `user_unregistered_mongodb`, `redeploy_without_PV` and `wrong_bin_usage`. Task type does
   parse by substring for all 89 (detection 34, localization 28, mitigation 14, analysis 13).
   The registry maps IDs to 58 classes and 31 lambdas, which resolve to 28 problem modules,
   readable without constructing anything.
8. **TTD includes the model's own time.** The session timer starts before the agent loop
   (`orchestrator.py:157`), model calls happen inside it (`:162`), and it stops after the loop
   (`:183`). Grading gets that duration (`:188`, `session.py:98-101`). TTD therefore mixes in
   serving latency, and B3 on the gateway can't be compared on TTD with B1, T1 and T2 on local
   vLLM.
9. **The run's efficiency is worse than necessary, but not as bad as the review says.** The
   port mismatch (27777 against 27017) is already stated in the Thought of action 5. Actions 5–7
   (`get_metrics`, two network-bytes `read_metrics`) added nothing; actions 8–9 (`kubectl get
   svc`, re-reading geo logs) confirmed the diagnosis; action 10 submitted. That's three wasted
   steps, not six. For a Yes/No detection task, "Yes" was already justified by action 3 (the geo
   pod in `Error` with one restart). The submission landed on step 10 of a 10-step cap, so this
   run can't show whether the agent would have kept going. The review's paper point stands:
   efficiency deltas after post-training may measure "stopped flailing".

## Decision

Recording only; nothing changes what the agent sees or how it's graded:

- `trajectory.json` now carries `batch_id`, `condition` and `agent_description`, so it
  describes itself outside its batch folder (`runner/run_batch.py`, `_trajectory`).
- It carries `agent_record` for agents that expose `record()`. `OpenAICompatibleAgent` returns
  every message it sent, including the rendered system prompt, task instructions and per-turn
  suffixes, plus one entry per model call: messages in history, the first turn sent, and
  whether the last message was truncated (`agents/openai_compatible.py`, `trim_summary`).
- The `history` copy inside `results` is dropped.
- The 2026-09-12 audit gets a dated correction to Q2.
- TTD is not an efficiency measure across serving stacks; compare steps and tokens instead.

Trajectories written before this change lack these fields. Only smoke and validation batches
exist, so no condition's data is affected.

## Open

- An adherence grader that calls the harness's `ResponseParser` and reads env responses, with
  rules over shell command strings. Deferred until grading work starts.
- A recording-only snapshot of cluster state at `eval`, before any mitigation batch. Until
  then, blast-radius claims stay out of the paper.
- The fault-family table, built from registry class modules rather than ID strings.
- How many samples per problem each condition needs, given Finding 4.
- What localization, analysis and mitigation problems return as results. None has run yet.
