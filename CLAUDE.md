# CLAUDE.md

## Harness pin (ADR v3, Day 1 — 12 Sep 2026)

Benchmark harness: [AIOpsLab](https://github.com/microsoft/AIOpsLab), vendored
unmodified at `third_party/aiopslab`. It is gitignored, not a submodule — there
is no `.gitmodules` entry, so this file is the only record of which commit any
run was scored against.

Pinned commit: `ddf7e40619689dad75eaf8f2174e263c4157ec76`
(2026-08-19, "Pin GitHub Actions to full-length commit SHAs (#196)")

Working tree at pin time: clean (`git -C third_party/aiopslab status --short`
empty).

A benchmark that moves under you invalidates every earlier run. Before
trusting any result against a prior one, confirm `third_party/aiopslab` is
still at the pinned commit:

```
git -C third_party/aiopslab rev-parse HEAD
```

If it has moved, either reset it back to the pinned SHA or treat all prior
runs as incomparable and re-pin here with the new hash.
