"""runner/run_plan.py: each batch gets exactly its own variables, and what a resume can't fix stops the run."""

import json
from pathlib import Path

import pytest

from runner import run_plan, study_plan

PLAN = {b["condition"]: b for b in study_plan.expand()}
COMBINED = PLAN["ladder2-qwen3-next-80b-combined-mitigation"]
NOPOLICY = PLAN["main2-qwen3-next-80b-nopolicy"]


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
    plan.write_text(study_plan.render().replace('"max_steps": 24', '"max_steps": 25', 1))
    monkeypatch.setattr(run_plan, "_git", lambda *a, **k: "ddf7e40619689dad75eaf8f2174e263c4157ec76" if a[0] == "submodule" else "")
    monkeypatch.setenv("OPENAI_BASE_URL", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert any("differs" in f for f in run_plan.preconditions(plan, tmp_path / "missing.json"))
    assert any("no cluster baseline" in f for f in run_plan.preconditions(plan, tmp_path / "missing.json"))
