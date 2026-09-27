"""The fresh run's plan: its size, its coverage, and that every arm is the one registered."""

import collections
import json
from pathlib import Path

import pytest

from agents import openai_compatible
from runner import study_plan
from runner.run_batch import CONDITION_PATTERN
from runner.verify_plan import expected_texts, sha12

REPO_ROOT = Path(__file__).resolve().parents[1]
PLAN = study_plan.expand()


def test_the_plan_is_the_registered_design():
    assert len(PLAN) == 84
    assert sum(len(b["problems"]) for b in PLAN) == 1056
    cells = collections.Counter((b["study"], b["arm"], b["round"]) for b in PLAN)
    # main: 4 arms x 6 models x 2 rounds; ladder: 3 arms x 6 models x 2 task batches, 1 round
    assert {k: v for k, v in cells.items() if k[0] == "main"} == {
        ("main", arm, r): 6 for arm in study_plan.MAIN_ORDER for r in (1, 2)}
    assert {k: v for k, v in cells.items() if k[0] == "ladder"} == {
        ("ladder", arm, 1): 12 for arm in study_plan.LADDER_ORDER}


def test_every_episode_is_planned_exactly_once():
    episodes = collections.Counter((b["study"], b["label"], b["arm"], b["round"], p) for b in PLAN for p in b["problems"])
    assert set(episodes.values()) == {1}
    assert len({b["condition"] for b in PLAN}) == len(PLAN)


def test_conditions_are_valid_and_never_an_earlier_study():
    for b in PLAN:
        assert CONDITION_PATTERN.fullmatch(b["condition"])
        assert b["condition"].split("-")[0] in ("main2", "ladder2")


def test_order_is_round_1_then_round_2_reversed_then_the_ladder():
    main = [(b["round"], b["label"], b["arm"]) for b in PLAN if b["study"] == "main"]
    assert main[:4] == [(1, "ministral3-3b", a) for a in ("nopolicy", "policy", "budget", "scored")]
    assert main[24:28] == [(2, "ministral3-3b", a) for a in ("scored", "budget", "policy", "nopolicy")]
    assert [b["study"] for b in PLAN] == ["main"] * 48 + ["ladder"] * 36
    assert [(b["arm"], b["task"]) for b in PLAN[48:50]] == [("budgetmedian", "mitigation"), ("budgetmedian", "diagnosis")]


def test_step_limits_match_the_budget_the_agent_states():
    for b in PLAN:
        budget = b["expect"]["step_budget"]
        assert budget is None or budget == b["max_steps"]
        assert (b["env"].get("AGENT_STEP_BUDGET") or None) == (str(budget) if budget else None)
    steps = {(b["arm"], b["task"]): b["max_steps"] for b in PLAN}
    assert steps[("budget", "both")] == 15 and steps[("policy", "both")] == 30
    assert steps[("combined", "mitigation")] == 24 and steps[("combined", "diagnosis")] == 7


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


def test_the_agent_describes_each_arm_as_the_plan_expects(monkeypatch):
    """describe() without the endpoint: the plan's env must produce the plan's expectation."""
    monkeypatch.setenv("OPENAI_BASE_URL", study_plan.AGENT_SETTINGS["base_url"])
    monkeypatch.setattr(openai_compatible, "serving_details", lambda *a: {})
    for item in PLAN:
        for variable in (*study_plan.AGENT_VARIABLES, "AGENT_MODEL"):
            monkeypatch.delenv(variable, raising=False)
        for key, value in {**item["env"], "AGENT_MODEL": item["model"]}.items():
            monkeypatch.setenv(key, value)
        described = openai_compatible.OpenAICompatibleAgent.describe()
        from runner.verify_plan import description_mismatches
        assert description_mismatches(described, item["expect"]) == [], item["condition"]


def test_committed_plan_file_matches_the_renderer():
    committed = REPO_ROOT / "configs" / "study-plan-fresh.json"
    assert committed.read_text() == study_plan.render()
    assert json.loads(committed.read_text())["episodes"] == 1056


def test_sha12_is_the_agents_hash():
    assert sha12("x") == openai_compatible._entry("policy", None, "x", None)["sha256"]
