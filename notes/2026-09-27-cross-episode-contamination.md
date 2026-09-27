---
date: 2026-09-27
type: investigation
status: current
evidence:
  - third_party/aiopslab/aiopslab/service/apps/socialnet.py:69-73 (cleanup never deletes the namespace; the line is commented out)
  - third_party/aiopslab/aiopslab/service/apps/hotelres.py:87 (HotelReservation's cleanup does delete its namespace)
  - third_party/aiopslab/aiopslab/service/apps/socialnet.py:14-22,30-43 (building the app recreates its namespace and TLS secret)
  - runs/2026-09-27T112744Z_main-ministral3-8b-scored-r2 (the copied deployment, 11:33:04Z, and the two episodes that saw it)
  - runs/*_main-*-scored-r2 index.jsonl (30 deploy timeouts, 11:54Z-15:59Z)
  - study/evidence/leftovers-2026-09-27T165000Z.yaml and inventory-2026-09-27T165000Z.txt, with SHA256SUMS (local, not in git; the inventory is copied below)
  - notes/2026-09-27-episode-contamination-rule.md (the rule an affected episode is judged by)
  - runner/harness_fixes.py (reset_app_state, preexisting_objects) and runner/run_batch.py (called per problem)
---

# Do objects an agent creates survive into later episodes, and what did that do to the data?

## Question

On 2026-09-27 every SocialNetwork problem in round 2 of the pressure arms began timing out at deploy.
The cause was a deployment an agent had created in an earlier episode. Is that a one-off, or does the
harness let agent-created state persist between episodes in general, and how much of the data ran next
to it?

## What we checked

- The harness's app classes: what `cleanup()` removes after a problem, and what building the app
  creates before one.
- The cluster at 2026-09-27 ~16:50Z: every object in `test-social-network` and `default` that no Helm
  release and no other object owns, with its creation time (saved, with checksums, before cleaning).
- The round-2 index files and trajectories around the incident.
- A first count of affected episodes (method under Findings). No episode's adherence or success was
  looked at for it.

## Findings

1. **SocialNetwork's namespace is never deleted between problems.** `SocialNetwork.cleanup()` uninstalls
   the Helm release and leaves `delete_namespace` commented out (socialnet.py:72); HotelReservation's
   deletes its namespace (hotelres.py:87). The namespace present on 2026-09-27 was created
   2026-09-14T08:29:13Z and had lived through every study since. Anything an agent created in it that is
   not part of the Helm release stays.
2. **Agent-created objects accumulated there, and in `default`.** Present at 16:50Z, none owned by a
   release or another object, none referenced by the harness or its charts (grep of third_party/aiopslab,
   excluding stored results):

   | namespace | created (UTC) | kind | name |
   |---|---|---|---|
   | test-social-network | 2026-09-20 07:54 | ConfigMap | social-graph-mongo-timeout |
   | test-social-network | 2026-09-20 10:02 | ConfigMap | user-service-mongodb-config |
   | test-social-network | 2026-09-20 20:12 | Secret | mongodb-tls-pem |
   | test-social-network | 2026-09-20 23:03 | Pod | debug-pod |
   | test-social-network | 2026-09-21 07:51 | ConfigMap | url-shorten-service-updated |
   | test-social-network | 2026-09-21 10:49 | ConfigMap | user-service-updated |
   | test-social-network | 2026-09-23 02:30 | Pod | net-test |
   | test-social-network | 2026-09-24 00:38 | Pod | dns-test |
   | test-social-network | 2026-09-24 02:45 | Ingress | nginx-thrift-ingress |
   | test-social-network | 2026-09-24 06:20 | ConfigMap | url-shorten-service-new |
   | default | 2026-09-22 22:00 | Job (7 failed pods) | mitigate-rate-mongo |
   | default | 2026-09-23 03:29 | Pod | geo-debug |

   `mongodb-tls` (2026-09-20 22:25) is the harness's own (socialnet.py:30-43) and was kept, as were
   `wrk2-job` and `wrk2-payload-script` in `default`. Objects agents created and later deleted are not in
   this list; they are unverified.
3. **One such object broke deploys.** ministral3-8b, in `k8s_target_port-misconfig-mitigation-3` of
   runs/2026-09-27T112744Z_main-ministral3-8b-scored-r2, created `post-storage-service-fixed` at
   11:33:04Z by copying a release deployment, Helm labels included. It crash-looped, `helm uninstall`
   did not remove it, and from 11:54Z every SocialNetwork deploy waited 300 s for it and failed:
   30 attempts over four batches, about 3 h. It was deleted by hand at 16:01:49Z, during a deploy wait
   and before any agent acted; the next SocialNetwork problem deployed.
4. **Episodes ran next to these objects and saw them.** First count, a lower bound: for every `ok`
   SocialNetwork episode of the main study and the ladder, the objects of Finding 2 (plus
   `post-storage-service-fixed` for its lifetime) created before the episode started, and whether any of
   their names appears in an observation the agent received. Of 373 such episodes, 372 started with
   at least one present and **220 observed one** (main round 1: 55 of 144; main round 2: 64 of 84;
   ladder: 101 of 145), mostly the three leftover pods in an ordinary `kubectl get pods`. Two are `ok`
   episodes that saw the crash-looping deployment itself (notes/2026-09-27-episode-contamination-rule.md).
   Objects agents created and later deleted, and the pods in `default`, are not counted, so the true
   number is at least this.
5. **The exposure grew over time**, so it is not spread evenly over arms that ran at different times;
   it can be confounded with the arm.

## Decision

- **Harness fix (this commit):** every problem starts from a reset. `reset_app_state()` deletes the app
  namespaces and waits until they are gone, and clears `default` of everything but the cluster's own
  objects and the harness's wrk2 workload; it raises if that does not finish in 300 s.
  `preexisting_objects()` then records, after deploy and before the agent's first action, anything in
  those namespaces older than the problem, and a non-empty list stops the problem. Both results go into
  each index entry (`reset`, `preexisting_objects`), so every episode carries its own proof of a clean
  start.
- The temporary out-of-repo guard used on 2026-09-27 (`study/leftover_watch.sh`, deletes stale not-Ready
  workloads) is superseded by the reset and is not used again.
- The cluster was cleaned at 16:50Z of every object in Finding 2 except the harness's.
- Round 2 of the pressure arms was stopped at 16:36Z (its last batch finished its clean
  HotelReservation problems and exited at 16:43Z).
- Whether the affected data is audited and re-run, or the main study and ladder are run again from a
  clean state, is the user's decision and is recorded separately.

## Open

- The complete audit under the rule, including objects agents created and later deleted, and the pods
  in `default`.
- Whether the pilot studies were affected in the same way (not counted).

## Smoke test (2026-09-27)

A pod (`planted-leftover`) and a config map (`planted-cm`) were planted in `test-social-network`, and a
config map (`planted-default-cm`) in `default`; then one SocialNetwork problem ran with the scripted
agent (runs/2026-09-27T165411Z_smoke-scripted-reset, `k8s_target_port-misconfig-localization-2`).
Its index entry records `reset = {deleted_namespaces: [test-social-network], deleted_default:
[ConfigMap/planted-default-cm]}` and `preexisting_objects = []`; the episode ended `ok`. Afterwards the
namespace was a new one (created 2026-09-27T16:54:59Z, replacing the one from 2026-09-14), the planted
objects were gone, and the harness had recreated its `mongodb-tls` secret.
