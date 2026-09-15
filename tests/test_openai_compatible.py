"""The OpenAI-compatible agent's prompting and trimming, without calling any endpoint."""

import ast
import asyncio
import types
from pathlib import Path

import pytest
import tiktoken

from agents import openai_compatible as oc

REPO_ROOT = Path(__file__).resolve().parents[1]
REACT = REPO_ROOT / "third_party" / "aiopslab" / "clients" / "react.py"
COPIED = ("RESP_INSTR", "count_message_tokens", "trim_history_to_token_limit")
TRACE_DUMP = "3fa2b9c1d4e5 span " * 40000  # far beyond the cap, like a real read_traces
PER_TURN_TEXT = "\n\n" + oc.RESP_INSTR + oc.THOUGHT_PLACEMENT


def _top_level(path: Path) -> dict[str, str]:
    nodes = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.FunctionDef):
            nodes[node.name] = ast.dump(node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            nodes[node.targets[0].id] = ast.dump(node)
    return nodes


def test_copied_react_code_matches_the_pinned_harness():
    shipped, ours = _top_level(REACT), _top_level(Path(oc.__file__))
    for name in COPIED:
        assert ours[name] == shipped[name], f"{name} differs from {REACT}; re-copy it or record why"


APIS = {
    "get_logs": "get_logs doc",
    "exec_shell": "exec_shell doc",
    "submit": "submit doc",
}


def _agent(monkeypatch, reply="Thought: look\nAction:\n```\nsubmit(\"No\")\n```"):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9/v1")
    agent = oc.OpenAICompatibleAgent(model="some-model")
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        message = types.SimpleNamespace(content=reply)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    agent.client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
    return agent, calls


def test_init_context_lays_out_the_prompt_like_react(monkeypatch):
    agent, _ = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    system, task = agent.history
    assert system["role"] == "system" and task == {"role": "user", "content": "INSTRUCTIONS"}
    assert system["content"].startswith("PROBLEM\n")
    assert system["content"].index("get_logs doc") < system["content"].index("exec_shell doc") \
        < system["content"].index("submit doc")
    assert system["content"].endswith("Thought: <your thought>\nAction: <your action>\n")


def test_the_plain_prompt_has_no_instructed_text(monkeypatch):
    monkeypatch.delenv("AGENT_POLICY_FILE", raising=False)
    monkeypatch.delenv("AGENT_PRESSURE_FILE", raising=False)
    agent, _ = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    assert agent.history[0]["content"] == oc.DOCS.format(
        prob_desc="PROBLEM", telemetry_apis="get_logs\nget_logs doc",
        shell_api="exec_shell\nexec_shell doc", submit_api="submit\nsubmit doc")


def _instructed_files(monkeypatch, tmp_path):
    (tmp_path / "policy").mkdir()
    (tmp_path / "policy" / "p.txt").write_text("Operational policy\n\nR1. Only observe.\n")
    (tmp_path / "policy" / "u.txt").write_text("Incident priority: SEV-1.\n")
    monkeypatch.setattr(oc, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AGENT_POLICY_FILE", "policy/p.txt")
    monkeypatch.setenv("AGENT_PRESSURE_FILE", "policy/u.txt")


def test_pressure_then_policy_follow_the_docs_in_the_system_prompt(monkeypatch, tmp_path):
    _instructed_files(monkeypatch, tmp_path)
    agent, _ = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    system, task = agent.history
    assert system["content"].endswith(
        "Action: <your action>\n\nIncident priority: SEV-1.\n\nOperational policy\n\nR1. Only observe.\n")
    assert task == {"role": "user", "content": "INSTRUCTIONS"}


def test_describe_records_each_instructed_file_and_its_hash(monkeypatch, tmp_path):
    import hashlib

    _instructed_files(monkeypatch, tmp_path)
    monkeypatch.setattr(oc, "serving_details", lambda base_url, model: {})
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    policy_hash = hashlib.sha256(b"Operational policy\n\nR1. Only observe.").hexdigest()[:12]
    assert oc.OpenAICompatibleAgent.describe()["instructed_texts"] == [
        {"role": "pressure", "file": "policy/u.txt",
         "sha256": hashlib.sha256(b"Incident priority: SEV-1.").hexdigest()[:12]},
        {"role": "policy", "file": "policy/p.txt", "sha256": policy_hash},
    ]


def test_a_missing_instructed_file_fails_before_any_problem_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(oc, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AGENT_POLICY_FILE", "policy/missing.txt")
    monkeypatch.setattr(oc, "serving_details", lambda base_url, model: {})
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    with pytest.raises(FileNotFoundError):
        oc.OpenAICompatibleAgent.describe()


def test_the_repo_policy_drafts_exist():
    for name in ("policy/draft-v2.txt", "policy/draft-urgency-v1.txt"):
        assert (oc.REPO_ROOT / name).read_text().strip()


def test_get_action_appends_resp_instr_and_uses_the_shipped_sampling(monkeypatch):
    agent, calls = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    reply = asyncio.run(agent.get_action("Please take the next action"))
    [call] = calls
    assert call["messages"][-1]["content"] == "Please take the next action" + PER_TURN_TEXT
    assert (call["temperature"], call["top_p"], call["max_tokens"]) == (0.5, 0.95, 1024)
    assert "extra_body" not in call
    assert agent.history[-1] == {"role": "assistant", "content": reply}


def _tokens(messages):
    enc = tiktoken.encoding_for_model("gpt-4")
    return sum(oc.count_message_tokens(m, enc) for m in messages)


def test_cap_leaves_observations_within_the_cap_untouched():
    for observation in ("Please take the next action", "some logs\nPlease take the next action", "no suffix"):
        assert oc.cap_observation(observation) == (observation, 0)


def test_cap_cuts_the_output_but_keeps_the_harness_request_after_a_marker():
    enc = tiktoken.encoding_for_model("gpt-4")
    observation = TRACE_DUMP + "\nPlease take the next action"
    capped, omitted = oc.cap_observation(observation)
    body_tokens = len(enc.encode(TRACE_DUMP + "\n"))
    assert omitted == body_tokens - oc.OBSERVATION_TOKEN_CAP
    assert capped.endswith(f"\n[... {omitted} more tokens of this output not shown ...]\nPlease take the next action")
    assert observation.startswith(capped.split("\n[... ")[0])
    assert len(enc.encode(capped)) <= oc.OBSERVATION_TOKEN_CAP + 30


def test_a_capped_observation_can_never_trigger_the_truncate_everything_branch():
    enc = tiktoken.encoding_for_model("gpt-4")
    head = [{"role": "system", "content": "system " * 700}, {"role": "user", "content": "task " * 150}]
    capped, _ = oc.cap_observation(TRACE_DUMP + "\nPlease take the next action")
    budget = oc.CONTEXT_TOKEN_LIMIT - sum(oc.count_message_tokens(m, enc) for m in head)
    assert oc.count_message_tokens({"content": capped + PER_TURN_TEXT}, enc) < budget


def test_an_oversized_observation_keeps_earlier_turns_and_the_per_turn_text(monkeypatch):
    agent, calls = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    asyncio.run(agent.get_action("Please take the next action"))
    asyncio.run(agent.get_action(TRACE_DUMP + "\nPlease take the next action"))
    first, second = agent.record()["calls"]
    sent = calls[1]["messages"]

    assert first["observation_tokens_omitted"] == 0
    assert second["observation_tokens_omitted"] > 0
    assert (second["first_turn_sent"], second["last_message_truncated"]) == (2, False)
    assert sent == agent.history[:5]  # system, task, obs 1, reply 1, capped obs 2
    assert sent[-1]["content"].endswith("more tokens of this output not shown ...]\nPlease take the next action" + PER_TURN_TEXT)
    assert _tokens(sent) <= oc.CONTEXT_TOKEN_LIMIT


def test_trim_keeps_task_messages_and_truncates_an_oversized_observation():
    head = [{"role": "system", "content": "system " * 500}, {"role": "user", "content": "policy " * 200}]
    turns = [{"role": "user", "content": f"obs {i}"} for i in range(5)]
    huge = {"role": "user", "content": TRACE_DUMP}
    trimmed = oc.trim_keeping_task(head + turns + [huge])
    assert trimmed[:2] == head
    assert len(trimmed) == 3  # the oversized observation alone fills the turn budget
    assert _tokens(trimmed) <= oc.CONTEXT_TOKEN_LIMIT


def test_trim_drops_oldest_turns_first_but_never_the_task():
    head = [{"role": "system", "content": "S"}, {"role": "user", "content": "T"}]
    turns = [{"role": "user", "content": "word " * 15000} for _ in range(6)]
    trimmed = oc.trim_keeping_task(head + turns)
    assert trimmed[:2] == head
    assert trimmed[2:] == turns[-len(trimmed[2:]):] and len(trimmed[2:]) < len(turns)
    assert _tokens(trimmed) <= oc.CONTEXT_TOKEN_LIMIT


def test_short_histories_are_untouched():
    history = [{"role": "system", "content": "S"}, {"role": "user", "content": "T"},
               {"role": "user", "content": "obs"}]
    assert oc.trim_keeping_task(history) == history


def test_record_keeps_what_the_model_received_and_what_each_call_sent(monkeypatch):
    agent, calls = _agent(monkeypatch)
    agent.init_context("PROBLEM", "INSTRUCTIONS", APIS)
    asyncio.run(agent.get_action("Please take the next action"))
    asyncio.run(agent.get_action("some observation"))
    record = agent.record()
    assert [m["role"] for m in record["messages"]] == ["system", "user", "user", "assistant", "user", "assistant"]
    assert record["messages"][4]["content"].endswith(oc.RESP_INSTR + oc.THOUGHT_PLACEMENT)
    for call in record["calls"]:
        assert call.pop("requested_at") <= call.pop("responded_at")
    assert record["calls"] == [
        {"messages_in_history": 3, "first_turn_sent": 2, "last_message_truncated": False,
         "observation_tokens_omitted": 0},
        {"messages_in_history": 5, "first_turn_sent": 2, "last_message_truncated": False,
         "observation_tokens_omitted": 0},
    ]


def test_trim_summary_reports_dropped_turns_and_truncation():
    head = [{"role": "system", "content": "S"}, {"role": "user", "content": "T"}]
    turns = [{"role": "user", "content": f"obs {i}"} for i in range(4)]
    huge = {"role": "user", "content": TRACE_DUMP}
    history = head + turns + [huge]
    sent = oc.trim_keeping_task(history)
    summary = oc.trim_summary(history, sent)
    assert summary == {"messages_in_history": 7, "first_turn_sent": 6, "last_message_truncated": True}
    assert history[-1]["content"].startswith(sent[-1]["content"]) and sent[-1] != history[-1]


def test_describe_records_everything_that_defines_the_condition(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "model-x")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setattr(oc, "serving_details", lambda base_url, model: {"root": f"{base_url}|{model}"})
    described = oc.OpenAICompatibleAgent.describe()
    assert described["model"] == "model-x"
    assert described["base_url"] == "http://localhost:8000/v1"
    assert described["serving"] == {"root": "http://localhost:8000/v1|model-x"}
    assert (described["context_token_limit"], described["observation_token_cap"]) == (64000, 16000)
    for key in ("prompt_variant", "prompt_template_sha256", "temperature", "top_p", "max_tokens"):
        assert key in described


def test_prompt_template_hash_matches_its_documented_preimage(monkeypatch):
    import hashlib

    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setattr(oc, "serving_details", lambda base_url, model: {})
    preimage = oc.DOCS + oc.RESP_INSTR + oc.THOUGHT_PLACEMENT
    expected = hashlib.sha256(preimage.encode()).hexdigest()[:12]
    assert oc.OpenAICompatibleAgent.describe()["prompt_template_sha256"] == expected


class _FakeModels:
    def __init__(self, entries):
        self.entries = entries

    def list(self):
        return types.SimpleNamespace(data=self.entries)


class _Entry:
    def __init__(self, **fields):
        self.id = fields["id"]
        self.fields = fields

    def model_dump(self):
        return dict(self.fields)


def _fake_endpoint(monkeypatch, entries, version_response):
    monkeypatch.setattr(oc, "OpenAI", lambda **kwargs: types.SimpleNamespace(models=_FakeModels(entries)))
    monkeypatch.setattr(oc.httpx, "get", version_response)


def test_serving_details_reads_what_a_local_vllm_server_reports(monkeypatch):
    entries = [_Entry(id="Qwen/Qwen3.5-2B", root="/models/qwen3.5-2b@abc123", max_model_len=65536,
                      owned_by="vllm", created=1789380000)]
    requested = []

    def version(url, timeout):
        requested.append(url)
        return types.SimpleNamespace(status_code=200, json=lambda: {"version": "0.11.0"})

    _fake_endpoint(monkeypatch, entries, version)
    details = oc.serving_details("http://localhost:8000/v1", "Qwen/Qwen3.5-2B")
    assert details == {"root": "/models/qwen3.5-2b@abc123", "max_model_len": 65536,
                       "owned_by": "vllm", "server_version": "0.11.0"}
    assert requested == ["http://localhost:8000/version"]


def test_serving_details_tolerates_an_endpoint_without_a_version_route(monkeypatch):
    entries = [_Entry(id="qwen.qwen3-32b", owned_by="system", created=1)]
    _fake_endpoint(monkeypatch, entries, lambda url, timeout: types.SimpleNamespace(status_code=404))
    details = oc.serving_details("https://gateway.example/v1", "qwen.qwen3-32b")
    assert details == {"root": None, "max_model_len": None, "owned_by": "system", "server_version": None}


def test_serving_details_fails_early_for_a_model_the_endpoint_does_not_serve(monkeypatch):
    _fake_endpoint(monkeypatch, [_Entry(id="other-model")], lambda url, timeout: None)
    with pytest.raises(RuntimeError, match="does not serve"):
        oc.serving_details("http://localhost:8000/v1", "Qwen/Qwen3.5-2B")
