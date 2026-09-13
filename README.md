# SRE agent policy adherence

Experiments on whether SRE agents follow an instructed operational policy, run
on the [AIOpsLab](https://github.com/microsoft/AIOpsLab) benchmark harness.

## Setup

Needs Docker, [kind](https://kind.sigs.k8s.io/), kubectl, Helm, Python 3.11
and Poetry on an x86 machine. `configs/kind-config-x86.yaml` pins an x86 node
image; on ARM, use the harness's own `kind/kind-config-arm.yaml` instead.

1. Clone with the harness and the apps it deploys (about 350 MB):

   ```
   git clone --recurse-submodules <repo-url>
   cd sre-agent-policy-adherence
   ```

   Already cloned without submodules? Run `git submodule update --init --recursive`.

2. Install the harness's Python environment, skipping its `clients` group:

   ```
   poetry -C third_party/aiopslab env use python3.11
   poetry -C third_party/aiopslab install --without clients
   ```

   The `clients` group holds the harness's reference agents (vllm, autogen,
   Azure ML) and pulls large CUDA wheels. Neither this repo nor the harness
   package imports anything from it.

3. Create the harness config from its template, then set `k8s_host: kind` and
   `k8s_user` to your username:

   ```
   cp third_party/aiopslab/aiopslab/config.yml.example third_party/aiopslab/aiopslab/config.yml
   ```

4. Create the cluster from the digest-pinned config. Keep the default cluster
   name `kind`: the harness targets the context `kind-kind` and the container
   `kind-control-plane`.

   ```
   kind create cluster --config configs/kind-config-x86.yaml
   ```

5. Confirm the harness is at the pinned commit (see `CLAUDE.md`):

   ```
   git submodule status --recursive
   ```

## Repository layout

| Path | What's there |
|---|---|
| `agents/` | Agents only: each turns an observation into one action |
| `runner/` | Runs AIOpsLab problems and records them; `harness_fixes.py` holds every workaround for harness bugs |
| `tests/` | Tests that need no cluster |
| `configs/` | Pinned cluster config |
| `notes/` | Dated findings and decisions |
| `runs/` | Batch outputs (not committed) |
| `third_party/aiopslab` | The harness, as a submodule at the pinned commit |

## Running problems

Activate the harness environment from the repo root, then run a batch:

```
eval "$(poetry -C third_party/aiopslab env activate)"
python -m runner.run_batch --problems misconfig_app_hotel_res-detection-1 --condition smoke-scripted --agent scripted-probe --max-steps 5
```

Avoid `poetry -C third_party/aiopslab run python -m runner.run_batch`:
`poetry -C` switches into the harness directory, where `runner` isn't importable.

Choose problems with exactly one of `--problems ID ...`, `--problem-file PATH`,
`--task detection|localization|analysis|mitigation`, `--all`, or
`--resume BATCH_ID` to continue an interrupted batch. Problems run one at a
time on the single cluster, and each spends roughly 1–4 minutes on setup and
teardown before any agent time. Problems known to fail at the pinned chart
version are skipped unless you pass `--include-excluded`; see
`runner/problem_sets.py`.

Run the tests, which need no cluster, with `python -m pytest tests`.

## Where results go

Each batch writes one folder under `runs/`, which git ignores:

```
runs/<UTC time>_<condition>/
  batch.json        environment: repo and harness commits, config, Python env, pins, run arguments
  index.jsonl       one line per finished problem: status, results, timings, port-forward cleanup counts
  problems/<problem_id>/
    trajectory.json   agent and environment turns, plus harness results
    pods.json         image digests of every pod, captured after deploy
    error.txt         only if the problem failed
```

Start from `index.jsonl`. The docstring in `runner/run_batch.py` covers the full
layout, the resume rules, and why the runner works from `~/aiopslab-work`.
