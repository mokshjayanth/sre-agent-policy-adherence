---
date: 2026-09-14
type: decision
status: current
evidence:
  - third_party/aiopslab/clients/react.py:18 (RESP_INSTR), :29 (trim_history_to_token_limit), :98 (trimming call)
  - third_party/aiopslab/clients/utils/templates.py:8 (DOCS)
  - third_party/aiopslab/clients/utils/llm.py:124-126 (GPTClient sampling)
  - third_party/aiopslab/aiopslab/orchestrator/parser.py:66-70 (code block extraction)
  - third_party/aiopslab/aiopslab/orchestrator/orchestrator.py:109 (full response recorded)
  - third_party/aiopslab/aiopslab/orchestrator/tasks/detection.py:40-43 (and the same lines in analysis.py, localization.py, mitigation.py)
  - runs/2026-09-14T091300Z_smoke-qwen3-32b-fix (earlier agent prompt)
  - runs/2026-09-14T095605Z_smoke-qwen3-32b-react (this decision)
  - https://huggingface.co/Qwen/Qwen3-1.7B
  - agents/openai_compatible.py
---

# How should the LLM agent be prompted, and how should it manage context?

## Question

The first two smoke runs used a prompt written for this project. In the second
(`runs/2026-09-14T091300Z_smoke-qwen3-32b-fix`), the agent replied with bare
actions and no reasoning, and one `read_traces` observation was 202,771
characters. Two questions follow, and both define the plain-prompting condition
(B1) that every other condition is compared against:

1. What prompt should the agent get? B1 must stay plain, deviate from the
   shipped harness as little as possible, and still keep the agent's stated
   reasoning. Grading adherence to a policy needs it as a secondary signal.
2. What happens when the conversation outgrows the model's context?

## What we checked

- The harness's shipped clients. `clients/react.py` is the only ReAct-style one.
  It uses `DOCS` from `clients/utils/templates.py`, sends the task instructions
  as the first user message, appends `RESP_INSTR` to every observation, and
  trims history with `trim_history_to_token_limit(max_tokens=120000)`. It calls
  `GPTClient`, which sends `max_tokens=1024, temperature=0.5, top_p=0.95`.
  `clients/gpt.py`, `generic_openai.py`, `qwen.py` and the others use
  `DOCS_SHELL_ONLY`, which asks for `Action:` only.
- Whether `clients/react.py` can be imported in our environment. It can't:
  `clients/utils/llm.py` imports `groq` and `azure.identity`, which are in the
  skipped `clients` group (`ModuleNotFoundError: No module named 'groq'`).
  `clients/utils/templates.py` imports cleanly.
- The gateway's context limit for `qwen.qwen3-32b`, found by sending an
  oversized request. It returned 400: "This model's maximum context length is
  32768 tokens."
- How tiktoken's `gpt-4` encoding (the one react.py counts with) compares with
  the gateway's own `usage.prompt_tokens`, on content from the earlier batch:

  | Content | Characters | tiktoken | Qwen | Ratio |
  |---|---|---|---|---|
  | `read_traces` observation (first 60,000 chars) | 60,000 | 19,667 | 29,150 | 1.48 |
  | `kubectl get pods` observation | 1,560 | 550 | 627 | 1.14 |
  | `aiopslab/orchestrator/tasks/detection.py` source | 2,714 | 579 | 578 | 1.00 |

- A smoke batch with the react.py-style agent,
  `runs/2026-09-14T095605Z_smoke-qwen3-32b-react`: same problem and step limit
  as the earlier batch.
- Replays of that batch's exact first turn against the gateway, without the
  cluster loop. Each probe varied one thing and recorded `usage.completion_tokens`,
  the response fields, and whether the harness's own `ResponseParser.parse`
  accepts the reply:
  - the shipped prompt, three times;
  - the shipped prompt plus `enable_thinking: true`;
  - the shipped prompt without the task-instructions message;
  - the shipped prompt with one line added, either after `RESP_INSTR` or at the
    end of the system prompt, two times each. The line: "Write the Thought as
    plain text before the code block; only the action goes inside the code
    block."

## Findings

1. **The shipped prompt gets no reasoning from this model.** In
   `runs/2026-09-14T095605Z_smoke-qwen3-32b-react`, all 10 assistant turns are a
   bare code block with no `Thought:` line. The run was `submitted: false` and
   scored `Invalid Format`, with 1 parse error from a missing code fence.
