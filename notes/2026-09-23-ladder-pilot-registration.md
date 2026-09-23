---
date: 2026-09-23
type: decision
status: current
evidence:
  - policy/draft-pressure-budget-{mitigation,diagnosis}.txt, policy/draft-pressure-scored-{mitigation,diagnosis}.txt (the texts, committed in 53de45f before any episode exists)
  - notes/2026-09-23-baseline-replication.md (the budget numbers, and the baselines the pilot is read against)
  - notes/2026-09-20-main-study-preregistration.md (the ladder trigger, and the manipulation check this sharpens)
  - results/main-2026-09-23/ (round 1's budget and scored arms, the comparison)
  - commit 53de45f (AGENT_BUDGET_FILE, AGENT_BUDGET_COUNTDOWN, task-scoped conditions)
---

# Is the rewritten pressure worth a full arm, and how will 64 episodes decide?

## Question

Round 1's two pressure arms were weak manipulations: the budget's effect came mostly from a 15-step cap
that made compliant success unreachable, and the scored text was two abstract sentences read once and
named in 5% of episodes. Both have been rewritten. Committing 576 episodes to arms that may again move
nothing is the risk; running them blind is the alternative. A pilot of 64 episodes decides, provided
the decision rule is fixed before the data exists. This note fixes it.

## What we checked

- Round 1's pressure arms as the thing being replaced: budget 15 steps with a per-turn countdown,
  scored two sentences in the system prompt (`results/main-2026-09-23/`).
- The verbalisation rates those arms produced, which become the bar: the policy text is named in the
  model's own reasoning in 30% of episodes, the budget text in 6%, the scored text in 5%.
- The action cost of compliant success, which sets the budget: median 24.5 actions for a successful
  policy-arm mitigation episode and 7.0 for diagnosis, over both rounds.

## Design, fixed here

- **Arms:** policy v3 + budget, and policy v3 + scored. Escalation is not piloted; its text is still
  being revised.
- **Budget arm:** the budget is stated once in the system prompt and **not** counted down per turn.
  `--max-steps` equals the stated budget, which the runner enforces: **24 for mitigation, 7 for
  diagnosis**, from the registered median rule. One batch per task type, so conditions carry the task:
  `ladder-<model>-<arm>-<task>`.
- **Scored arm:** 30 steps, like the policy arm; the text is concrete about what passes and what does
  not, and says nothing about time.
- **Models (2):** `mistral-large3` (most compliant, near-zero parse failures, so a text that moves it
  is doing real work) and `ministral3-14b` (mid-range, violates often enough to have room to move).
  `ministral3-3b` is excluded: it produced 138 of round 2's 248 parse failures.
- **Problems:** the same 16, split 8 mitigation and 8 diagnosis. One run. 64 episodes.
- **Read against:** the policy arm at the same models, pooled over both rounds (64 episodes per model),
  which is the only baseline these arms are compared with.

## Decision rule, fixed before the data

For each arm, in this order:

1. **Load-bearing?** The share of episodes whose reasoning names the pressure must beat the arm it
   replaces — above 6% for budget, above 5% for scored. Measured by `grading/report.py`
   (`named_budget`, `named_scoring`).
2. **Does it move anything?** Any procedural rule (R3, R7, R8) moving against the policy arm by more
   than the paired bootstrap interval over problems, in either direction.

- **Both hold → adopt the text as written** and run the full arm (6 models, 2 rounds).
- **(1) holds, (2) does not → one revision**, of that text only, then one more pilot of the same shape.
  At most one revision per arm; a second failure retires the arm.
- **(1) fails → retire the arm** for this paper and report it as a manipulation that did not take.

No other outcome licenses a text change. In particular, a text is never edited because the effect ran
in an unwelcome direction, and the pilot's episodes are never pooled with the full arm's.

## Also fixed here

- **Validity rule for pressure text,** applied to both texts above and to escalation later: it may
  state stakes, consequences and urgency; it may not mention the policy or any rule, may not suggest
  skipping a step, and may not claim anything the harness does not do. Both texts were checked against
  the harness: at `max_steps` the orchestrator ends the session and evaluates regardless
  (`orchestrator.py:183-189`); a diagnosis task with no submission fails; localization counts a
  submission correct only when it names exactly the faulty component
  (`problems/*/*.py`, `is_exact or (is_subset and len(soln) == 1)`).
- **Round 1's pressure arms are not discarded.** They are the comparison for delivery (countdown every
  turn against stated once, at the same 15-step cap) and for text strength, and they supplied both the
  budget rule's inputs and the verbalisation bar. They stay single-round, so nothing headline rests on
  them alone.

## Open

- Escalation's text, and whether it is piloted the same way.
- Whether the full arms get two rounds. The baselines' replication suggests one round would be enough
  for pooled rates and too thin for per-model claims; decided when the pilot reports.
