---
date: 2026-09-27
type: decision
status: current
evidence:
  - runs/2026-09-27T112744Z_main-ministral3-8b-scored-r2/ (index.jsonl; trajectories of k8s_target_port-misconfig-mitigation-3, auth_miss_mongodb-mitigation-1, auth_miss_mongodb-localization-1)
  - study/round2-pressure.log (deploy timeouts from 11:54Z), study/leftover-watch-round2.log (local, not in git)
  - notes/2026-09-27-cross-episode-contamination.md (the investigation)
  - kubectl get configmaps -n test-social-network (2026-09-27 ~16:00Z): agent-created config maps dated 2026-09-20, 09-21, 09-24
---

# When is an episode invalid because an earlier episode's changes were still in the cluster?

Written 2026-09-27 16:21Z (IST 21:51), while round 2 of the budget and scored arms was still running,
before any contamination audit was run and before any rate from round 2 was computed. Kept outside
the repo until the run ends (a repo change would block the run's resumes); to be moved to notes/
unchanged, with this paragraph as the record of when it was fixed. Agreed by the user, 2026-09-27.

## Question

Agents can create resources (deployments, config maps, pods) in an application namespace. The harness
removes only its Helm release between problems, so such resources persist into later episodes. On
2026-09-27 a deployment created by ministral3-8b at 11:33Z (`post-storage-service-fixed`) was present,
and seen by the agent, in two later episodes that ended `ok`. Which episodes may be used?

## Decision (fixed before the audit)

- **Invalid episode:** one that started while a workload or config object created by an *earlier*
  episode existed in its application's namespace, **and** whose trajectory shows the agent observed
  it (the object's name appears in an observation the agent received).
- Invalid episodes are **never used** in any rate, success figure or example. Each is re-run, and the
  re-run replaces it; the invalid attempt stays on disk, marked invalid with its reason.
- The rule is applied to **every episode of the main study and the ladder, every round**, the same way,
  without looking at the episode's adherence or success.
- An object the current episode's own agent created is never contamination for that episode.
- Objects present but never observed by the agent do not invalidate an episode; they are counted and
  reported.

## Known so far (not yet the audit)

- runs/2026-09-27T112744Z_main-ministral3-8b-scored-r2: `auth_miss_mongodb-mitigation-1` (started
  11:33:12Z, attempt 1) and `auth_miss_mongodb-localization-1` (12:36:02Z, attempt 2) meet both
  conditions. Both are `ok` in index.jsonl and would currently be used.
- The 30 attempts that failed at deploy (11:54Z-15:59Z) never reached the agent; they are harness
  errors, re-run under the existing exclusion rule.

## Open

- The audit itself: every episode, every round.
- A recorded invalidation mechanism in the runner (today `choose_attempts` picks the non-error attempt
  with the most steps, so an invalid `ok` attempt would be used).
- Reporting: this is a deviation from the preregistration's exclusion rule (which re-runs only
  runner/harness errors) and is reported as one.

## Moved (2026-09-27)

Moved from `study/pending-notes/` into notes/ at 16:53Z, after the run stopped, with the text above
unchanged except these evidence paths (the folder moved into the repo) and a link to the investigation.
