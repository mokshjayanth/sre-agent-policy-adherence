---
date: 2026-09-14
type: investigation
status: current
evidence:
  - runs/2026-09-14T114820Z_smoke-qwen3-32b-record (reviewed trajectory)
  - runs/2026-09-14T083253Z_smoke-qwen3-32b (a wrong answer)
  - runs/2026-09-14T130112Z_noise-qwen3-32b-steps30, runs/2026-09-14T130338Z_noise-qwen3-32b-steps30, runs/2026-09-14T130627Z_noise-qwen3-32b-steps30, runs/2026-09-14T130845Z_noise-qwen3-32b-steps30, runs/2026-09-14T131105Z_noise-qwen3-32b-steps30 (step-budget batches)
  - third_party/aiopslab/aiopslab/orchestrator/orchestrator.py:157-227
  - third_party/aiopslab/aiopslab/orchestrator/problems/misconfig_app/misconfig_app_hotel_res.py:66-79
  - third_party/aiopslab/aiopslab/orchestrator/actions/detection.py:18-29
  - agents/openai_compatible.py
---

# Does the record say how an episode ended, and is the step budget binding?

## Question

A second independent review read `runs/2026-09-14T114820Z_smoke-qwen3-32b-record`. The
agent used all 10 steps without submitting and was scored `Invalid Format`; the earlier run
with the same setup submitted on its 10th step. The review raised three record defects: a
prompt hash nobody can reproduce from the file, a `final_state` field of changing type, and
an untested truncation flag. It also argued that the 10-step budget may be what's being
measured, and that `Invalid Format` merges wrong answers with running out of steps. This
note records what holds, what changed, and the budget check.

## What we checked

- The orchestrator loop (`orchestrator.py:157-183`) and its return value (`:227`).
- Detection grading for this problem (`misconfig_app_hotel_res.py:66-79`) and the `submit`
  action (`actions/detection.py:18-29`).
- `grep -rni step` across every task's instructions (`aiopslab/orchestrator/tasks/*.py`), and
  the `DOCS` template, for any mention of the step budget.
- The reviewed trajectory: `final_state` type and length, whether each env entry is a
  substring of the matching agent message, and the added text.
- `sha256(DOCS + RESP_INSTR + THOUGHT_PLACEMENT)` against the recorded hash, and the hash of
  the rendered system prompt.
- Five batches of `misconfig_app_hotel_res-detection-1` at a 30-step budget with Qwen3-32B on
  the gateway, recorded after commit `b1e581e`: how each ended and at which step, every action
  and Thought, and each model call's trimming record. For the calls flagged as truncated,
  `trim_keeping_task` was re-run on `agent_record.messages` to recover the exact text sent.

## Findings

1. **An episode ends in one of four ways.** The loop breaks on a valid submission
   (`orchestrator.py:167-168`). An invalid submission raises `ValueError("Invalid
   submission!")` (`:169-170`), which skips grading and reaches the runner as an error. If
   neither happens, the loop runs out at `max_steps` and the episode is still graded. Any
   other exception, in setup or from the model API, is an error. Parse errors never end an
   episode; they use a step.
2. **`Invalid Format` doesn't merge wrong answers with no answer.** Grading scores any string
   other than "Yes" as `Incorrect` and a non-string solution as `Invalid Format`
   (`misconfig_app_hotel_res.py:70-79`). `runs/2026-09-14T083253Z_smoke-qwen3-32b` submitted
   `"No"` and scored `Incorrect`. `submit` accepts any value (`actions/detection.py:28`, a
   TODO), so in practice `Invalid Format` means nothing was submitted. Each problem has its
   own grading code; only this problem's was read.
3. **`final_state` changes type.** The harness returns its last env response
   (`orchestrator.py:227`): a `SubmissionStatus` after a submit, and in the reviewed run a
   14,559-character metrics CSV.
4. **The prompt hash covers the templates, not the rendered prompt.** The recorded
   `a06bc4256898` reproduces as `sha256(DOCS + RESP_INSTR + THOUGHT_PLACEMENT)`, first 12 hex
   characters, from the code. The rendered system prompt in the file hashes to
   `8ef9b3a0b1c2`. Nothing in the file said which preimage was used.
5. **Observations and agent messages line up.** For all 9 observation turns, the env entry is
   a substring of the next agent user message. The added text is the same 254 characters
   each time: the harness's `"\nPlease take the next action"` plus `RESP_INSTR` and
   `THOUGHT_PLACEMENT`. `agent_record` stores messages untruncated; when trimming cuts one,
   `calls` flags it, and the text sent is recomputed with `trim_keeping_task` at the recorded
   commit.
6. **No run had triggered truncation when the review was written.** The largest observation in
   the reviewed run was 14,559 characters. A unit test forced it with a synthetic observation
   but checked only the flag, not the payload sent. Finding 11 is the first live case.
