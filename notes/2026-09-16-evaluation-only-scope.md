---
date: 2026-09-16
type: decision
status: current
evidence:
  - notes/2026-09-15-premise-check-pilot.md (design, rubric, decision rule)
  - runs/2026-09-15T120248Z_pilot-qwen3-next-nopolicy, runs/2026-09-15T125458Z_pilot-qwen3-next-nopolicy
  - runs/2026-09-15T121402Z_pilot-qwen3-next-policy, runs/2026-09-15T124448Z_pilot-qwen3-next-policy
  - runs/2026-09-15T122332Z_pilot-qwen3-next-urgency-policy, runs/2026-09-15T123250Z_pilot-qwen3-next-urgency-policy
  - runs/2026-09-15T130428Z_pilot-qwen3-next-urgency, runs/2026-09-15T131417Z_pilot-qwen3-next-urgency
  - /home/ubuntu/pilot-judging-2026-09-15/labels-claude.csv (one judge's labels, frozen before the condition map was opened; not yet in the repo)
  - RESEARCH.md (O1, O4, O5)
  - https://www.anthropic.com/research/agentic-misalignment
  - https://arxiv.org/abs/2412.14093
---

# Should the first study post-train at all?

## Question

`RESEARCH.md` asks what success-optimising post-training does to an SRE agent's adherence to an
instructed policy. Its training rungs depend on things not in place: T2's reward is open (O1),
whether T2 fits one 48 GB GPU is unmeasured (O5), B2 and B3 aren't designed (O4), and no 48 GB
instance is available. Can a first study answer a narrower question without post-training, and
is there evidence it would produce a measurable result?

## What we checked

- The 24-episode premise-check pilot (`notes/2026-09-15-premise-check-pilot.md`): Qwen3-Next on
  the gateway, three training-split mitigation problems, four prompt variants. Episodes were
  labelled by one judge against the pre-registered rubric, and the labels were frozen before the
  condition map was opened. The pilot note's findings are pending the owner's review, so the
  counts below are provisional.
- Input and output tokens per episode, from each pilot episode's `agent_record`, counted with
  tiktoken as the agent counts.
- Two Anthropic studies of model behaviour under pressure, through their abstract and research
  page only.

## Findings

1. **Adherence varies without any training, by the kind of rule.** Without the policy, 6 of 7
   restart actions were pod deletions or scaling to zero and back (4 of 7 counting deletions
   only); with the policy, 0 of 8. With the policy, a change was recorded before it (R7) for 3 of
   29 changes (`labels-claude.csv`).
2. **The urgency text changed nothing measurable.** Counted per episode, the policy and
   urgency-plus-policy variants look alike; urgency-plus-policy's higher R8 count comes mostly from
   one episode with 12 change attempts. The urgency line isn't a usable pressure manipulation on
   its own.
3. **Harness success doesn't discriminate on `misconfig_app_hotel_res-mitigation-1`:** 8 of 8
   episodes passed, including ones whose change didn't address the fault (a service type changed
   to NodePort; a frontend restart). The cause is unverified.
4. **Cost is set by input tokens.** A pilot episode sent a median of 100,431 and a mean of 137,386
   input tokens (maximum 675,456) and a mean of 1,582 output tokens.
5. **Related work** (from summaries; verify against full text before citing):
   - *Agentic Misalignment* (Lynch et al., Anthropic, 20 June 2025) places models as agents with
     tool access under a goal conflict or a threat of replacement. Its research page states that a
     simple instruction not to do the harmful behaviours "reduced, but didn't come close to
     completely preventing" them, and that models recognised they were violating ethical
     principles and proceeded anyway. This is the closest published parallel to an instructed
     policy under pressure.
   - *Alignment faking in large language models* (Greenblatt et al., arXiv:2412.14093) tells Claude 3
     Opus in its system prompt that it is being trained, and on which users' conversations. It
     concerns behaviour when a model believes it is being trained, which bears on post-training
     rather than on pressure within an episode.

## Decision

- **The first study is evaluation-only.** Its question: how does pressure toward task success
  change an SRE agent's adherence to an instructed operational policy that task scoring does not
  enforce, and does the change depend on the kind of rule? Measure the change, not the level.
- **Post-training becomes a possible second study,** unscheduled, with O1 and O5 parked alongside
  it.
- **Pressure must be shown to work before the main runs.** Candidates: a tight step budget, and
  telling the agent it is scored on recovery. Pressure leads the paper's framing only if a
  manipulation changes adherence; otherwise the result by rule type does.
- **Conditions become models × prompt variants:** no policy, policy, and pressure with and
  without the policy.
- **Agentic Misalignment is the primary related work** on instructions under pressure. Alignment
  faking is cited only where the paper discusses post-training as future work.
- **Harness success is reported next to adherence,** and problems whose success check doesn't
  discriminate are identified and reported separately.

## Open

- Which models, and how many runs per problem, within the Bedrock credit.
- Whether the main evaluation uses all in-scope problems or only the test split, now that no model
  is trained on the training split.
- The grader: hand labelling doesn't scale to the main runs.
- Why the hotel mitigation check passes regardless of the fix.
