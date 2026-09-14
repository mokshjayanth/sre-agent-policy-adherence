"""LLM agent via an OpenAI-compatible chat endpoint, prompted like AIOpsLab's ReAct client.

Reads OPENAI_API_KEY / OPENAI_BASE_URL from the environment, which in this
project point at an AWS Bedrock gateway (see open_ai_api_crendentials.txt --
source it before running). Model is chosen by AGENT_MODEL.

Everything about how the model is prompted follows the harness's shipped ReAct
client (third_party/aiopslab/clients/react.py) so the plain-prompting condition
stays plain: the DOCS system template, the task instructions as the first user
message, RESP_INSTR ("Thought: ... Action: ...") appended to every observation,
the same history trimming, and GPTClient's sampling settings. Whatever the model
writes, Thought text included, is recorded in trajectory.json -- but the task
instructions every problem sends demand a bare code block, and Qwen3-32B obeys
them, so with this prompt it writes no Thought at all. How to keep reasoning is
undecided. Decision and evidence: notes/2026-09-14-agent-prompt-and-context.md.

Two differences from react.py, both needed rather than chosen:
- The token limit is CONTEXT_TOKEN_LIMIT, not 120000: the smallest models in
  scope have a 32,768-token context, and one limit applies to every condition.
- The system and task messages are never trimmed. react.py's trimming drops the
  oldest messages first, so a long episode would lose the problem description,
  the API docs and any instructed policy -- a policy "forgotten" by context
  management rather than by the model.

react.py can't be imported here (its module imports groq and azure-identity,
from the harness's skipped `clients` group), so RESP_INSTR and the trimming
helpers are copied verbatim below; tests/test_openai_compatible.py fails if they
drift from the pinned harness.
"""

import hashlib
import os

import tiktoken
from openai import AsyncOpenAI

from clients.utils.templates import DOCS

DEFAULT_MODEL = "qwen.qwen3-32b"

# GPTClient.inference in clients/utils/llm.py, used by react.py.
TEMPERATURE = 0.5
TOP_P = 0.95
MAX_TOKENS = 1024

# Counted with tiktoken like react.py. Qwen's tokenizer counts trace output about
# 1.5x higher, so 18000 * 1.6 + MAX_TOKENS still fits a 32,768-token context.
CONTEXT_TOKEN_LIMIT = 18000


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


def trim_keeping_task(history: list[dict], max_tokens: int = CONTEXT_TOKEN_LIMIT) -> list[dict]:
    """react.py's trimming applied to the turns only; the system and task messages always stay."""
    head, turns = history[:2], history[2:]
    enc = tiktoken.encoding_for_model("gpt-4")
    budget = max_tokens - sum(count_message_tokens(m, enc) for m in head)
    return head + trim_history_to_token_limit(turns, max_tokens=budget)


class OpenAICompatibleAgent:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        self.client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ["OPENAI_BASE_URL"],
        )
        self.history: list[dict] = []

    @classmethod
    def describe(cls) -> dict:
        """What batch.json records about this agent; a resume must match it exactly."""
        return {
            "kind": "LLM via OpenAI-compatible endpoint",
            "model": os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
            "prompt": "AIOpsLab clients/react.py (DOCS + RESP_INSTR), task messages never trimmed",
            # A prompt edit changes the condition, so it must change what's recorded.
            "prompt_sha256": hashlib.sha256((DOCS + RESP_INSTR).encode()).hexdigest()[:12],
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "max_tokens": MAX_TOKENS,
            "context_token_limit": CONTEXT_TOKEN_LIMIT,
        }

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

    async def get_action(self, observation: str) -> str:
        self.history.append({"role": "user", "content": observation + "\n\n" + RESP_INSTR})
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=trim_keeping_task(self.history),
            temperature=TEMPERATURE,
            top_p=TOP_P,
            max_tokens=MAX_TOKENS,
        )
        content = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": content})
        return content
