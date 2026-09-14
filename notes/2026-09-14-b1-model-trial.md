---
date: 2026-09-14
type: decision
status: current
evidence:
  - runs/2026-09-14T161925Z_smoke-qwen3.5-2b
  - runs/2026-09-14T170346Z_smoke-qwen3-4b-instruct-2507
  - runs/2026-09-14T171156Z_smoke-qwen3.5-4b
  - notes/2026-09-14-qwen35-2b-local-serving.md
  - third_party/aiopslab/aiopslab/orchestrator/parser.py:16-18
  - agents/openai_compatible.py (THOUGHT_PLACEMENT)
---

# Which model is B1, and what does the agent need to show it?

## Question

Qwen3.5-2B, the planned B1, executed no actions in a 30-step smoke episode: every reply
failed the harness's parser (`notes/2026-09-14-qwen35-2b-local-serving.md`, Finding 6). B1 is
the base for B2, T1 and T2, and a B1 that can't act makes both task success and adherence
unmeasurable. Which candidate should B1 be, chosen on whether it can act, never on adherence?

## What we checked

- **Candidates,** each served locally with vLLM 0.29.0 on the g5.xlarge's A10G with
  `VLLM_USE_FLASHINFER_SAMPLER=0`, `--generation-config vllm`, pinned revisions and weights on
  the EBS cache:
  - Qwen3.5-2B, revision `15852e8c16360a2fea060d615a32b45270f8a8fc`, 100K context.
  - Qwen3-4B-Instruct-2507, revision `cdbee75f17c01a7cc42f958dc650907174af0554`, served at 65K:
    at 100K vLLM needed 13.73 GiB of KV cache and had 8.97 GiB, and estimated a maximum of
    65,312.
  - Qwen3.5-4B, revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, 100K context, thinking
    turned off with `--default-chat-template-kwargs '{"enable_thinking": false}'` because its
    model card says Qwen3.5 thinks by default. No reply contained `<think>`, and completion
    tokens matched the visible text.
  - Ministral-3-3B-Instruct-2512-BF16, revision `b6d637bef2393152b3da2b2fde72eecdee30557e`:
    never served (Finding 5).
  - Control: `qwen.qwen3-next-80b-a3b-instruct` on the Bedrock gateway.
- **Replay:** the three turn-1 messages the agent sent in
  `runs/2026-09-14T161925Z_smoke-qwen3.5-2b` (system prompt, task instructions, first
  per-turn message), sent 20 times to each model at the agent's settings (temperature 0.5,
  top_p 0.95, 1,024 max tokens). Every reply went through the harness's `ResponseParser`. Turn
  1 is the only turn every model sees identically. Two variants of the per-turn message: as
  recorded, and with the Thought-placement line replaced by one showing the action fenced on its
  own lines, reusing the harness's own `exec_shell("ls -l")` example.
- **Episodes:** one 30-step batch of `misconfig_app_hotel_res-detection-1`, a training-split
  problem, per served model, with the prompt as recorded.

## Findings

1. **Results:**

   | Model | Replay, as recorded | Replay, fenced example | Episode, as recorded |
   |---|---|---|---|
   | Qwen3.5-2B | 2/20 | 13/20 | 0 of 30 actions executed, `step_limit` |
   | Qwen3-4B-Instruct-2507 | 0/20 | not run | 0 of 30 actions executed, `step_limit` |
   | Qwen3.5-4B | 6/20 | 20/20 | `valid_submission` "Yes", `Correct`, 10 steps, 9 of 10 actions executed |
   | Qwen3-Next-80B (control) | 20/20 | 20/20 | earlier batches: 3 of 3 correct |

   The control parsing 20/20 on the same messages shows the replay itself is sound.
