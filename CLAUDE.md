# CLAUDE.md

## Harness pin (ADR v3, Day 1 — 12 Sep 2026; submodule since 13 Sep 2026)

Benchmark harness: [AIOpsLab](https://github.com/microsoft/AIOpsLab), vendored
unmodified as a git submodule at `third_party/aiopslab`. Git records the pinned
commit; the apps under test come from the harness's own nested
`aiopslab-applications` submodule, pinned by that commit.

Pinned commit: `ddf7e40619689dad75eaf8f2174e263c4157ec76`
(2026-08-19, "Pin GitHub Actions to full-length commit SHAs (#196)")

A benchmark that moves under you invalidates every earlier run. Before
trusting any result against a prior one, confirm the harness is at the pinned
commit with a clean tree:

```
git submodule status --recursive             # a leading + or - means moved or missing
git -C third_party/aiopslab status --short   # must print nothing
```

If it has moved, either return to the pin with
`git submodule update --init --recursive`, or bump deliberately: check out the
new commit inside `third_party/aiopslab`, commit the updated submodule here,
update the hash above, and treat all prior runs as incomparable.

Beyond the commit, see `notes/harness-pinning-hardening.md`. Create the kind
cluster from `configs/kind-config-x86.yaml` (node image pinned by digest), not
the harness's own config. Run problems through `agents/run_batch.py`; each
batch records its environment in `runs/<batch>/batch.json`.
