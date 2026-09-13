# Harness pinning — hardening beyond the commit hash

Follow-up to [`day1-scoring-surface-audit.md`](day1-scoring-surface-audit.md) and the
CLAUDE.md commit pin. The commit hash only proves which *code* is checked out; this covers
what it doesn't.

## What's actually floating, checked against the code (2026-09-13)

**Correction, not a new finding against anyone else's claim:** an earlier pass through this
checked `aiopslab-applications/hotelReservation/helm-chart/`'s `values.yaml` files and
concluded `consul`/`memcached` were version-pinned there (`1.13.2`, `1.6.17`). That chart is
never actually used. `HotelReservation` sets `self.helm_deploy = False`
(`aiopslab/service/apps/hotelres.py`) and deploys via `kubectl.apply_configs` against raw
manifests at `aiopslab-applications/hotelReservation/kubernetes/` instead — a completely
different, unpinned set of YAML files living next to the unused Helm chart. Caught this by
diffing what `agents/run_manifest.py` recorded from the *actual running pods* against what the
chart values implied; they didn't match at all. Lesson: for this app, only pod-level
`kubectl get pods -o jsonpath=...image` (or the manifest, now automated) tells you the truth —
reading `values.yaml` here checks a path that isn't wired up.

| Input | Status | Evidence |
|---|---|---|
| `yinfangchen/hotelreservation:latest` (frontend/profile/rate/recommendation/reservation/search/user) | Floats, but every container in these raw manifests sets `imagePullPolicy: IfNotPresent` explicitly (19 of 19 deployments), so a node pulls it once and reuses the cached copy. Left unset, Kubernetes would default `:latest` and untagged images to `Always` and re-pull every run | `aiopslab-applications/hotelReservation/kubernetes/*/*-deployment.yaml` |
| `hashicorp/consul:latest` | Floats, same as above | `.../kubernetes/consul/consul-deployment.yaml` |
| `memcached` (no tag = `:latest`) | Floats, same as above | `.../kubernetes/*/memcached-*-deployment.yaml` |
| `mongo:4.4.6`, `jaegertracing/all-in-one:1.57` | Pinned | same manifests |
| `yinfangchen/geo:app3` | Not really "floating" — it's the fault itself. `ApplicationFaultInjector.inject_misconfig_app` hardcodes `container.image = "yinfangchen/geo:app3"` as the misconfiguration for `misconfig_app_hotel_res-*` problems; it's a fixed string in a file already covered by the commit pin. Only risk is the third-party publisher changing what that tag points to on Docker Hub — same category as any other unpinned-by-digest external image, not something the harness controls either way. | `aiopslab/generators/fault/inject_app.py:162` |
| `deathstarbench/wrk2-client:latest` | Repulled every run — k8s defaults `imagePullPolicy` to `Always` for `:latest` tags with none set explicitly | `aiopslab/generators/workload/wrk-job-template.yaml` |
| kind node image | Floats on `:latest` upstream | `third_party/aiopslab/kind/kind-config-x86.yaml` |
| OpenEBS operator manifest | Live-fetched from `openebs.github.io` on every non-Docker `init_problem()` call, no version pin | `orchestrator.py`'s `kubectl apply -f https://openebs.github.io/charts/openebs-operator.yaml` |
| OpenTelemetry demo (Astronomy Shop) Helm chart | **Genuinely floats, and will almost certainly move mid-study** | `AstronomyShop.deploy()` calls `Helm.install(**self.helm_configs)` with no `"version"` key against the remote `open-telemetry/opentelemetry-demo` repo — this one *is* real Helm, unlike HotelReservation. Checked the real release history via the GitHub API: 13 releases in 2026, most recent `0.41.1` on 2026-09-11 — roughly monthly cadence, so a release landing between now and the 31 Oct anchor is near-certain. |

Net: the original "hotelreservation:latest, geo:app3, wrk2-client... effectively frozen (given
no cluster rebuild)" read on this was right. My in-chat "correction" of it, based on the unused
Helm chart, was wrong and is retracted.

The bigger source of run-to-run variance isn't any of these: two identical Day-1 runs of the
same deterministic scripted agent got different observation text in 2 of 3 steps (`get_logs`
596 vs 1402 chars, `get_metrics` 1418 vs 375 chars — see `runs/day1-boot-run1` vs
`runs/day1-boot-run2`). A scripted agent ignores that; a real LLM agent conditions on it, so
"identical" reruns can diverge in *behavior*, not just telemetry, before sampling randomness
is even in play. No amount of image pinning touches this — it has to be handled by measuring
the noise floor directly (below).

## What we're doing about it

1. **Don't rebuild the cluster during the study.** Keeps every cached image (hotel-res app
   code, wrk2-client, kind node) frozen for the duration, without needing to chase digests for
   things that are already effectively static. If the cluster does need rebuilding mid-study,
   treat runs before and after as a discontinuity, not just noise.
2. **Kind node image pinned by digest** in our own `configs/kind-config-x86.yaml` (not
   editing the vendored `third_party/aiopslab/kind/kind-config-x86.yaml`):
   `jacksonarthurclark/aiopslab-kind-x86@sha256:d631857278d3f8ce5c36364c75ec25695ceb22e311ec6621a4ebf5506b86774d`,
   verified as the currently-cached digest on 2026-09-12. Use this file, not upstream's, when
   (re-)creating the cluster.
3. **Per-run manifest** (`agents/run_manifest.py`, written as `runs/<tag>/manifest.json`
   alongside `trajectory.json`): AIOpsLab + `aiopslab-applications` commit hashes,
   `config.yml` contents (gitignored upstream — `qualitative_eval` lives here and changes
   what gets scored), the kind node image digest actually running, the Python interpreter
   (`sys.executable`, `poetry.lock` hash, `pip freeze`), and the image refs of every pod
   actually deployed for the run's namespace. Not a gate — a debugging record, so a future
   discrepancy has something to check against.
4. **OTel chart version pin** (`agents/pin_otel_chart.py`): monkeypatches
   `ProblemRegistry.get_problem_instance` from our own code (no edit to `third_party/aiopslab`)
   to set `prob.app.helm_configs["version"] = "0.41.1"` for any Astronomy Shop problem.
   `Helm.install` already turns a `"version"` key into `--version X`. Pinned to the latest
   release as of 2026-09-13; re-verify and bump deliberately if it's used later, never let it
   silently ride newest. Dormant for now — no Astronomy Shop problems are in scope yet
   (Day 1 only used `misconfig_app_hotel_res-detection-1`).
5. **OpenEBS**: no hash-check/abort gate — decided against it, not worth the complexity for
   a manifest already 2024-vintage stable. Its live-fetched content isn't otherwise recorded
   per run; if it's ever suspected of drifting, check `openebs/charts` history directly rather
   than build machinery for something that hasn't moved in two years.
6. **Interleave baseline and trained runs** rather than running all of one, then all of the
   other. Protocol note for whoever executes the actual study, not something enforced in code.
7. **Measure the noise floor** before trusting any single delta: run the same real agent on
   the same problem 5-10 times and look at how much the *outcome* (not just telemetry) moves
   run to run. This needs a real LLM, not the scripted probe agent — the scripted agent is
   deterministic by construction and can't reveal whether varying observation text actually
   changes what an agent decides to do. Next up, once the Bedrock-compatible key is wired in.