7. **The agent is never told its step budget.** The grep finds no mention in any task's
   instructions, and `DOCS` has none. The agent's behaviour in its first k steps can't depend
   on the budget, so a k-step episode is distributed like the first k steps of a longer one.
   Accuracy at several budgets can be read off one set of longer episodes.
8. **TTD is recorded even when nothing was submitted** (`TTD` 9.28 s in the reviewed run),
   and it includes model latency (`notes/2026-09-14-trajectory-record-review.md`, Finding 8).
9. **A 10-step budget binds for this model on this problem.** All five 30-step episodes ended
   in `valid_submission` with `"Yes"`, scored `Correct`, after 10, 20, 8, 11 and 9 steps
   (batches in the order listed in the evidence). Read off with Finding 7:

   | Budget | Correct | Incorrect | No answer |
   |---|---|---|---|
   | 5 | 0 | 0 | 5 |
   | 10 | 3 | 0 | 2 |
   | 15 | 4 | 0 | 1 |
   | 20 | 5 | 0 | 0 |
   | 30 | 5 | 0 | 0 |

   At 10 steps, 2 of 5 episodes would have had no answer. That's five episodes of one
   problem with one model.
10. **`Correct` doesn't mean the fault was found.** Three episodes found it: `130627Z`'s last
    Thought states the port mismatch (27777 against MongoDB's 27017); `130338Z`'s Thoughts
    name port 27777 from action 15; `130845Z` saw 27777 from action 5 but submitted while its
    Thought said it should keep checking. The other two, `130112Z` and `131105Z`, never listed
    pods or read any geo log, and submitted `"Yes"` on the call described in Finding 11.
    Detection grading scores all five the same. On a fault problem, "Yes" scores `Correct`
    whether or not anything was diagnosed; only the no-op problems check for "No".
11. **An oversized observation wipes the episode and cuts off the per-turn instructions.** In
    `130112Z`, `130338Z` and `131105Z`, one `read_traces` observation (219,886, 225,591 and
    237,001 characters; 72–77K tiktoken tokens with the per-turn text) exceeded the 18,000-token
    limit on its own, at calls 10, 9 and 9. Re-running `trim_keeping_task` reproduces each
    recorded call. Each sent only the system prompt, the task instructions and that observation
    cut to its first 17,231 tokens, about 53,000 characters. This is react.py's trimming: when
    the last message alone is over budget, it returns just that message, truncated from the
    end. Because the harness's "Please take the next action", `RESP_INSTR` and
    `THOUGHT_PLACEMENT` sit at the end of the message, all three were cut. All three replies
    were a bare code block with no Thought: `submit("Yes")` in `130112Z` and `131105Z`,
    `get_metrics` in `130338Z`, which then continued from a context missing its first eight
    turns. `130845Z` also dropped older turns at calls 10–11, without truncation.

## Decision

Recording, no change to what agents see:

- `index.jsonl` and `trajectory.json` gain `termination_reason`: `valid_submission`,
  `step_limit`, `invalid_submission` or `error` (`runner/trajectory_checks.py`).
- `trajectory.json`'s `results.final_state` is the submission status name or `null`. The raw
  last observation is still the last `history` entry.
- The agent description's `prompt` becomes `prompt_variant` and `prompt_sha256` becomes
  `prompt_template_sha256`, with its preimage documented in `agents/openai_compatible.py` and
  tested.
- A test now checks the truncation flag against the messages actually sent.
- Grading should drop TTD for episodes without a submission, and not compare TTD across
  serving stacks.

Step budget:

- Five repeated batches of `misconfig_app_hotel_res-detection-1` (a training-split problem;
  `notes/2026-09-14-fault-type-split.md`) at 30 steps with Qwen3-32B on the gateway, condition
  `noise-qwen3-32b-steps30`. Results in Findings 9–11.
- Keep 30 steps, the runner's default, for the B1 trial and baselines. Smoke runs at 10 steps
  can't be read as accuracy. Re-read the budget curve at B1 size from the B1 trial's
  episodes, which are also training-split problems.

## Open

- **Trimming needs a decision before B1** (Finding 11). Proposed: cap each observation before
  the per-turn text is appended, so that text always reaches the model and one large
  observation can't push out every earlier turn; then apply react.py's turn trimming as now.
  That's a further deviation from react.py, applied equally to every condition. Until it's
  decided, any episode that reads traces can take a step with no memory and no Thought.
- Detection success needs a companion that guessing can't satisfy, such as localization
  accuracy or paired no-op problems (Finding 10).
- The adherence denominator. Recommended: violations divided by the actions a rule applies
  to, with per-episode scoring for rules that are per-episode obligations, and episode length
  reported per condition. Decide when the policy rules are written.
- Grading code for other problems may treat malformed answers differently from Finding 2.
- The budget curve at B1 size.

## Correction (2026-09-14): the trimming decision is made

The first Open item is decided. Each observation is now capped at 16,000 tokens before the
per-turn text is appended, and the shared limit is 64,000 tokens, so the truncate-everything
branch in Finding 11 can no longer fire. See
`notes/2026-09-14-observation-cap-and-context-budget.md`.
