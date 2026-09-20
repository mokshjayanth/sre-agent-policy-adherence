---
date: 2026-09-20
type: investigation
status: current
evidence:
  - runs/2026-09-20T*_main-ministral3-14b-* (index.jsonl; 19 episodes failed to deploy)
  - third_party/aiopslab/aiopslab/service/kubectl.py:102-143 (wait_for_ready needs every pod ready)
  - third_party/aiopslab/aiopslab/service/helm.py:133 (assert_if_deployed calls it)
  - runner/harness_fixes.py (delete_failed_pods) and runner/run_batch.py (called per problem)
  - commit 7bf0d0f
---

# Why did SocialNetwork deployments start timing out mid-study?

## Question

Four hours into the main study's round 1, every SocialNetwork problem began failing with "Timeout: Not
all pods in namespace 'test-social-network' reached the Ready state within 300 seconds", while the
first model's batches had run clean. What changed, and how much data is affected?

## What we checked

- `kubectl get pods -A`: one pod, `test-connect` in `test-social-network`, in Failed state, 4 h 45 min
  old at 15:27 UTC, so created around 10:42 UTC, between the first model's last batch and the second
  model's first.
- The harness's readiness wait: `wait_for_ready` returns only when **every** pod in the namespace is
  ready or Succeeded (`kubectl.py:102-143`), and `helm.assert_if_deployed` calls it after each install
  (`helm.py:133`).
- Where `test-connect` comes from: the harness's own MongoDB fault problems run `test-connect`,
  `mongo-check` and `mongo-fix` pods; nothing deletes them when they fail.
- Each main batch's `index.jsonl` for failed episodes and their errors.

## Findings

1. **One failed pod blocks every later deploy of that app.** A pod in Failed phase never becomes ready,
   so `wait_for_ready` burns its full 300 seconds and raises, no matter what the agent does. The
   namespace survives `app.delete()` between problems, and so does the pod.
2. **19 episodes were lost this way**, all SocialNetwork problems, across four `ministral3-14b` batches
   (4, 6, 6 and 3 of 16). A twentieth episode failed separately with the harness's own
   `TypeError: 'NoneType' object is not iterable` in `storage_user_unregistered.eval`.
3. **The first model's 64 episodes are unaffected:** they ran before the pod failed.
4. **It is not agent behaviour.** The failure happens during setup, before the agent is given the
   problem, so no episode content is involved and no condition is favoured; the affected episodes are
   simply missing.

## Decision

- **Deleted the blocking pod** at 15:28 UTC, which unblocks deploys immediately.
- **`runner/harness_fixes.py` gained `delete_failed_pods`**, called before every problem, which clears
  Failed pods in the three app namespaces and records what it deleted in `index.jsonl` (commit
  7bf0d0f). This is a harness workaround, so it lives there per `CLAUDE.md`.
- **The lost episodes are re-run** by a repair pass (`~/study/repair.sh`) that waits for the study to
  finish, then resumes every main batch that still has a failed or missing episode. Resumes need
  `--allow-env-change` because the repo moved to 7bf0d0f; each resume records the diff in the batch's
  `resume-<n>.json`.
- **Batches therefore span two commits** (79a46a3 before the fix, 7bf0d0f after). The change touches
  cluster cleanup only, not the agent, its prompt or the grader, and each batch records which commit it
  ran under.

## Open

- Whether `mongo-check` and `mongo-fix`, which were in CrashLoopBackOff rather than Failed at 15:27, can
  block hotel-reservation deploys the same way. CrashLoopBackOff pods are in Running phase, so the new
  cleanup doesn't catch them; no hotel deploy has timed out so far.
- The `storage_user_unregistered.eval` TypeError, seen twice now, may need its own workaround if it
  recurs after the repair pass.
