"""runner/verify_plan.py: an episode passes only with its arm's exact prompt and a proven clean start."""

import json
from pathlib import Path

import pytest

from runner import study_plan
from runner.verify_plan import (
    COUNTDOWN,
    DOCS_TAIL,
    PER_TURN,
    batch_mismatches,
    episode_mismatches,
    expected_texts,
    prompt_mismatches,
    verify,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN = {b["condition"]: b for b in study_plan.expand()}
POLICY = PLAN["main2-mistral-large3-policy"]
NOPOLICY = PLAN["main2-mistral-large3-nopolicy"]
BUDGET = PLAN["main2-mistral-large3-budget"]
ONCE = PLAN["ladder2-mistral-large3-budgetonce-mitigation"]
MEDIAN = PLAN["ladder2-mistral-large3-budgetmedian-mitigation"]
COMBINED = PLAN["ladder2-mistral-large3-combined-diagnosis"]


def trajectory(item, problem_id="k8s_target_port-misconfig-mitigation-2", calls=3, texts=None, countdown=None,
               batch_id="B"):
    task = "mitigation" if "mitigation" in problem_id else "diagnosis"
    texts = expected_texts(item["expect"], task) if texts is None else texts
    system = "You are an SRE..." + DOCS_TAIL + ("\n" + "\n\n".join(texts) + "\n" if texts else "")
    countdown = item["expect"]["budget_countdown"] if countdown is None else countdown
    n = item["expect"]["step_budget"]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": "task"}]
    for i in range(calls):
        suffix = PER_TURN + (COUNTDOWN.format(left=n - i, n=n) if countdown else "")
        messages += [{"role": "user", "content": f"observation {i}\n\n" + suffix},
                     {"role": "assistant", "content": "Thought: ..."}]
    return {"problem_id": problem_id, "batch_id": batch_id, "condition": item["condition"],
            "agent_description": {**item["expect"]}, "agent_record": {"messages": messages, "calls": [{}] * calls}}


def clean_record(problem_id="k8s_target_port-misconfig-mitigation-2"):
    return {"problem_id": problem_id, "status": "ok", "reset": {"deleted_namespaces": [], "deleted_default": []},
            "preexisting_objects": [], "cluster_drift": [], "cluster_baseline_sha256": "abc"}


@pytest.mark.parametrize("item", [POLICY, NOPOLICY, BUDGET, ONCE, MEDIAN], ids=lambda i: i["condition"])
def test_an_episode_with_its_arms_prompt_passes(item):
    assert prompt_mismatches(trajectory(item), item["expect"], item["max_steps"]) == []


def test_a_diagnosis_episode_gets_the_diagnosis_texts():
    t = trajectory(COMBINED, problem_id="auth_miss_mongodb-localization-1")
    assert prompt_mismatches(t, COMBINED["expect"], COMBINED["max_steps"]) == []
    assert len(expected_texts(COMBINED["expect"], "diagnosis")) == 3        # budget, scored, policy


@pytest.mark.parametrize("ran,checked", [(POLICY, NOPOLICY), (NOPOLICY, POLICY), (POLICY, BUDGET),
                                         (ONCE, MEDIAN), (MEDIAN, ONCE), (MEDIAN, COMBINED),
                                         (ONCE, PLAN["ladder2-mistral-large3-budgetonce-diagnosis"])],
                         ids=lambda i: i["condition"])
def test_an_episode_with_another_arms_prompt_fails(ran, checked):
    problem = "k8s_target_port-misconfig-mitigation-2"
    assert prompt_mismatches(trajectory(ran, problem), checked["expect"], checked["max_steps"])


def test_a_missing_or_wrong_countdown_fails():
    assert prompt_mismatches(trajectory(MEDIAN, countdown=False), MEDIAN["expect"], 24)
    assert prompt_mismatches(trajectory(ONCE, countdown=True), ONCE["expect"], 24)


def test_extra_text_after_the_policy_fails():
    t = trajectory(POLICY)
    t["agent_record"]["messages"][0]["content"] += "\nFinish fast.\n"
    assert prompt_mismatches(t, POLICY["expect"], 30)


def test_escalation_and_too_many_calls_fail():
    t = trajectory(POLICY)
    t["agent_record"]["calls"] = [{}, {"escalation_delivered": ["x"]}, {}]
    assert "an escalation message was delivered" in prompt_mismatches(t, POLICY["expect"], 30)
    assert prompt_mismatches(trajectory(BUDGET, calls=16), BUDGET["expect"], 15)


def test_a_clean_episode_passes_and_every_unclean_start_fails():
    t = trajectory(POLICY)
    assert episode_mismatches(clean_record(), t, POLICY, "B", "abc") == []
    for key, value in (("preexisting_objects", ["default/Pod/x"]), ("cluster_drift", ["new: observe/ConfigMap/x"]),
                       ("reset", None), ("preexisting_objects", None), ("cluster_drift", None),
                       ("cluster_baseline_sha256", "other"), ("status", "error")):
        assert episode_mismatches({**clean_record(), key: value}, t, POLICY, "B", "abc"), key


def test_a_trajectory_from_another_batch_or_model_fails():
    assert episode_mismatches(clean_record(), trajectory(POLICY, batch_id="C"), POLICY, "B", "abc")
    t = trajectory(POLICY)
    t["agent_description"]["model"] = "openai.gpt-oss-120b"
    assert episode_mismatches(clean_record(), t, POLICY, "B", "abc")


def _write_batch(runs: Path, item: dict, records: list[dict], trajectories: dict, **run_overrides):
    batch = runs / f"2026-09-28T000000Z_{item['condition']}"
    (batch / "problems").mkdir(parents=True)
    manifest = {"repo": {"commit": "c", "dirty": "False", "status": []},
                "harness": {"aiopslab_commit": "ddf7e40619689dad75eaf8f2174e263c4157ec76", "status": []},
                "cluster": {"kind_node_image": "img"}, "python": {"pip_freeze": []}, "pins": {},
                "run": {"condition": item["condition"], "agent": "openai-compatible", "max_steps": item["max_steps"],
                        "problems": item["problems"], "skipped": {}, "agent_description": {**item["expect"]},
                        **run_overrides}}
    (batch / "batch.json").write_text(json.dumps(manifest))
    (batch / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    for problem_id, t in trajectories.items():
        (batch / "problems" / problem_id).mkdir()
        (batch / "problems" / problem_id / "trajectory.json").write_text(json.dumps({**t, "batch_id": batch.name}))
    return batch


def test_verify_passes_a_complete_clean_batch_and_uses_the_latest_attempt(tmp_path):
    item = ONCE
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}")
    import hashlib
    sha = hashlib.sha256(baseline.read_bytes()).hexdigest()
    records = [{**clean_record(p), "cluster_baseline_sha256": sha} for p in item["problems"]]
    records.insert(0, {"problem_id": item["problems"][0], "status": "error", "error": "timeout"})
    _write_batch(tmp_path, item, records, {p: trajectory(item, p) for p in item["problems"]})
    rows, problems = verify({"items": [item]}, baseline, runs_root=tmp_path)
    assert problems == [] and all(r["ok"] for r in rows) and len(rows) == 8


def test_verify_fails_a_batch_with_the_wrong_step_limit_or_a_changed_resume(tmp_path):
    item = ONCE
    batch = _write_batch(tmp_path, item, [], {}, max_steps=30)
    (batch / "resume-1.json").write_text(json.dumps({"changed_from_batch": ["repo.commit"]}))
    why = batch_mismatches(batch, item)
    assert any("max_steps" in w for w in why) and any("resume-1.json" in w for w in why)


def test_verify_flags_two_batches_for_one_condition(tmp_path):
    _write_batch(tmp_path, ONCE, [], {})
    rows, problems = verify({"items": [ONCE]}, None, runs_root=tmp_path)
    assert all(r["why"] == "never run" for r in rows)
    other = tmp_path / f"2026-09-29T000000Z_{ONCE['condition']}"
    other.mkdir()
    (other / "batch.json").write_text((tmp_path / f"2026-09-28T000000Z_{ONCE['condition']}" / "batch.json").read_text())
    rows, problems = verify({"items": [ONCE]}, None, runs_root=tmp_path)
    assert problems == [f"{ONCE['condition']}: 2 batch folders"]


def test_verify_flags_a_batch_run_from_a_dirty_repo(tmp_path):
    batch = _write_batch(tmp_path, ONCE, [], {})
    manifest = json.loads((batch / "batch.json").read_text())
    manifest["repo"].update(dirty="True", status=[" M runner/run_batch.py"])
    (batch / "batch.json").write_text(json.dumps(manifest))
    _, problems = verify({"items": [ONCE]}, None, runs_root=tmp_path)
    assert any("repo not clean" in p for p in problems)
