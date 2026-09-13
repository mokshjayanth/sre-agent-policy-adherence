---
date: 2026-09-13
type: decision
status: current
evidence:
  - commit 119efe9 (tip after the rewrite; was e7a3948)
  - runs/2026-09-13T225142Z_smoke-scripted (batch.json records 0354ca3, now 4575e72)
---

# Commit hashes before and after the email rewrite

## Question

Before the first push to GitHub, every commit carried a personal email address. How was it
removed, and how do commit hashes recorded before the rewrite map to the history that was
pushed?

## What we checked

- Saved a bundle of the full pre-rewrite history, then rewrote the author and committer email of
  all 18 commits to `85436060+mokshjayanth@users.noreply.github.com` with
  `git filter-branch --env-filter`. Author names, dates and messages were left unchanged.
- Confirmed the rewritten `main` has the same file tree as the old tip `e7a3948`, 18 commits on
  both sides, and no occurrence of the personal address in any email field or commit message.
- Listed every `batch.json` under `runs/` that records a repo commit.

## Findings

Every hash changed. Old and new, oldest first:

| Old | New | Commit |
|---|---|---|
| `af2bda1` | `e55386b` | Add AIOpsLab harness pin, scripted probe agent and Day-1 audit |
| `7986c9a` | `73b3725` | Ignore Python bytecode and the local credentials file |
| `3cd7f8b` | `cfd6316` | Record per-run manifests and pin the kind node image and OTel chart |
| `0cef347` | `251de36` | Correct the imagePullPolicy reasoning in the pinning note |
| `c559961` | `48e8004` | Record resolved image digests across all namespaces |
| `3e98298` | `3d4c3f0` | Record repo and harness working-tree state, pins and run arguments |
| `d8600c8` | `9ae224a` | Add problem selection with known-broken exclusions |
| `f6694f8` | `9239db3` | Add a batch runner with a navigable run layout and resume |
| `cc4f6d5` | `1b7c235` | Route scripted probe runs through the batch runner |
| `52137a3` | `61bfcbc` | Track AIOpsLab as a git submodule at the pinned commit |
| `46195c3` | `62dcf67` | Add setup and run instructions for a fresh clone |
| `a9e4670` | `85ccb24` | Use the harness's KubeCtl for manifests; detail package drift on resume |
| `2b21cfc` | `dbbda2e` | Install the harness without its clients group |
| `dd56178` | `6ec7604` | Adopt naming and structure conventions for notes and runs |
| `3b48471` | `e13f7aa` | Identify the Python environment by prefix, not interpreter path |
| `43085c9` | `f2e3af7` | Stop harness port-forwards leaked by failed metric queries |
| `0354ca3` | `4575e72` | Clear orphaned harness port-forwards between problems |
| `e7a3948` | `119efe9` | Separate the runner from agents and add cluster-free tests |

Run records whose `repo.commit` names a pre-rewrite commit:

| Batch | Recorded | Now |
|---|---|---|
| `runs/_legacy/2026-09-13T190612Z_runner-validation` | `f6694f8` | `9239db3` |
| `runs/2026-09-13T194534Z_validation-scripted` | `2b21cfc` | `dbbda2e` |
| `runs/2026-09-13T200318Z_validation-scripted` | `3b48471` | `e13f7aa` |
| `runs/2026-09-13T204443Z_smoke-scripted` | `43085c9` | `f2e3af7` |
| `runs/2026-09-13T210625Z_validation-scripted-sweep` | `43085c9` | `f2e3af7` |
| `runs/2026-09-13T225142Z_smoke-scripted` | `0354ca3` | `4575e72` |

## Decision

- Run records stay untouched: they record what was true when they ran. Resolve an old hash with
  the tables above.
- Hashes cited as evidence in `2026-09-12-scoring-surface-audit.md` and
  `2026-09-13-harness-pin-coverage.md` were updated in place to the new ones.
- Future commits use the no-reply address, set in the global git config.
- The pre-rewrite bundle lived only in a temporary session folder.

## Open

None.
