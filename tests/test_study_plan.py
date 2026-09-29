"""The fresh run's plan: its stages, its coverage, and that every arm is the one registered."""

import collections
import csv
import json
import shutil
from pathlib import Path

import pytest

from agents import openai_compatible
from runner import study_plan
from runner.run_batch import CONDITION_PATTERN
from runner.verify_plan import description_mismatches, expected_texts, sha12

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTERED_CAPS = {"mitigation": 24, "diagnosis": 7}
STAGE1 = study_plan.expand(1)
STAGE2 = study_plan.expand(2, REGISTERED_CAPS)
PLAN = STAGE1 + STAGE2


def test_stage_1_is_the_baseline_arms_in_both_rounds():
    assert len(STAGE1) == 24 and sum(len(b["problems"]) for b in STAGE1) == 384
    assert collections.Counter((b["arm"], b["round"]) for b in STAGE1) == {
        (arm, r): 6 for arm in ("nopolicy", "policy") for r in (1, 2)}
    assert [(b["round"], b["label"], b["arm"]) for b in STAGE1[:2]] == [
        (1, "ministral3-3b", "nopolicy"), (1, "ministral3-3b", "policy")]
    assert [(b["round"], b["label"], b["arm"]) for b in STAGE1[12:14]] == [
        (2, "ministral3-3b", "policy"), (2, "ministral3-3b", "nopolicy")]


def test_stage_2_is_the_pressure_arms_then_the_ladder():
    assert len(STAGE2) == 60 and sum(len(b["problems"]) for b in STAGE2) == 672
    assert [b["study"] for b in STAGE2] == ["main"] * 24 + ["ladder"] * 36
    assert [b["arm"] for b in STAGE2[:2]] == ["budget", "scored"]
    assert [b["arm"] for b in STAGE2[12:14]] == ["scored", "budget"]
    assert [(b["arm"], b["task"]) for b in STAGE2[24:26]] == [("budgetmedian", "mitigation"),
                                                              ("budgetmedian", "diagnosis")]


def test_both_stages_together_are_the_registered_design_each_episode_once():
    assert sum(len(b["problems"]) for b in PLAN) == 1056
    cells = collections.Counter((b["study"], b["arm"], b["round"]) for b in PLAN)
    assert {k: v for k, v in cells.items() if k[0] == "main"} == {
        ("main", arm, r): 6 for arm in ("nopolicy", "policy", "budget", "scored") for r in (1, 2)}
    assert {k: v for k, v in cells.items() if k[0] == "ladder"} == {
        ("ladder", arm, 1): 12 for arm in study_plan.LADDER_ORDER}
    episodes = collections.Counter((b["study"], b["label"], b["arm"], b["round"], p) for b in PLAN for p in b["problems"])
    assert set(episodes.values()) == {1}
    assert len({b["condition"] for b in PLAN}) == len(PLAN)


def test_conditions_are_valid_and_never_an_earlier_study():
    for b in PLAN:
        assert CONDITION_PATTERN.fullmatch(b["condition"])
        assert b["condition"].split("-")[0] in ("main6", "ladder6")


def test_the_ladder_takes_its_caps_from_the_caps_it_is_given():
    stage2 = study_plan.expand(2, {"mitigation": 22, "diagnosis": 9})
    ladder = {(b["arm"], b["task"]): b for b in stage2 if b["study"] == "ladder"}
    assert ladder[("combined", "mitigation")]["max_steps"] == 22
    assert ladder[("budgetonce", "diagnosis")]["env"]["AGENT_STEP_BUDGET"] == "9"
    assert ladder[("budgetonce", "diagnosis")]["expect"]["step_budget"] == 9
    main = [b for b in stage2 if b["study"] == "main"]
    assert main == STAGE2[:24]                      # the main arms don't depend on the caps


def test_step_limits_match_the_budget_the_agent_states():
    for b in PLAN:
        budget = b["expect"]["step_budget"]
        assert budget is None or budget == b["max_steps"]
        assert (b["env"].get("AGENT_STEP_BUDGET") or None) == (str(budget) if budget else None)
    steps = {(b["arm"], b["task"]): b["max_steps"] for b in PLAN}
    assert steps[("budget", "both")] == 15 and steps[("policy", "both")] == 30


