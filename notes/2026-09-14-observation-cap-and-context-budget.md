---
date: 2026-09-14
type: decision
status: current
evidence:
  - notes/2026-09-14-step-budget-and-termination.md (Findings 10-11)
  - runs/2026-09-14T130112Z_noise-qwen3-32b-steps30, runs/2026-09-14T130845Z_noise-qwen3-32b-steps30
  - third_party/aiopslab/clients/react.py:29-55, :98
  - third_party/aiopslab/clients/flash.py:91-104, :125-127
  - third_party/aiopslab/aiopslab/orchestrator/actions/base.py:159-161, :209-211
  - https://huggingface.co/Qwen/Qwen3.5-2B (config.json)
  - https://aws.amazon.com/ec2/instance-types/g6e/, https://aws.amazon.com/ec2/instance-types/g6/
  - agents/openai_compatible.py
---

# How should the agent handle an observation larger than its context budget, and what budget?

## Question

In three of five 30-step episodes, one `read_traces` observation was larger than the whole
18,000-token limit. The trimming copied from AIOpsLab's `react.py` then sent only that
observation, cut from the end: every earlier turn and the per-turn instructions were lost, and
two of those episodes answered "Yes" with no Thought and no diagnosis
(`notes/2026-09-14-step-budget-and-termination.md`, Findings 10–11). The 18,000 limit dated
from a 32K-context smoke model. This note decides how observations are handled and what
limit every condition shares.

## What we checked

- Every shipped client in `third_party/aiopslab/clients/` for history trimming, per-message
  caps and output limits, and the harness's `read_metrics`/`read_traces`.
- Per-call context, recomputed from `agent_record` for `130112Z` (wiped) and `130845Z`
  (ordinary trimming).
- All five 30-step episodes tokenized with Qwen3.5-2B's tokenizer (`tokenizer.json` from the
  model page) as well as tiktoken.
- A memory model built from Qwen3.5-2B's `config.json`: weights, per-token activations with
  per-layer gradient checkpointing, vLLM KV cache, and full logits.
- AWS instance pages for G6e and G6.
- Context limits the Bedrock gateway enforces, found by sending one oversized request per
  model with a 1-token output.

## Findings

1. **No shipped client caps a single observation, and neither does the harness.**
   `read_metrics` and `read_traces` return the whole CSV (`actions/base.py:159-161`,
   `:209-211`). `react.py`, `gpt.py` and `openrouter.py` trim the whole history to 120,000
   tokens with the function we copied. `flash.py` uses it too and saves the trimmed history
   as its own (`flash.py:102-104`); its only per-message cut is 300 characters for the last
   5 messages in its side "hindsight" prompt (`:125-127`). `generic_openai.py`, `qwen.py`,
   `deepseek.py`, `vllm.py`, `llama.py` and `gpt_azure_identity.py` send the full history
   every call.
2. **The wipe is one branch of that function.** When the newest message alone exceeds the
   budget, it returns only that message, cut to the budget from the end
   (`react.py:39-42`). In `130112Z` call 10, the budget was 17,235 tokens (18,000 less 765
   for the system and task messages) and the observation was 72,236. The call sent 18,000
   tokens: system, task, and the first 17,231 tokens of the CSV. The 55 tokens of per-turn
   instructions, which sit at the end of the message, were cut. Otherwise, older messages are
   added newest first until one doesn't fit (`react.py:47-53`), as in `130845Z` call 10,
   which dropped 7 old messages to send 17,454 of 19,074 tokens. Because that walk stops at
   the first message that doesn't fit, an oversized observation also hides every older turn
   from all later calls.
3. **At the shipped 120,000-token limit the branch rarely fires.** It needs one observation
   over 120K tokens; the largest in our five episodes was 77,346, and the largest full
   episode 99,008. A limit anywhere between 18K and 77K still triggers it on these traces.
4. **Qwen3.5 counts our contexts 1.20–1.50x higher than tiktoken.** Episodes of logs and
   kubectl output: 1.20–1.21x. Episodes with a trace dump: 1.43–1.47x, and the dumps
   themselves 1.49–1.50x. System and task messages: 1.09x. The largest untrimmed episode was
   99,008 tiktoken tokens and 141,390 Qwen3.5 tokens.
5. **Estimated GPU memory per sequence for Qwen3.5-2B** (weights 4.55 GB bf16; 6 of 24
   layers use full attention with 2 KV heads × 256 dims, the other 18 are linear attention;
   vocabulary 248,320):

   | Qwen3.5 tokens | LoRA SFT | RL, vLLM on the same GPU |
   |---|---|---|
   | 32,000 | 14.4 GB | 22.5 GB |
   | 64,000 | 21.0 GB | 30.6 GB |
   | 96,000 | 27.5 GB | 38.8 GB |
   | 120,000 | 32.4 GB | 44.9 GB |
   | 160,000 | 40.6 GB | 55.0 GB |

   Assumptions: LoRA, one sequence per step, per-layer gradient checkpointing, memory-linear
   attention kernels, about 3 GB of CUDA overhead; RL adds a vLLM copy of the weights, 4 live
   sequences and 2 GB for vLLM. Serving one sequence costs about 7–8.5 GB at any of these
   lengths (KV cache 12.3 KB per token). Computing full logits would add 0.99 MB per token,
   so training must compute loss on assistant tokens only. None of this is measured; treat it
   as roughly ±30%.
