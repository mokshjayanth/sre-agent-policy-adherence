"""Real LLM agent via an OpenAI-compatible chat endpoint.

Not tied to OpenAI specifically: reads OPENAI_API_KEY / OPENAI_BASE_URL from the
environment, which in this project point at an AWS Bedrock gateway (see
open_ai_api_crendentials.txt -- source it before running). Model is chosen by
AGENT_MODEL, defaulting to a mid-size open-weight model from that gateway's
catalog. Deliberately minimal: one system message built from the problem
description, instructions and every available API's docstring, then one
assistant/user turn per step. AIOpsLab's parser requires the response to hold
exactly one action in a single markdown code block; the system prompt asks for
that, and a model that gets it wrong gets the parser's error back as its next
observation rather than the run being aborted (see orchestrator.py's ask_env).

Qwen models on this gateway default to near-silent reasoning: asking in plain
English to "think step by step" produced 14 completion tokens for a real
question, versus 631 with the vLLM/Qwen `enable_thinking` chat-template flag
passed explicitly -- confirmed by inspecting the raw response with and without
it; there is no separate reasoning field being dropped, the model just doesn't
produce visible reasoning without being asked this specific way. Adherence
analysis wants that reasoning, so this agent passes the flag for Qwen models.
It's a vLLM/Qwen convention, not a general one -- untested for the rest of the
gateway's catalog, so it's scoped to model names starting with "qwen.".
"""

import hashlib
import os

from openai import AsyncOpenAI

DEFAULT_MODEL = "qwen.qwen3-32b"
TEMPERATURE = 0.7


def _extra_body_for(model: str) -> dict:
    if model.startswith("qwen."):
        return {"chat_template_kwargs": {"enable_thinking": True}}
    return {}

SYSTEM_TEMPLATE = """{prob_desc}

{instructions}

You are provided with the following APIs:

{apis}

At each turn, think step by step, then respond with exactly one action in a
single markdown code block, like this:

Action:
```
api_name(args)
```

Only one code block per response. Call submit(...) only once you are ready to
give your final answer.
"""


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
        model = os.environ.get("AGENT_MODEL", DEFAULT_MODEL)
        return {
            "kind": "LLM via OpenAI-compatible endpoint",
            "model": model,
            "temperature": TEMPERATURE,
            "extra_body": _extra_body_for(model),
            # A prompt edit changes the condition, so it must change what's recorded.
            "system_template_sha256": hashlib.sha256(SYSTEM_TEMPLATE.encode()).hexdigest()[:12],
        }

    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        apis_text = "\n\n".join(f"{name}\n{doc}" for name, doc in apis.items())
        system = SYSTEM_TEMPLATE.format(prob_desc=problem_desc, instructions=instructions, apis=apis_text)
        self.history = [{"role": "system", "content": system}]

    async def get_action(self, observation: str) -> str:
        self.history.append({"role": "user", "content": observation})
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            temperature=TEMPERATURE,
            extra_body=_extra_body_for(self.model),
        )
        content = response.choices[0].message.content or ""
        self.history.append({"role": "assistant", "content": content})
        return content
