"""LLM agent via an OpenAI-compatible chat endpoint, prompted like AIOpsLab's ReAct client.

Reads OPENAI_API_KEY / OPENAI_BASE_URL from the environment, which in this
project point at an AWS Bedrock gateway (see open_ai_api_crendentials.txt --
source it before running) or a local vLLM server. Model is chosen by AGENT_MODEL.

Everything about how the model is prompted follows the harness's shipped ReAct
client (third_party/aiopslab/clients/react.py) so the plain-prompting condition
stays plain: the DOCS system template, the task instructions as the first user
message, RESP_INSTR ("Thought: ... Action: ...") appended to every observation,
the same history trimming, and GPTClient's sampling settings. Whatever the model
writes, Thought text included, is recorded in trajectory.json, and record()
adds the messages the model actually received.
Decisions and evidence: notes/2026-09-14-agent-prompt-and-context.md and
notes/2026-09-14-observation-cap-and-context-budget.md.

Four differences from react.py, all needed rather than chosen, and identical for
every condition:
- The token limit is CONTEXT_TOKEN_LIMIT, not 120000: long training contexts for
  T1 and T2 have to fit one 48 GB GPU, and one limit applies to every condition.
- The system and task messages are never trimmed. react.py's trimming drops the
  oldest messages first, so a long episode would lose the problem description,
  the API docs and any instructed policy -- a policy "forgotten" by context
  management rather than by the model.
- THOUGHT_PLACEMENT follows RESP_INSTR. The task instructions every problem
  sends demand a bare code block, which overrides RESP_INSTR's request for a
  Thought; this line resolves that contradiction so reasoning gets recorded.
- Each observation is capped at OBSERVATION_TOKEN_CAP tokens, with a visible
  marker, before the per-turn instructions are appended. Without it, one trace
  read larger than the whole limit makes react.py's trimming send only that
  observation, cut from the end: every earlier turn and the per-turn
  instructions disappear, and no later call can reach past it.

react.py can't be imported here (its module imports groq and azure-identity,
from the harness's skipped `clients` group), so RESP_INSTR and the trimming
helpers are copied verbatim below; tests/test_openai_compatible.py fails if they
drift from the pinned harness.
"""

import hashlib
import os

import httpx
import tiktoken
from openai import AsyncOpenAI, OpenAI

from clients.utils.templates import DOCS

# The smoke model, not a ladder condition: 262,144-token context on the gateway, so the
# limit below is never the model's. Ladder runs set AGENT_MODEL explicitly.
DEFAULT_MODEL = "qwen.qwen3-next-80b-a3b-instruct"

# GPTClient.inference in clients/utils/llm.py, used by react.py.
TEMPERATURE = 0.5
TOP_P = 0.95
MAX_TOKENS = 1024

# Counted with tiktoken like react.py. Qwen3.5's tokenizer counts trace-heavy contexts up to
# 1.5x higher, so 64,000 is about 96,000 Qwen3.5 tokens: the longest sequence estimated to fit
# RL training with vLLM on one 48 GB GPU.
CONTEXT_TOKEN_LIMIT = 64000
# One trace read was 72-77K tokens. 16,000 keeps several large reads plus recent turns in the limit.
OBSERVATION_TOKEN_CAP = 16000

# The harness appends this to every observation it hands the agent (orchestrator.py:173).
HARNESS_NEXT_ACTION = "Please take the next action"


# --- Copied verbatim from third_party/aiopslab/clients/react.py -----------------

RESP_INSTR = """DO NOT REPEAT ACTIONS! Respond with:
Thought: <your thought on the previous output>
Action: <your action towards mitigating>
"""

def count_message_tokens(message, enc):
    # Each message format adds ~4 tokens of overhead
    tokens = 4  # <|start|>role/name + content + <|end|>
    tokens += len(enc.encode(message.get("content", "")))
    return tokens

def trim_history_to_token_limit(history, max_tokens=120000, model="gpt-4"):
    enc = tiktoken.encoding_for_model(model)

    trimmed = []
    total_tokens = 0

    # Always include the last message
    last_msg = history[-1]
    last_msg_tokens = count_message_tokens(last_msg, enc)

    if last_msg_tokens > max_tokens:
        # If even the last message is too big, truncate its content
        truncated_content = enc.decode(enc.encode(last_msg["content"])[:max_tokens - 4])
        return [{"role": last_msg["role"], "content": truncated_content}]

    trimmed.insert(0, last_msg)
    total_tokens += last_msg_tokens

    # Add earlier messages in reverse until limit is reached
    for message in reversed(history[:-1]):
        message_tokens = count_message_tokens(message, enc)
        if total_tokens + message_tokens > max_tokens:
            break
        trimmed.insert(0, message)
        total_tokens += message_tokens

    return trimmed

# --- End of copy -----------------------------------------------------------------

THOUGHT_PLACEMENT = "Write the Thought as plain text before the code block; only the action goes inside the code block.\n"


def cap_observation(observation: str, cap: int = OBSERVATION_TOKEN_CAP) -> tuple[str, int]:
    """Cut the environment's output to `cap` tokens; return the text and the tokens omitted.

    The harness's closing "Please take the next action" is kept after the cut, and a
    marker tells the model how much of the output it isn't seeing.
    """
    body, tail = observation, ""
    if observation.endswith(HARNESS_NEXT_ACTION):
        body, tail = observation[: -len(HARNESS_NEXT_ACTION)], HARNESS_NEXT_ACTION
    enc = tiktoken.encoding_for_model("gpt-4")
    tokens = enc.encode(body)
    if len(tokens) <= cap:
        return observation, 0
    omitted = len(tokens) - cap
    return f"{enc.decode(tokens[:cap])}\n[... {omitted} more tokens of this output not shown ...]\n{tail}", omitted


