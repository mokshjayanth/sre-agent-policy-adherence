---
date: 2026-09-13
type: investigation
status: current
evidence:
  - third_party/aiopslab/aiopslab/observer/metric_api.py:139-145 (constructor starts the port-forward)
  - third_party/aiopslab/aiopslab/observer/metric_api.py:327,373 (query, then cleanup() after the loop)
  - runs/_legacy/day1-boot-run2 (failed get_metrics)
  - runs/2026-09-13T194534Z_validation-scripted (failed get_metrics, process hung at exit)
  - runs/2026-09-13T200318Z_validation-scripted (failed get_metrics, hang captured with a stack dump)
  - runner/harness_fixes.py stop_leaked_port_forwards (committed with this note)
---

# Why get_metrics sometimes fails, and why those runs hang at exit

## Question

Two validation batches finished their problem, printed "Done", and then the Python process
never exited. Why, and does the same cause change what agents see?

## What we checked

- Reran the batch with `PYTHONFAULTHANDLER=1` under `timeout -s ABRT`, so the hang dumped every
  thread's stack into the log.
- Read `PrometheusAPI` (`aiopslab/observer/metric_api.py`), `TraceAPI`
  (`aiopslab/observer/trace_api.py`) and `get_metrics` (`aiopslab/orchestrator/actions/base.py:115-137`).
- Classified the observation after every recorded `get_metrics` call as metrics or error, and
  compared it with each run's TTD.

## Findings

**The hang.** The stack dump shows the main thread in `threading._shutdown`, waiting on two
threads looping in `PrometheusAPI.print_output` (`metric_api.py:165`). `get_metrics` creates a
`PrometheusAPI`, whose constructor starts `kubectl port-forward` (`metric_api.py:145`, `192`)
and two non-daemon threads that read its output until `stop_event` is set (`metric_api.py:200`,
`203`). `export_all_metrics` sets it through `cleanup()` only after the query loop
(`metric_api.py:327`, `373`). When a query raises, cleanup never runs, the threads never stop,
and the process can't exit. The orchestrator still catches the exception and hands it to the
agent as the observation, so the run itself finishes normally.

`TraceAPI` uses the same fields and thread pattern (`trace_api.py:23-24`, `115-126`, cleanup at
`248` and `314`). Whether its failure path leaks the same way is unverified.

**The failure behind it.** In the failed runs the first query was refused on `localhost:32000`
(`HTTPConnectionPool(host='localhost', port=32000): Max retries exceeded …`), even though the
harness had printed "Port forwarding established successfully." Why the forwarded port refused
connections is unverified. Each failure came right after Prometheus was freshly deployed, but
so did three of the successes.

**How often.** `get_metrics` failed in 3 of the 7 runs recorded so far, and TTD separates the
two outcomes cleanly:

| Run | get_metrics | TTD (s) |
|---|---|---|
| `runs/_legacy/day1-boot-run1` | metrics | 3.33 |
| `runs/_legacy/day1-boot-run2` | error | 9.12 |
| `runs/_legacy/day2-manifest-validation` | metrics | 3.39 |
| `runs/_legacy/2026-09-13T190612Z_runner-validation` | metrics | 3.22 |
| `runs/2026-09-13T194534Z_validation-scripted` | error | 9.12 |
| diagnostic rerun (scratch folder, not kept) | metrics | 3.23 |
| `runs/2026-09-13T200318Z_validation-scripted` | error | 9.18 |

**What it does to measurements.** A failed call adds roughly 6 s of TTD, so the Day-1 TTD gap
(3.33 vs 9.12 s) was this failure. For an agent, the tool returns an error message instead of a
metrics listing: the observation differs in kind, not just length, which can change what the
agent reasons from.

**A second leak: orphaned kubectl.** The harness starts the port-forward with `shell=True`
(`metric_api.py:192`), and `/bin/sh` here is dash, which forks the command instead of replacing
itself with it: `sh -c "sleep 30"` runs `sleep` as a child, and killing the shell leaves `sleep`
running. So terminating the port-forward process, which both the harness's own
`stop_port_forward` (`metric_api.py:220`) and the first version of the runner fix did, kills
only the shell. In a test that forced the failure by occupying port 32000, the batch process
exited with `kubectl port-forward svc/prometheus-server 32001:80 -n observe` still running under
PID 1. Whether the harness's own cleanup leaves kubectl behind after a successful query is
unverified.

## Decision

- After each problem, `runner/run_batch.py` stops any port-forward a harness object left running:
  it sets the object's `stop_event`, terminates the shell's `kubectl` child and then the shell,
  and joins the reader threads. It records the count as `leaked_port_forwards` in `index.jsonl`.
  A non-zero count marks a problem whose metrics or traces call failed. The harness itself stays
  unmodified.
- Dated corrections appended to `2026-09-12-scoring-surface-audit.md` and
  `2026-09-13-harness-pin-coverage.md`, which had attributed these differences to jitter.

## Open

- Why the forwarded port refuses connections, and whether waiting for Prometheus to be ready
  before the agent loop would prevent it. Doing that would change the environment relative to
  vanilla AIOpsLab, so it is a study-design decision, not a bug fix.
- With a real LLM agent, how often a failed `get_metrics` changes the trajectory. Count failures
  per condition so they can't bias a baseline-versus-trained comparison.

## Correction (2026-09-13): the cause is a port collision, not readiness

The finding above left the refused connection unexplained, and Open floated Prometheus
readiness. The harness's own logs show a port collision instead. `PrometheusAPI` forwards the
first free local port from 32000 (`metric_api.py:142`, `find_free_port` at `156-161`), but its
query client is built from the URL `get_metrics` passes, which is always
`http://localhost:32000` (`metric_api.py:146`, `actions/base.py:115-129`). In every run whose
`get_metrics` failed, kubectl logged `Forwarding from 127.0.0.1:32001`; in every successful run,
`127.0.0.1:32000`.

What held 32000: even when the query succeeds, `stop_port_forward()` terminates only the
`sh -c` wrapper, so kubectl keeps listening. After `runs/2026-09-13T204443Z_smoke-scripted`
succeeded, `kubectl port-forward svc/prometheus-server 32000:80 -n observe` was still running
under PID 1 and listening on 127.0.0.1:32000. That settles the question above: the harness's
own cleanup does orphan kubectl on the success path. Why a port that looked taken when the next
run started then refused its query is still unverified.

Decision, replacing the readiness idea: before and after every problem, `runner/run_batch.py`
stops kubectl processes running exactly one of the harness's port-forward commands and records
`stale_port_forwards` and `orphaned_port_forwards` in `index.jsonl`. In
`runs/2026-09-13T210625Z_validation-scripted-sweep`, three problems ran back to back in one
process: each post-problem sweep stopped one orphan, kubectl forwarded 32000 every time, and all
three `get_metrics` calls returned metrics (TTD 3.22–3.32 s). No readiness wait is needed.
