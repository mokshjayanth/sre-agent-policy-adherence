---
date: 2026-09-28
type: investigation
status: current
evidence:
  - study/evidence/fs-2026-09-28/ (container file list with birth times, copies of every agent file, the runaway file's stat, head and tail, the runaway command, the end of the stage-1 log; SHA256SUMS; local, not in git)
  - third_party/aiopslab/aiopslab/service/shell.py:20-26,98-117 (exec_shell runs `docker exec kind-control-plane sh -c`, timeout on the host side)
  - third_party/aiopslab/aiopslab/orchestrator/actions/base.py:80-104 (exec_shell, "NOT A STATEFUL OR INTERACTIVE shell session")
  - runs/2026-09-28T021806Z_main2-qwen3-next-80b-policy (user_unregistered_mongodb-mitigation-1, history[58]: the awk command)
  - runs/2026-09-27T190525Z_main2-ministral3-3b-nopolicy through runs/2026-09-28T021806Z_main2-qwen3-next-80b-policy (stage 1's first attempt, 152 episodes)
  - runner/harness_fixes.py (reap_after_agent_commands, exec_processes, container_files, reset_container_files, container_drift, check_free_disk)
  - notes/2026-09-27-fresh-run.md (the run this stopped)
---

# Does anything outlive an episode inside the control-plane container, and what did it do to stage 1?

## Question

Stage 1 of the fresh run (notes/2026-09-27-fresh-run.md) stopped on 2026-09-28 with the host disk
full. What filled it, does the same mechanism carry state from one episode to the next, and can the
152 episodes that ran be kept?

## What we checked

- `df`, then `du` down to the kind node containers: the control-plane container's writable layer was
  74.4 GB.
- The container's root: `stat` of every file there and in `/tmp` newer than the container itself,
  with birth times; copies of all of them (the large one as its first 64 KiB and last 4 KiB).
- How the harness runs agent commands (shell.py, actions/base.py), and the processes and cgroups in
  the container.
- The stage-1 trajectories: which episodes named, in an observation they received, a file an earlier
  episode had left. Matched as a whole path token against the files that survived; files written and
  later deleted leave no trace and are not counted.
- The end of study/stage1.log.

## Findings

1. **Agent commands run inside the control-plane container, and what they leave stays.** exec_shell
   runs `docker exec kind-control-plane sh -c "<command>"` (shell.py:20-26, 101-117) with `/` as the
   working directory. The reset and the cluster baseline covered Kubernetes objects only. On
   2026-09-28 the container held 5 agent files in `/` (rate-deployment.yaml, pod.yaml,
   deployment.yaml, geo-deployment.yaml, geo-deployment-fixed.yaml) and 7 in `/tmp`, created
   2026-09-27T20:10Z to 2026-09-28T02:44Z (container-files.txt). The harness runs nothing else there
   (actions/base.py:104 is its only call of Shell.exec), so every one is an agent's.
2. **Later episodes saw them.** At least 4 of the 152 episodes received an observation naming a file
   an earlier episode had left: three of runs/2026-09-27T203433Z_main2-ministral3-8b-nopolicy
   (k8s_target_port-misconfig-mitigation-2, auth_miss_mongodb-mitigation-1,
   wrong_bin_usage-mitigation-1: `rate-deployment.yaml`, and in the last also `pod.yaml`) and
   user_unregistered_mongodb-mitigation-1 of runs/2026-09-28T021806Z_main2-qwen3-next-80b-policy
   (`geo-deployment.yaml`). This is a lower bound: deleted files, and files an agent read without the
   name appearing, are not counted. Only the 23 episodes that started before the first surviving file
   are outside it, and even those can't be proven clean, since earlier files may have been deleted.
3. **A command outlived its episode and filled the disk.** In user_unregistered_mongodb-mitigation-1
   of the qwen3-next-80b policy batch (started 02:36:26Z), the agent ran
   `kubectl get deployment geo ... -o yaml > geo-deployment.yaml && awk '/spec:/ { print; getline;
   while($0 !~ /^  template:/) { print; getline } ...' ... > geo-deployment-fixed.yaml` (history[58];
   runaway-command.txt). The `while` loop never ends at end of file, since `getline` then leaves `$0`
   unchanged. The harness's 30 s timeout kills the `docker exec` client on the host
   (shell.py:108-113); the process in the container is reparented to its init and keeps running. The
   file was created at 02:39:28Z and last written at 02:53:15Z, at 74,434,625,536 bytes, when the host
   volume was full. The run's driver then died writing an error file ("No space left on device"),
   so study/stage1.log ends in a traceback, not a `STOPPED:` line.
4. **The episodes that ran next to the runaway** (02:39Z to 02:53Z) shared the node with it.
5. **Leftover processes can be told apart exactly.** A process started by `docker exec`, and every
   orphan it leaves, is in the container's `0::/init.scope` cgroup; the only other member is init
   (PID 1). Systemd services and pods have their own cgroups (checked with a planted `sleep 300`,
   killed by that rule).

## Decision

- **Stage 1's first attempt is retired**: runs/*_main2-* (10 batches, 152 episodes) stay untouched in
  `runs/` and are not used. Its Kubernetes checks all passed; the container was never checked, and
  Finding 2 shows exposure.
- **Harness fixes, all in runner/harness_fixes.py and applied by runner/run_batch.py:**
  - `reap_after_agent_commands()`: after every exec into the control plane, success or timeout, every
    process left in `init.scope` (but init) is killed, so no agent command outlives its call; what was
    killed is recorded per episode (`reaped_after_commands`). This is the harness's own contract:
    exec_shell is documented as not stateful (actions/base.py:83).
  - The cluster baseline also records the container's files (`container_files`: every path under `/`,
    `/var`, `/tmp`, `/dev/shm` and `/run`, each on its own mount, outside the system-managed subtrees
    in `CONTAINER_FS_SKIP`). The reset deletes every path the baseline doesn't have and kills leftover
    processes (`deleted_container_files`, `reaped_processes`); `cluster_drift` also reports new,
    changed or missing paths and any live exec process, and a non-empty drift refuses the episode.
  - `check_free_disk()`: a problem doesn't start with less than 20 GB free, and run_plan stops for a
    person, before a disk can fill silently.
- **The fresh run restarts at stage 1**, from a new cluster, under purposes `main3` and `ladder3`
  (`main2` names are taken by the retired batches, and run folders are never renamed). Design,
  plan contents and order are otherwise unchanged.

## Open

- An agent writing inside a skipped subtree (for example `/var/log`) is not detected; unverified
  whether any ever did.

## Calibration (2026-09-28)

On a new cluster (created 2026-09-28T06:47:53Z from configs/kind-config-x86.yaml), with the scripted
agent, at 7069ba7:

1. **What the system changes by itself.** The container's files right after creation against after a
   warm-up (runs/2026-09-28T064828Z_smoke-scripted-warmup2, one problem per app): nothing new or gone;
   changed only `/run/log/journal/*/system.journal` and two files under `/run/systemd/transient`. Both
   subtrees were added to `CONTAINER_FS_SKIP` (33abbc1).
2. **Mid-problem.** Under a baseline taken after a reset, all 5 problems of
   runs/2026-09-28T065631Z_smoke-scripted-baseline2 were refused before the agent's first action:
   `file new: /run/systemd/units/invocation:cri-containerd-<id>.scope`, two per problem, systemd's
   records of the scopes of the pods per-problem daemonsets start on this node, which exist only
   while a problem runs, so the between-problems snapshot of step 1 could not see them. They were the
   only drift. `/run/systemd/units` was added to the skips (7069ba7) and the baseline retaken; the
   next reset also removed the Prometheus and OpenEBS the refused problems had left.
3. **Under that baseline**, runs/2026-09-28T070945Z_smoke-scripted-baseline3, the same 5 problems:
   all `ok`, nothing preexisting, no drift, nothing reaped or deleted.
4. **The reaper, through the harness's own shell** (`Shell.exec`, with and without the patch): stock,
   `sleep 300 &` stayed running after the call; patched, a background `sleep 301` was killed when the
   call returned, and a `sleep 100` that hit the 30 s timeout was killed with its shell; an ordinary
   command's output was unchanged and nothing was reaped.
5. **Planted leftovers.** Files in `/`, `/root`, `/var/tmp` and a directory in `/tmp`, and a detached
   `sleep 900`: the next problem's reset (runs/2026-09-28T072347Z_smoke-scripted-planted-fs) deleted all
   four paths and killed the process, and the problem started clean.
6. **A changed baseline file.** A line appended to `/etc/issue.net`: the next problem
   (runs/2026-09-28T072612Z_smoke-scripted-changed-fs) was refused before the agent's first action
   with `file changed: /etc/issue.net`.
7. **Final baseline**, configs/cluster-baseline-fresh.json, taken 2026-09-28T07:28:47Z right after a
   reset (242 objects, 8,319 container paths), with the file restored; two problems under it
   (runs/2026-09-28T072850Z_smoke-scripted-final-baseline): both `ok`, clean, no drift.

## Correction (2026-09-28): refusing on a changed file stopped stage 1 again; the reset now restores

The Decision above refused any episode whose container files differed from the baseline after the
reset, which deleted only new paths. That was wrong for files that already existed: stage 1's second
attempt (`main3-…`, launched 08:12:17Z at c2ea72e) stopped at 09:35:30Z (study/stage1-main3.log). In
runs/2026-09-28T085729Z_main3-ministral3-3b-policy, k8s_target_port-misconfig-mitigation-3, the agent ran
`kubectl get resources`; an unknown resource type makes kubectl refetch discovery, rewriting 24 files
under `/root/.kube/cache`, content derived from the API server, not written by the agent. The next 14
problems of that batch were refused (`file changed: /root/.kube/cache/…`), and run_plan stopped. An
agent has also run `apt-get install` on the node itself (runs/2026-09-20T095754Z_main-ministral3-3b-scored,
k8s_target_port-misconfig-mitigation and wrong_bin_usage-localization-1), which changes
`/var/lib/dpkg/status` the same way.

- **Fix (e0636de):** the baseline takes a pax tar of every regular file and symlink it lists
  (study/baselines/cluster-baseline-fresh.files.tar, ~600 MB, local; its sha256 is recorded in
  configs/cluster-baseline-fresh.json). The reset deletes new paths as before and restores every
  changed or missing file and directory from that snapshot, after checking its sha256; only what it
  cannot restore reaches cluster_drift() and refuses the episode. Nothing is skipped for kubectl: its
  cache is put back like any other file.
- **`main3` retired:** its 18 completed episodes (runs/2026-09-28T081221Z_main3-ministral3-3b-nopolicy,
  16; and 2 of runs/2026-09-28T085729Z_main3-ministral3-3b-policy) were clean but ran at c2ea72e, and a
  plan must run in one environment (runner/verify_plan.py, environment()). The fresh run is `main4-…`
  and `ladder4-…`.
- **Baseline retaken** 2026-09-28T19:05:23Z, after a reset with no process left; against the one it
  replaced it differs only in the 24 kubectl cache files (no other path, no object).
- **Calibration** (2026-09-28T190601Z_smoke-scripted-restore): on the node, `kubectl get resources`, a real `apt-get install telnet`
  (succeeded), `/etc/issue.net` deleted, the symlink `/usr/bin/captoinfo` replaced by a file, a
  planted `/planted.yaml` and a detached `sleep 900`, 53 drift entries in all. The first problem's
  reset deleted 15 paths, restored 37 files (the 24 cache files, 11 apt/dpkg files, `/etc/issue.net`,
  the symlink) and killed the process; all three problems started with no drift and ran `ok`, and
  afterwards telnet was gone and the symlink pointed at `tic` again.
- **Tests** in tests/test_harness_fixes.py reached the real node through docker since fc9c1fa (three
  baseline tests); an autouse fixture now sends every docker call to a fake node, and a
  `docker events` trace of a full test run showed no exec.