def test_ladder_batches_hold_only_their_task_type():
    for b in PLAN:
        if b["task"] == "mitigation":
            assert all("-mitigation-" in p for p in b["problems"])
        elif b["task"] == "diagnosis":
            assert all("-localization-" in p for p in b["problems"])


@pytest.mark.parametrize("item", PLAN, ids=lambda b: b["condition"])
def test_texts_on_disk_still_hash_to_the_registered_values(item):
    for task in ("mitigation", "diagnosis"):
        texts = expected_texts(item["expect"], task, REPO_ROOT)   # raises on a hash mismatch
        assert len(texts) == sum(1 for t in item["expect"]["instructed_texts"] if t["task"] == task)


def test_an_edited_ladder_budget_file_fails_even_at_a_new_cap(tmp_path):
    shutil.copytree(REPO_ROOT / "policy", tmp_path / "policy")
    edited = tmp_path / study_plan.LADDER_BUDGET_FILES["mitigation"]
    edited.write_text(edited.read_text() + " Hurry.")
    with pytest.raises(ValueError, match="not the text"):
        study_plan.ladder_budget_texts(22, repo_root=tmp_path)


def test_the_agent_describes_each_arm_as_the_plan_expects(monkeypatch):
    """describe() without the endpoint: the plan's env must produce the plan's expectation."""
    monkeypatch.setenv("OPENAI_BASE_URL", study_plan.AGENT_SETTINGS["base_url"])
    monkeypatch.setattr(openai_compatible, "serving_details", lambda *a: {})
    for item in PLAN + study_plan.expand(2, {"mitigation": 21, "diagnosis": 8}):
        for variable in (*study_plan.AGENT_VARIABLES, "AGENT_MODEL"):
            monkeypatch.delenv(variable, raising=False)
        for key, value in {**item["env"], "AGENT_MODEL": item["model"]}.items():
            monkeypatch.setenv(key, value)
        described = openai_compatible.OpenAICompatibleAgent.describe()
        assert description_mismatches(described, item["expect"]) == [], item["condition"]


def test_the_cap_rule_rounds_to_nearest_with_ties_down():
    assert [study_plan.round_half_down(v) for v in (24.5, 24.6, 24.4, 7.0, 7.5)] == [24, 25, 24, 7, 7]


def test_the_cap_rule_reproduces_the_registered_24_and_7():
    """On the retired baseline table the rule gives the numbers notes/2026-09-23-baseline-replication.md
    registered, so the code is that rule."""
    table = REPO_ROOT / "results" / "main-2026-09-23" / "episodes.csv"
    rows = [{**r, "steps": int(r["steps"]), "success": r["success"] == "True", "used": r["used"] == "True"}
            for r in csv.DictReader(table.open()) if r["variant"] == "policy"]
    derived = study_plan.caps_from(rows)
    assert derived["successes"] == {"mitigation": 10, "diagnosis": 70}
    assert derived["medians"] == {"mitigation": 24.5, "diagnosis": 7.0}
    assert derived["caps"] == REGISTERED_CAPS


def test_caps_are_not_derived_from_a_stage_1_that_does_not_verify(tmp_path):
    stage1 = json.loads(study_plan.render(1))
    with pytest.raises(ValueError, match="does not verify"):
        study_plan.derive_caps(stage1, None, runs_root=tmp_path)


def test_committed_stage_1_plan_matches_the_renderer():
    committed = REPO_ROOT / "configs" / "study-plan-fresh-stage1.json"
    assert committed.read_text() == study_plan.render(1)
    assert json.loads(committed.read_text())["episodes"] == 384


def test_sha12_is_the_agents_hash():
    assert sha12("x") == openai_compatible._entry("policy", None, "x", None)["sha256"]


def test_stage_2a_and_2b_are_stage_2_split_where_the_caps_are_first_needed(monkeypatch):
    caps = {"mitigation": 22, "diagnosis": 9}
    def no_caps_file():
        raise AssertionError("stage 2a must not read the caps")
    monkeypatch.setattr(study_plan, "load_caps", no_caps_file)
    first, second = study_plan.expand("2a"), study_plan.expand("2b", caps)
    assert first + second == study_plan.expand(2, caps)
    assert {i["arm"] for i in first} == {"budget", "scored"} and all(i["condition"].startswith("main") for i in first)
    assert all(i["condition"].startswith("ladder") for i in second)
    assert len(first) == 24 and len(second) == 36
    assert json.loads(study_plan.render("2a"))["stage"] == "2a"