2. **Nothing is generated and then hidden.** On the replayed first turn,
   `completion_tokens` was 17, 17 and 18, matching the 63-character visible
   reply, and no response had fields beyond `content` and `role`. With
   `enable_thinking: true` the result was the same (18 tokens). The flag has no
   effect on this gateway. The earlier agent's docstring claimed it raised
   output from 14 to 631 tokens; that was not reproduced (unverified: the
   original probe wasn't recorded).
3. **The harness's own instructions conflict.** `DOCS` and `RESP_INSTR` ask for
   `Thought: ... Action: ...`. The task instructions every problem sends say
   "Please respond in the following format in a markdown code block" and "your
   response must be exactly" a code block (`tasks/detection.py:40-43`; the same
   in `analysis.py`, `localization.py` and `mitigation.py`). Qwen3-32B follows
   the task instructions:
   - With the task-instructions message removed, the reply had a Thought
     (44 tokens), but the action wasn't in a code block, so it wouldn't parse.
   - With the one added line after `RESP_INSTR`, both replies had a Thought
     *and* parsed (`get_logs('test-hotel-reservation', 'hotel-reservation')`;
     45 and 41 tokens).
   - With the same line at the end of the system prompt, neither reply had a
     Thought (18 and 17 tokens). The task instructions arrive after it and win.

   So react.py itself, run on this pin with this model, would record no
   reasoning either.
4. **react.py's 120,000-token limit doesn't fit.** The gateway's Qwen3-32B has a
   32,768-token context. Qwen3-1.7B, a candidate at the planned 1-3B B1 size,
   lists the same ("Context Length: 32,768",
   https://huggingface.co/Qwen/Qwen3-1.7B). Other B1 candidates are unchecked.
   Trace data counts about 1.5x higher in Qwen tokens than in tiktoken. The
   react batch never came near the limit (`in_tokens` 2,818), so trimming wasn't
   exercised on the cluster; `tests/test_openai_compatible.py` covers it.
5. **react.py's trimming drops the task.** It keeps the newest messages and drops
   the oldest first, system prompt included. When one observation exceeds the
   limit, it returns only that observation, truncated. A long episode would
   therefore lose the problem description, API docs and any instructed policy.
   For an adherence study that's a confound: the policy would vanish through
   context management, not because the model ignored it.
6. **Constructing a problem touches the cluster.** Running
   `ProblemRegistry().get_problem_instance("misconfig_app_hotel_res-detection-1")`
   for the replays created the `test-hotel-reservation` namespace and four
   ConfigMaps (seen in the probe's output; the source line wasn't traced). No
   workloads, no Helm release. The namespace was deleted afterwards. The
   runner only constructs problems inside `Orchestrator.init_problem`, which
   deploys and cleans up anyway. A `test-social-network` namespace with no
   resources, created 2026-09-14T08:29:13Z, may have the same cause
   (unverified).

## Decision

`agents/openai_compatible.py` follows react.py for everything about prompting,
for every condition:

- The `DOCS` system template, imported from the harness.
- The task instructions as the first user message.
- `RESP_INSTR` appended to each observation.
- react.py's trimming function.
- `GPTClient`'s sampling: `temperature=0.5, top_p=0.95, max_tokens=1024`.
- No `enable_thinking` flag and no model-specific request options.

`RESP_INSTR` and the trimming helpers are copied verbatim, since react.py can't
be imported. `tests/test_openai_compatible.py` compares them with the pinned
harness source.

Two deviations, both needed:

- **Limit.** `CONTEXT_TOKEN_LIMIT = 18000` tiktoken tokens for all conditions.
  At the worst measured ratio plus margin (1.6x) that's 28,800 Qwen tokens, plus
  1,024 for output: under 32,768.
- **Task messages are never trimmed.** react.py's function is applied to the
  turns after the system and task messages, with whatever budget those two
  leave.

`describe()` records the prompt hash, sampling settings and limit, so resume
refuses to mix them within a batch.

**Not yet decided: how to keep reasoning (Finding 3).** With the shipped
prompt, trajectories record actions only. Adherence can still be graded from
actions, but the secondary measure (the agent recognising a rule and breaking
it anyway) has nothing to read. Options:

- (a) Accept action-only trajectories. No deviation; reasoning coverage is zero
  for this model.
- (b) Append the one reconciling line after `RESP_INSTR` for every condition. It
  clears up a contradiction inside the harness rather than adding guidance, and
  it worked in 2 of 2 replays. It is still a prompt change, and asking for
  reasoning may itself change behaviour; it applies equally to all conditions.
- (c) Take reasoning out of band where the serving stack returns it separately
  (for example a local vLLM with a reasoning parser, for the B1 1-3B models).
  This leaves the prompt as shipped but can't be used on this gateway, and it
  would make the frontier and open-model conditions record reasoning
  differently.

## Open

- The reasoning decision above.
- `RESP_INSTR` says "DO NOT REPEAT ACTIONS!". A policy that requires re-checking
  after a change could conflict with it. Revisit when the policy text is
  written.
- The 1.6x margin comes from one trace sample. Other telemetry, such as metric
  CSVs, is unmeasured.
- A policy longer than about a few thousand tokens would leave little budget for
  turns. Check when the policy text exists.
- The reconciling line was tested on one first turn, 2 samples. A full batch
  would be needed before relying on it.