def trim_keeping_task(history: list[dict], max_tokens: int = CONTEXT_TOKEN_LIMIT) -> list[dict]:
    """react.py's trimming applied to the turns only; the system and task messages always stay."""
    head, turns = history[:2], history[2:]
    enc = tiktoken.encoding_for_model("gpt-4")
    budget = max_tokens - sum(count_message_tokens(m, enc) for m in head)
    return head + trim_history_to_token_limit(turns, max_tokens=budget)


def trim_summary(history: list[dict], sent: list[dict]) -> dict:
    """Which part of `history` one request actually sent, given what trim_keeping_task returned."""
    turns_sent = sent[2:]
    return {
        "messages_in_history": len(history),
        # History index of the first turn sent after the system and task messages; 2 means nothing was dropped.
        "first_turn_sent": len(history) - len(turns_sent),
        "last_message_truncated": turns_sent[-1]["content"] != history[-1]["content"],
    }


def _api_key() -> str:
    # A local vLLM server started without --api-key accepts any key.
    return os.environ.get("OPENAI_API_KEY", "EMPTY")


def serving_details(base_url: str, model: str) -> dict:
    """What the endpoint itself reports about the served model.

    Tells gateway serving from a local server and, for vLLM, pins what was
    loaded: `root` is the weights path or Hugging Face ID, `max_model_len` the
    context the server enforces, `server_version` the vLLM version. `created`
    is left out because vLLM reports the request time. Raises if the endpoint
    can't be reached, so a batch fails before any problem is deployed.
    """
    entries = OpenAI(api_key=_api_key(), base_url=base_url).models.list().data
    entry = next((m.model_dump() for m in entries if m.id == model), None)
    if entry is None:
        raise RuntimeError(f"{base_url} does not serve model {model!r}")
    try:
        response = httpx.get(base_url.rstrip("/").removesuffix("/v1") + "/version", timeout=5)
        version = response.json().get("version") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError, AttributeError):
        version = None
    return {
        "root": entry.get("root"),
        "max_model_len": entry.get("max_model_len"),
        "owned_by": entry.get("owned_by"),
        "server_version": version,
    }


class OpenAICompatibleAgent:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        self.client = AsyncOpenAI(api_key=_api_key(), base_url=os.environ["OPENAI_BASE_URL"])
        self.history: list[dict] = []
        self.calls: list[dict] = []

    @classmethod
    def describe(cls) -> dict:
        """What batch.json records about this agent; a resume must match it exactly."""
        model = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        base_url = os.environ["OPENAI_BASE_URL"]
        return {
            "kind": "LLM via OpenAI-compatible endpoint",
            "model": model,
            # Same model name, different serving stack (gateway vs local vLLM) is a different setup.
            "base_url": base_url,
            "serving": serving_details(base_url, model),
            "prompt_variant": "AIOpsLab clients/react.py (DOCS + RESP_INSTR) + THOUGHT_PLACEMENT, task messages never trimmed",
            # First 12 hex characters of sha256(DOCS + RESP_INSTR + THOUGHT_PLACEMENT), the unformatted
            # templates: it identifies the prompt variant across problems, so a template edit changes the
            # recorded condition. Each problem's rendered prompt isn't hashed; trajectory.json stores it
            # in full as agent_record.messages[0] and [1].
            "prompt_template_sha256": hashlib.sha256((DOCS + RESP_INSTR + THOUGHT_PLACEMENT).encode()).hexdigest()[:12],
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_tokens": MAX_TOKENS,
            "context_token_limit": CONTEXT_TOKEN_LIMIT,
            "observation_token_cap": OBSERVATION_TOKEN_CAP,
        }

    def record(self) -> dict:
        """The conversation as the model received it, for trajectory.json.

        The harness history holds only replies and raw observations. Grading
        against an instructed policy and building T1 training examples both
        need the rendered system prompt and task instructions, the text appended
        to each observation, any cap applied to it, and what trimming actually
        sent on each call.
        """
        return {"messages": self.history, "calls": self.calls}

    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        # As react.py's Agent.init_context.
        shell_api = {k: v for k, v in apis.items() if "exec_shell" in k}
        submit_api = {k: v for k, v in apis.items() if "submit" in k}
        telemetry_apis = {k: v for k, v in apis.items() if "exec_shell" not in k and "submit" not in k}
        stringify = lambda group: "\n\n".join(f"{k}\n{v}" for k, v in group.items())
        system = DOCS.format(
            prob_desc=problem_desc,
            telemetry_apis=stringify(telemetry_apis),
            shell_api=stringify(shell_api),
            submit_api=stringify(submit_api),
        )
        self.history = [
            {"role": "system", "content": system},
            {"role": "user", "content": instructions},
        ]
        self.calls = []

    async def get_action(self, observation: str) -> str:
        capped, omitted = cap_observation(observation)
        self.history.append({"role": "user", "content": capped + "\n\n" + RESP_INSTR + THOUGHT_PLACEMENT})
        messages = trim_keeping_task(self.history)
        self.calls.append({**trim_summary(self.history, messages), "observation_tokens_omitted": omitted})
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": content})
        return content
