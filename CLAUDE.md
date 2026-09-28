# CLAUDE.md

## Harness pin (decided 12 Sep 2026; submodule since 13 Sep 2026)

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

Beyond the commit, see `notes/2026-09-13-harness-pin-coverage.md`. Create the
kind cluster from `configs/kind-config-x86.yaml` (node image pinned by digest),
not the harness's own config. Run problems through `runner/run_batch.py`; each
batch records its environment in `runs/<batch>/batch.json`.

## Layout

- `agents/` holds agents only. Each exposes `init_context(...)` and
  `async get_action(observation) -> str`, and is registered by name in
  `runner/run_batch.py`. Agents never import `runner`.
- `runner/` runs AIOpsLab problems and records them. Entry point:
  `python -m runner.run_batch`. Every workaround for harness behaviour goes in
  `runner/harness_fixes.py`, and nowhere else; revisit it whenever the harness
  pin moves.
- `tests/` needs no cluster: `python -m pytest tests`. Keep new tests there,
  not in scratch folders.
- `policy/` holds the operational policy text agents are instructed to follow.
  Files named `draft-*` are drafts; only a version wired into the agent's prompt
  is in effect, and which one is recorded in the agent's description.
- `results/<study>-<date>/` holds a study's reviewed outputs: a `README.md` with the episode table
  and legend, the episodes, and `labels/` (every judge's labels, the reconciliation and the agreed
  labels the notes cite). `runs/` stays the raw, uncommitted record.
- `RESEARCH.md` states the research design decisions in force. Don't rewrite a
  decision in place: append a dated `## Correction` there, and link the note
  that holds the evidence.

## Notes (`notes/`)

Notes record what was learned or decided, including findings that changed no
code. Commits record what changed. One note answers one question.

- **Name:** `notes/YYYY-MM-DD-<topic>.md`, dated the day the question was
  worked. The topic names the subject (`harness-pin-coverage`), not the
  activity (`hardening`).
- **Structure:** copy `notes/_template.md`. Frontmatter has `date`, `type`
  (`audit`, `investigation` or `decision`), `status` (`current` or
  `superseded by <file>`) and `evidence`. Sections are Question, What we
  checked, Findings, Decision, Open.
- **Evidence:** every claim cites a file path and line, a commit, a batch ID
  or a URL. Mark anything not checked as unverified. Take counts from the code
  or data, never from planning documents, the literature or memory.
- **Corrections:** never silently rewrite a finding. Append
  `## Correction (YYYY-MM-DD)` stating what was wrong and what is right.
  Fixing a broken link or moved path in place is fine.
- **Commits** that act on a note name it in the message body.

Notes written before these rules keep their original structure; they gained
frontmatter and dated names only.

## Runs (`runs/`, gitignored)

- Only `runner/run_batch.py` creates run folders, named
  `runs/<UTC timestamp>_<condition>/`. Never create, rename or restructure one
  by hand.
- `condition` is `<purpose>-<agent>[-<variant>][-r<round>]`, lowercase. `purpose`
  is one of `smoke`, `validation`, `noise`, `pilot`, `main`, `ladder`, `main2`,
  `ladder2`, `main3`, `ladder3`, `main4`, `ladder4`, `main5`, `ladder5`, `b1`, `b2`,
  `b3`, `t1`, `t2`, and the runner rejects anything else. `main5` and `ladder5` are
  the fresh run of the main study and the ladder, driven only by
  `python -m runner.run_plan` (notes/2026-09-27-fresh-run.md); `main2` to `main4`
  and `ladder2` to `ladder4` were its first three attempts, retired
  (notes/2026-09-28-control-plane-persistence.md). Examples:
  `validation-scripted`, `noise-sonnet5`, `main-gpt-oss-120b-policy-r2`,
  `ladder-qwen3-next-80b-combined-r1`. A missing `-r<round>` means round 1, which
  is how the main study's first round was labelled.
- `python -m runner.catalog --out results/<study>/batches.csv` writes one row per
  batch: study, arm, round, model, step budget, every instructed text with its
  hash, and whether those texts still match the working tree. Analysis selects
  batches through that file, not by globbing `runs/`.
- Runs from before these rules sit untouched in `runs/_legacy/`.
