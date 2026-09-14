---
date: 2026-09-12
type: audit
status: current
evidence:
  - commit e55386b (scripted probe agent used for these runs)
  - runs/_legacy/day1-boot-run1
  - runs/_legacy/day1-boot-run2
  - third_party/aiopslab/aiopslab/orchestrator/problems/registry.py
---

# Day 1 — scoring-surface audit

Date: 2026-09-12. Harness: AIOpsLab @ `ddf7e40619689dad75eaf8f2174e263c4157ec76` (pinned in
[`CLAUDE.md`](../CLAUDE.md)). Cluster: local `kind` (2 nodes, `jacksonarthurclark/aiopslab-kind-x86`).

## Reference-agent substitution

No AWS/Bedrock or other LLM credentials are available in this environment (`aws sts
get-caller-identity` → `NoCredentials`; no `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/etc.; no
Bedrock-capable client exists in `third_party/aiopslab/clients/`). The boot + audit runs
below used [`agents/scripted_probe.py`](../agents/scripted_probe.py) instead: a
fixed, seedless `get_logs -> get_metrics -> submit("Yes")` sequence. It exercises the harness
plumbing end to end but is **not** a policy-adherence baseline and must not be treated as one.
The overnight ~20-task Bedrock detection run from the Day 1 plan is still blocked on
credentials.

## Boot: one scenario, unmodified, end to end

Problem: `misconfig_app_hotel_res-detection-1` (Detection, HotelReservation app, `geo`
service misconfigured). Ran twice, back to back, same scripted agent, same cluster:

| | run 1 | run 2 |
|---|---|---|
| session id | `3ce883b1-...` | `ad916841-...` |
| solution | `Yes` | `Yes` |
| Detection Accuracy | Correct | Correct |
| TTD (s) | 3.33 | 9.12 |
| action sequence | get_logs, get_metrics, submit | get_logs, get_metrics, submit |

Raw records: `runs/_legacy/day1-boot-run1/trajectory.json`, `runs/_legacy/day1-boot-run2/trajectory.json`
(gitignored — telemetry, not source), plus AIOpsLab's own dump under
`third_party/aiopslab/aiopslab/data/results/<session_id>_<ts>.json`.

One real hurdle, not a design problem: the vendored `kubectl.py` and `shell.py` hardcode the
cluster name `kind` (kubeconfig context `kind-kind`, control-plane container
`kind-control-plane`). This sandbox already had an unrelated, empty `kind` cluster sitting
around; naming the AIOpsLab cluster anything else (I first used `aiopslab`) causes a silent
split-brain — Helm/kubectl-CLI calls hit the right cluster via the ambient kubeconfig context,
but AIOpsLab's own Python client hits the other one, producing confusing "namespace not found"
errors right after "namespace created successfully". Fix: the kind cluster for AIOpsLab must
be created with the default name (`kind create cluster --config ...`, no `--name`). Recorded
here since it'll bite anyone else standing this up in an environment with a stray `kind`
cluster already present.

## Q1 — Is the full tool-call sequence recoverable from a completed run?

**Yes.** Both our own trajectory JSON and AIOpsLab's native `Session.to_json()` dump contain
the complete `role`/`content` history: every agent action verbatim (including arguments),
every environment response, the submitted solution, and the final eval result. Nothing about
the harness's session model loses information needed to reconstruct an action-level trace.
This is the gate question from the Day 1 plan, and it passes — the adherence measurement has
something to score.

## Q2 — Does a fixed seed reproduce?

**There is no seed to fix.** `grep -rn seed` across `aiopslab/generators` and `aiopslab/orchestrator`
returns nothing, and neither the fault injectors nor `Wrk` (workload generator) expose a seed
parameter — confirmed by reading `inject_app.py` and `wrk.py` directly. Faults themselves are
deterministic (fixed target service, fixed fault type per problem — no `random.choice` anywhere
in `generators/fault/`).

Empirically, running the identical scenario twice back to back reproduced the **action-level
trace and the correctness outcome** exactly (same 3 actions, same submitted answer, same
"Correct" verdict). It did **not** reproduce wall-clock-derived numbers: TTD went from 3.33s to
9.12s, and the log/metrics text returned by the environment differed enough to shift the
default `in_tokens` count from 583 to 670. That's real infrastructure timing jitter (pod
readiness, wrk2's `exp` request-timing distribution), not a controllable RNG — there's nothing
to seed because nothing is seeded.

Implication for the adherence scoring design: the action stream and pass/fail outcome are
trustworthy to diff across runs; TTD and any other wall-clock/byte-count-derived metric are not
comparable run-to-run without normalization and should not be used as an identity or
reward signal on their own.

## Q3 — Do problem IDs map cleanly to fault types?

**Mostly, but the ADR's own instance counts don't match the registry at the pinned commit.**
Live (uncommented) entries in `aiopslab/orchestrator/problems/registry.py`:

```
total: 89   detection: 34   localization: 28   analysis: 13   mitigation: 14
```

ADR v3 claims 86 (32 / 28 / 13 / 13), described as "88 less 2 deprecated." That doesn't
reconcile cleanly against what's actually in the registry:

- Excluding the 2 `flower_*` problems (the only Docker-deployed, non-k8s entries) gets
  Detection to 32 and matches the ADR there — but total becomes 87, not 86, and Mitigation is
  still 14, not 13.
- 3 `noop_detection_*` entries inject no fault at all (negative controls, useful for false-positive
  rate but not a fault-type instance) — excluding those too drops Detection to 29 and total to
  84, overshooting past the ADR's numbers in the other direction.
- Far more than "2" are actually commented out and unavailable: 5 pairs of `operator_*`
  problems (10 IDs) plus `kernel_fault_hotel_reservation-*` and `disk_woreout-*` (4 IDs) are
  disabled in the registry with inline notes citing an open Chaos Mesh bug — 14 IDs, not 2.
- `container_kill-detection` / `container_kill-localization` are the only two live IDs without
  the `-N` instance suffix every other problem uses; worth confirming they're intended
  permanent members of the suite and not a leftover template before folding them into a
  fault-type split.

None of this blocks scoring — every live problem file has exactly one fault-injector class and
one hardcoded `fault_type` string, so a problem-ID → fault-type table is mechanical to build.
But the split should be built by reading the live registry directly (as above), not by reusing
the ADR's 86/32/28/13/13 figures, and the "88 less 2 deprecated" framing should be corrected
before it goes in front of anyone else — the real disabled count is 14, and the live total is
89 (87 if the two Docker-only Flower problems are excluded as out of scope for a k8s-only
benchmark).

## Gate verdict

Q1 passes without qualification. Q2 passes for what actually matters (action trace + outcome),
with a documented caveat about wall-clock metrics. Q3 surfaces a real bookkeeping gap in the
ADR that should be fixed before the AOI-style fault-type split is finalized, but doesn't
invalidate the approach. Recommendation: proceed past the gate; recompute the split from the
live registry; treat TTD/token-count fields as non-reproducible telemetry, not scoring signal.

## Correction (2026-09-13)

- **15 problem IDs are disabled, not 14.** The list above misses
  `redeploy_without_PV-localization-1`, commented out at
  `third_party/aiopslab/aiopslab/orchestrator/problems/registry.py:198` with no
  stated reason. The live total of 89 stands.
- **Only four of them sit under the Chaos Mesh comment.** That comment
  (`registry.py:165-167`) precedes the two `kernel_fault_hotel_reservation-*`
  and two `disk_woreout-*` entries (`registry.py:168-171`). The ten
  `operator_*` entries (`registry.py:207-216`) are commented out under a plain
  "K8S operator misoperation" header with no reason given.

## Correction (2026-09-13): the Q2 differences were a failed metrics call

Q2 put the differences between the two runs down to infrastructure timing. They were mostly
one failure. In `runs/_legacy/day1-boot-run2` the `get_metrics` call failed: its 375-character
observation is `HTTPConnectionPool(host='localhost', port=32000): Max retries exceeded …`, not
a metrics listing. Across all seven runs recorded so far, every failed `get_metrics` has a TTD
of 9.12–9.18 s and every successful one 3.22–3.39 s, so the 3.33 s vs 9.12 s TTD gap here is
that failure too. See `notes/2026-09-13-get-metrics-failures.md`.

What still holds: the action sequence and the verdict reproduced, and TTD is not a scoring
signal. What changes: the observation an agent receives can differ in kind, data versus an
error, and that is an environment fault to count and control for, not noise. The `get_logs`
length difference (596 vs 1402 characters) is unaffected.

## Correction (2026-09-14): identical actions here say nothing about reproducibility

Q2, and the correction above, say the action sequence and the verdict reproduced. Both runs
used `agents/scripted_probe.py` (see Reference-agent substitution), which always sends the same
three actions, so identical actions were guaranteed, not observed. The finding that there is no
seed to fix stands. For an LLM agent, observations differ between runs (the geo pod's name
suffix was `qb72m`, `m9d5k` and `dh89n` in three Qwen3-32B smoke runs; timestamps and metrics
directory names differ too) and sampling runs at temperature 0.5, so trajectories are expected
to diverge. See `notes/2026-09-14-trajectory-record-review.md`.
