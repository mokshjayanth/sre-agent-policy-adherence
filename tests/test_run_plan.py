"""runner/run_plan.py: each batch gets exactly its own variables, and what a resume can't fix stops the run."""

import json
from pathlib import Path

import pytest

from runner import run_plan, study_plan

PLAN = {b["condition"]: b for b in study_plan.expand(1) + study_plan.expand(2, {"mitigation": 24, "diagnosis": 7})}
COMBINED = PLAN["ladder3-qwen3-next-80b-combined-mitigation"]
NOPOLICY = PLAN["main3-qwen3-next-80b-nopolicy"]


def test_batch_env_drops_variables_left_from_another_arm(monkeypatch, tmp_path):
    for variable, value in {**COMBINED["env"], "AGENT_ESCALATION_FILE": "x", "AGENT_MODEL": "other"}.items():
        monkeypatch.setenv(variable, value)
    env = run_plan.batch_env(NOPOLICY, tmp_path / "b.json")
    assert not [v for v in study_plan.AGENT_VARIABLES if v in env]
    assert env["AGENT_MODEL"] == NOPOLICY["model"]
    assert env["RUNNER_CLUSTER_BASELINE"] == str((tmp_path / "b.json").resolve())


def test_batch_env_sets_exactly_the_plan_items_variables(tmp_path):
    env = run_plan.batch_env(COMBINED, tmp_path / "b.json")
    assert {v: env[v] for v in study_plan.AGENT_VARIABLES if v in env} == COMBINED["env"]


def test_the_gate_stops_a_batch_whose_agent_is_not_its_arm(monkeypatch, tmp_path):
    monkeypatch.setattr(run_plan, "describe", lambda env: {**COMBINED["expect"], "budget_countdown": False})
    with pytest.raises(run_plan.Stop, match="budget_countdown"):
        run_plan.gate(COMBINED, tmp_path / "b.json")
    monkeypatch.setattr(run_plan, "describe", lambda env: dict(COMBINED["expect"]))
    run_plan.gate(COMBINED, tmp_path / "b.json")


def _batch(tmp_path, records, name="B"):
    batch = tmp_path / name
    batch.mkdir()
    (batch / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    return batch


def test_runner_errors_are_resumed_but_an_unclean_cluster_stops(tmp_path):
    rows = [{"problem_id": "p", "ok": False, "why": "latest attempt status 'error'"},
            {"problem_id": "q", "ok": False, "why": "never run"}]
    timeout = {"problem_id": "p", "status": "error", "error": "TimeoutError: deploy", "started_utc": "2026-09-28T02"}
    run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, [timeout]), rows, since="2026-09-28T01")
    unclean = {**timeout, "error": "RuntimeError: cluster differs from its baseline: ['new: Namespace/debug']"}
    with pytest.raises(run_plan.Stop, match="baseline"):
        run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, [unclean], "C"), rows, since="2026-09-28T01")


def test_an_unclean_refusal_from_before_this_run_is_resumed(tmp_path):
    rows = [{"problem_id": "p", "ok": False, "why": "latest attempt status 'error'"}]
    old = {"problem_id": "p", "status": "error", "started_utc": "2026-09-28T00",
           "error": "RuntimeError: episode would start next to earlier objects: ['default/Pod/x']"}
    run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, [old]), rows, since="2026-09-28T01")


@pytest.mark.parametrize("why", ["system prompt does not end with the arm's texts",
                                 "batch.json run.max_steps 30, expected 24; latest attempt status 'error'",
                                 "cluster_drift None"])
def test_a_wrong_prompt_setup_or_record_stops(tmp_path, why):
    with pytest.raises(run_plan.Stop):
        run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, []), [{"problem_id": "p", "ok": False, "why": why}],
                                    since="2026-09-28T01")


def test_preconditions_refuse_a_plan_file_that_drifted(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text(study_plan.render(1).replace('"max_steps": 30', '"max_steps": 31', 1))
    monkeypatch.setattr(run_plan, "_git", lambda *a, **k: "ddf7e40619689dad75eaf8f2174e263c4157ec76" if a[0] == "submodule" else "")
    monkeypatch.setenv("OPENAI_BASE_URL", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert any("differs" in f for f in run_plan.preconditions(plan, tmp_path / "missing.json"))
    assert any("no cluster baseline" in f for f in run_plan.preconditions(plan, tmp_path / "missing.json"))


def test_a_reset_timeout_is_resumed_until_it_keeps_happening(tmp_path):
    rows = [{"problem_id": "p", "ok": False, "why": "latest attempt status 'error'"}]
    slow = {"problem_id": "p", "status": "error", "started_utc": "2026-09-28T02",
            "error": "RuntimeError: reset_app_state: still present after 600 s: ['namespace/test-social-network']"}
    run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, [slow, slow]), rows, since="2026-09-28T01")
    with pytest.raises(run_plan.Stop, match="timed out 3 times"):
        run_plan._stop_if_unfixable(COMBINED, _batch(tmp_path, [slow] * 3, "C"), rows, since="2026-09-28T01")


def test_a_run_batch_that_ran_nothing_stops_the_run(monkeypatch, tmp_path):
    batch = _batch(tmp_path, [{"problem_id": "p", "status": "error", "started_utc": "2026-09-28T00"}])
    monkeypatch.setattr(run_plan, "find_batches", lambda condition: [batch])
    monkeypatch.setattr(run_plan, "settle", lambda item, baseline: (
        [{"problem_id": "p", "ok": False, "why": "latest attempt status 'error'"}], []))
    monkeypatch.setattr(run_plan, "gate", lambda item, baseline: None)
    monkeypatch.setattr(run_plan, "wait_healthy", lambda: None)
    monkeypatch.setattr(run_plan, "run_batch", lambda item, baseline, resume: 1)   # refused resume
    with pytest.raises(run_plan.Stop, match="without running an episode"):
        run_plan.run_item(COMBINED, tmp_path / "b.json", attempts=3, since="2026-09-28T01")


@pytest.mark.parametrize("stdout,code,expected", [
    ("kind-control-plane   Ready   control-plane   1d   v1.32.0\nkind-worker   Ready   <none>   1d   v1.32.0\n", 0, True),
    ("kind-control-plane   Ready   control-plane   1d   v1.32.0\nkind-worker   NotReady   <none>   1d   v1.32.0\n", 0, False),
    ("   \n\n", 0, False),
    ("", 1, False),
])
def test_healthy_needs_every_node_ready_and_at_least_one(monkeypatch, stdout, code, expected):
    import types
    monkeypatch.setattr(run_plan.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=stdout, stderr=""))
    assert run_plan.healthy() is expected