2. **The small models' failure is mostly one shape: an unfenced action.** As recorded, replies
   had a Thought and then the action written inline after `Action:`, with no code block, which
   the parser rejects ("Only have one pair of three ticks"). Qwen3-4B-Instruct's actions were
   otherwise well formed (`get_logs("test-hotel-reservation", "Hotel Reservation")`), and in its
   episode none of the 30 replies contained a backtick. The per-turn text at the time said
   `Action: <your action>` (react.py's `RESP_INSTR`) and "only the action goes inside the code
   block", with no example.
3. **Qwen3.5-2B also fails beyond the fence.** With the fenced example, 13 of its 20 replies
   parsed, and only 6 were a clean `get_logs('test-hotel-reservation', 'Hotel Reservation')`;
   one parsed reply ran two commands together. The 7 failures put arguments on separate lines
   (`namespace(test-hotel-reservation), service(Hotel Reservation)`), called `get_logs` with no
   arguments, or left arguments unquoted. In its episode it spent turns 6–15 reasoning about the
   parser's error message, whose own examples are fenced, and then gave up.
4. **Qwen3.5-4B recovers even without the example.** In its episode, turn 1 was unfenced and
   rejected; from turn 2, after reading the parser's error message, every reply had exactly one
   fence. It checked logs, services, metrics and traces and submitted a correct "Yes". Its call
   10 was the first live firing of the observation cap: 61,140 tokens omitted, nothing dropped or
   truncated, per-turn instructions intact, and a Thought and parseable action in reply.
5. **Ministral-3-3B couldn't be served in this environment.** vLLM 0.29.0's `pixtral.py` imports
   `PixtralRotaryEmbedding` from transformers, which transformers 5.17.0 renamed
   `PixtralVisionRotaryEmbedding`; vLLM only requires `transformers>=5.10.4`. Serving it would
   need a separate environment with an older transformers, since the Qwen3.5 stack is validated
   on 5.17.0.
6. **Qwen3.5-4B costs about twice as much to train as the 2B.** From each `config.json`, with the
   memory model in `notes/2026-09-14-observation-cap-and-context-budget.md`:

   | Qwen3.5 tokens | 2B: LoRA SFT / RL with vLLM | 4B: LoRA SFT / RL with vLLM |
   |---|---|---|
   | 48,000 | 17.7 / 26.6 GB | 27.8 / 45.4 GB |
   | 64,000 | 21.0 / 30.6 GB | 32.8 / 52.5 GB |
   | 96,000 | 27.5 / 38.8 GB | 42.9 / 66.8 GB |

   The 4B has 9.32 GB of weights, hidden size 2,560, intermediate 9,216 and 32 layers (8 full
   attention), for about 315 KB per token of activations and 32.8 KB per token of KV cache. At
   the current budget (up to about 96,000 Qwen3.5 tokens), RL with vLLM on the same 48 GB GPU is
   estimated not to fit. Unmeasured, roughly ±30%.

## Decision

- **The fenced example is adopted for every condition.** `THOUGHT_PLACEMENT` now reads "Write the
  Thought as plain text. Then write Action: and put only the action inside a markdown code block
  on its own lines", followed by a fenced `exec_shell("ls -l")`. It spells out a requirement the
  harness already enforces, and it left the control unchanged. The prompt hash changes, so
  batches before and after are recorded as different conditions.
- **B1 is Qwen3.5-4B,** served as in `notes/2026-09-14-qwen35-2b-local-serving.md` with its own
  revision and thinking off. It is the only candidate that cleared the bar (16 of 20 parseable
  replies, and an episode that submits). This departs from ADR v3's 1–3B band: the only 1–3B
  candidate tested, Qwen3.5-2B, didn't clear the format floor even with the example.
- **Ministral-3-3B is not tested.** It is 3.4B against 4B, also outside the band, dense (KV cache
  106.5 KB per token against 32.8), and would need a different library stack from B1, T1 and T2.
- **Training memory:** the 64,000-token limit stays for now. On the g6e, measure RL for Qwen3.5-4B
  with vLLM's sleep mode, which frees vLLM's memory during training steps, before lowering the
  limit or adding a GPU.

## Open

- Confirming episode with Qwen3.5-4B under the new per-turn text: pending.
- The scope of Findings 1–3. They cover one problem's turn 1 and one episode per model, at
  temperature 0.5, under AIOpsLab's free-text action format. They show that these small models
  fail this parser with this prompt, not that 2–3B models can't act: Qwen3.5-2B is the only model
  tested inside that band, react.py's prompt without our Thought-placement line wasn't replayed
  on the small models, and lower temperatures weren't tried.
- The fenced example has been checked on Qwen3-Next only among larger models. Check it on the B3
  candidates.
- Whether Qwen3.5-4B's RL memory fits one 48 GB GPU with sleep mode.