6. **Instances:** g6e.xlarge has one L40S with 48 GB, 4 vCPUs and 32 GiB; g6e.2xlarge the same
   GPU with 8 vCPUs and 64 GiB. g6.xlarge has one L4 with 24 GB, 4 vCPUs and 16 GiB.
7. **Gateway context limits:** Qwen3-32B 32,768; Kimi-K2.5 262,144; GLM-5 202,752;
   Qwen3-235B-A22B-2507 262,144; Qwen3-Next-80B-A3B-Instruct 262,144; Ministral-3-3B 131,072.

## Decision

- **Each observation is capped at 16,000 tiktoken tokens before the per-turn instructions are
  appended** (`OBSERVATION_TOKEN_CAP`). A marker states how many tokens were omitted, and the
  harness's "Please take the next action" stays after it. Each call records
  `observation_tokens_omitted`. A capped message always fits the budget, so the
  truncate-everything branch can't fire.
- **The shared limit becomes 64,000 tiktoken tokens** (`CONTEXT_TOKEN_LIMIT`), at most about
  96,000 Qwen3.5 tokens: on the estimates, the longest sequence that fits RL with vLLM on one
  48 GB GPU with some margin. Both values are in the agent description, so resume refuses to
  mix them. With the cap, the five episodes' largest contexts would have been around 42,000
  tokens (99,008 − 73,131 + 16,000), so none would be trimmed.
- **Instance: g6e** (xlarge now, 2xlarge when the vCPU quota allows), not g6. On 24 GB the RL
  estimate forces the limit back to about 16,000.
- **Before B1 runs:** one LoRA training step at 96,000 Qwen3.5 tokens on the instance. Lower
  the limit only if it runs out of memory.
- **Smoke model:** `qwen.qwen3-next-80b-a3b-instruct`, whose gateway limit is well above the
  budget. Qwen3-32B's 32,768 would now be the binding limit.
- **B1 trial:** SmolLM3-3B is dropped; it was trained on 64K contexts, below the budget in its
  own tokens.
- Rejected: the shipped 120,000 limit without a cap, which puts T2 at an estimated 60 GB, and
  training on shorter contexts than evaluation would mismatch T1's data. Also rejected:
  raising the limit without a cap, which leaves the wipe in place for 72–77K observations.

**Disclose in the paper**, in the method and an appendix on harness and scaffold changes:

- The agent's context management differs from AIOpsLab's ReAct client in four ways, the same
  for every condition: a 64,000-token limit, system and task messages never trimmed, the
  Thought-placement line, and the 16,000-token observation cap. Say why: T2 training has to
  fit one 48 GB GPU, and the shipped trimming erases the episode when one tool output exceeds
  the limit.
- Agents never see more than 16,000 tokens of a single tool output, so large trace and metrics
  reads are partial.
- Per condition, report how often the cap fired and how many tokens it omitted. A post-trained
  model that reads traces more or less often changes its own exposure to the cap, so this is a
  behaviour-dependent difference between conditions, not a constant.
- The shipped trimming's single-message branch, as a note for anyone running AIOpsLab with a
  smaller context than 120K.
- The harness-level workarounds in `runner/harness_fixes.py` (OTel chart pin, port-forward
  cleanup, exec_shell docs) belong in the same appendix.

## Open

- The memory estimates are unmeasured; the one-step check above settles them. The estimate
  covers Qwen3.5-2B only; a dense B1 alternative such as Ministral-3-3B costs more at the same
  length.
- An episode can still exceed 64,000 tokens, for example with several capped reads, and then
  loses its oldest turns. System and task messages are always kept.
- The agent can't page through the rest of a capped output. `read_traces` has no offset, and
  `exec_shell` runs inside the kind control-plane container, while the CSV is written on the
  host.
- Tokenizer ratios for Kimi-K2.5 and GLM-5 are unmeasured; their limits leave a wide margin.
- For grading, a `history` env entry is no longer a substring of the agent's message when the
  cap fired; the capped part is then a prefix of it.

## Verification (2026-09-14)

- **Smoke batches with the new agent and smoke model:**
  `runs/2026-09-14T142739Z_smoke-qwen3-next-80b-cap`, `runs/2026-09-14T143008Z_smoke-qwen3-next-80b-cap`
  and `runs/2026-09-14T143253Z_smoke-qwen3-next-80b-cap` (commit `0b4c7d2`, 30-step budget). All
  three submitted `"Yes"`, scored `Correct`, after 7, 13 and 7 steps. All 27 replies had a
  Thought and there were no parse errors. Each episode inspected the geo pod. None called
  `read_traces`, so the cap never fired and nothing was trimmed. These runs check the model and
  the recording, not the cap.
- **Replay of the call that wiped an episode.** The agent was given
  `runs/2026-09-14T130112Z_noise-qwen3-32b-steps30`'s recorded history up to call 10 and that
  call's raw observation (219,914 characters, the trace dump plus the harness's request), with
  the new default model on the gateway. The call record was `first_turn_sent: 2`,
  `last_message_truncated: false`, `observation_tokens_omitted: 56178`. It sent all 21 messages,
  27,995 tokens; before the fix the same call sent 3 messages, 18,000 tokens. The sent message
  ended with the marker, the harness's request and the per-turn instructions. The reply had a
  Thought citing 5xx errors on `/geo.Geo/Nearby` and `/search.Search/Nearby` from the visible
  part of the trace, and the harness's `ResponseParser` parsed its action as `submit("Yes")`.
  One replay on one model; the cap has not yet fired inside a live episode.
