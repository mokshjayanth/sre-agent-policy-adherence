"""The fresh run of the main study and the ladder: every batch, in order, with its arm's registered settings.

    python -m runner.study_plan --write configs/study-plan-fresh.json   (render the plan)
    python -m runner.study_plan --check configs/study-plan-fresh.json   (fail if it drifted from this file)

Why a fresh run, and what it replaces: notes/2026-09-27-fresh-run.md. The arms are the ones registered in
notes/2026-09-20-main-study-preregistration.md (main: 4 arms, 2 rounds) and
notes/2026-09-23-ladder-round1-registration.md (ladder: 3 arms, 1 round), unchanged. Only the purpose
changes, to `main2` and `ladder2`, so no fresh batch can pool with an earlier one by name.

Each arm carries the instructed texts, with the SHA-256 prefixes, that the earlier batches of that arm
recorded in their batch.json. They are copied here by hand from those records, not computed from the
policy files, so they are an independent check: a batch whose agent describes different texts is not
that arm, and runner/run_plan.py refuses to start it.
"""

import argparse
import json
import sys
from pathlib import Path

MODELS = (  # (AGENT_MODEL, label): the main study's six, as study/main_study.sh ran them
    ("mistral.ministral-3-3b-instruct", "ministral3-3b"),
    ("mistral.ministral-3-8b-instruct", "ministral3-8b"),
    ("mistral.ministral-3-14b-instruct", "ministral3-14b"),
    ("mistral.mistral-large-3-675b-instruct", "mistral-large3"),
    ("qwen.qwen3-next-80b-a3b-instruct", "qwen3-next-80b"),
    ("openai.gpt-oss-120b", "gpt-oss-120b"),
)
MITIGATION = (
    "k8s_target_port-misconfig-mitigation-2", "k8s_target_port-misconfig-mitigation-3",
    "auth_miss_mongodb-mitigation-1", "revoke_auth_mongodb-mitigation-1", "revoke_auth_mongodb-mitigation-2",
    "user_unregistered_mongodb-mitigation-1", "user_unregistered_mongodb-mitigation-2",
    "wrong_bin_usage-mitigation-1",
)
LOCALIZATION = (
    "k8s_target_port-misconfig-localization-2", "k8s_target_port-misconfig-localization-3",
    "auth_miss_mongodb-localization-1", "revoke_auth_mongodb-localization-1",
    "revoke_auth_mongodb-localization-2", "user_unregistered_mongodb-localization-1",
    "user_unregistered_mongodb-localization-2", "wrong_bin_usage-localization-1",
)
# The agent's fixed settings, as every earlier condition recorded them.
AGENT_SETTINGS = {"base_url": "https://bedrock-mantle.ap-south-1.api.aws/v1", "temperature": 0.5, "top_p": 0.95,
                  "max_tokens": 1024, "context_token_limit": 64000, "observation_token_cap": 16000,
                  "prompt_template_sha256": "04dd22bef1bd"}
# Every variable the agent reads for a condition; each batch unsets all of them before setting its own.
AGENT_VARIABLES = ("AGENT_POLICY_FILE", "AGENT_PRESSURE_FILE", "AGENT_STEP_BUDGET", "AGENT_BUDGET_FILE",
                   "AGENT_BUDGET_COUNTDOWN", "AGENT_ESCALATION_FILE", "AGENT_ESCALATION_TURNS")

POLICY = ("policy", [("policy/draft-v3-mitigation.txt", "mitigation", "d4d898ad8625"),
                     ("policy/draft-v3-diagnosis.txt", "diagnosis", "57356491965c")])

# arm -> (study, env, {task: max_steps}, registered texts as (role, file, task, sha256) in prompt order,
#         countdown). The key "" means one batch with both task types.
ARMS = {
    "nopolicy": ("main", {}, {"": 30}, {"": []}, False),
    "policy": ("main", {"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt"}, {"": 30},
               {"": [("policy", f, t, h) for f, t, h in POLICY[1]]}, False),
    # The built-in budget sentence (agents/openai_compatible.py BUDGET_TEXT), counted down every turn.
    "budget": ("main", {"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt", "AGENT_STEP_BUDGET": "15"},
               {"": 15},
               {"": [("budget", None, "mitigation", "983915b27a32"), ("budget", None, "diagnosis", "e725d591b074"),
                     *[("policy", f, t, h) for f, t, h in POLICY[1]]]}, True),
    "scored": ("main", {"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt",
                        "AGENT_PRESSURE_FILE": "policy/draft-pressure-scored-v1-{task}.txt"}, {"": 30},
               {"": [("pressure", "policy/draft-pressure-scored-v1-mitigation.txt", "mitigation", "afd8ad3b39fe"),
                     ("pressure", "policy/draft-pressure-scored-v1-diagnosis.txt", "diagnosis", "cfa0952aae04"),
                     *[("policy", f, t, h) for f, t, h in POLICY[1]]]}, False),
}
# The ladder states its budget in its own words (policy/draft-pressure-budget-{task}.txt) at the median
# caps, 24 for mitigation and 7 for diagnosis. The hash is of the text with {n} rendered, so it differs
# by cap: describe() lists both task types' texts at the batch's cap.
LADDER_BUDGET = {
    24: [("budget", "policy/draft-pressure-budget-mitigation.txt", "mitigation", "f38783bad03e"),
         ("budget", "policy/draft-pressure-budget-diagnosis.txt", "diagnosis", "5c7ebf59e049")],
    7: [("budget", "policy/draft-pressure-budget-mitigation.txt", "mitigation", "16e1339671c0"),
        ("budget", "policy/draft-pressure-budget-diagnosis.txt", "diagnosis", "33e3d9bf7c58")],
}
LADDER_SCORED = [("pressure", "policy/draft-pressure-scored-mitigation.txt", "mitigation", "ff25ea7becdd"),
                 ("pressure", "policy/draft-pressure-scored-diagnosis.txt", "diagnosis", "278ef7fb7f19")]
LADDER_CAPS = {"mitigation": 24, "diagnosis": 7}
LADDER_ENV = {"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt",
              "AGENT_BUDGET_FILE": "policy/draft-pressure-budget-{task}.txt"}
for _arm, _countdown, _extra_env, _extra_texts in (
        ("budgetonce", False, {"AGENT_BUDGET_COUNTDOWN": "0"}, []),
        ("budgetmedian", True, {"AGENT_BUDGET_COUNTDOWN": "1"}, []),
        ("combined", True, {"AGENT_BUDGET_COUNTDOWN": "1",
                            "AGENT_PRESSURE_FILE": "policy/draft-pressure-scored-{task}.txt"}, LADDER_SCORED)):
    ARMS[_arm] = ("ladder", {**LADDER_ENV, **_extra_env}, dict(LADDER_CAPS),
                  {task: [*LADDER_BUDGET[cap], *_extra_texts, *[("policy", f, t, h) for f, t, h in POLICY[1]]]
                   for task, cap in LADDER_CAPS.items()}, _countdown)

# Order, as registered: main round 1 per model in this arm order, round 2 reversed (study/main_study.sh);
# then the ladder, arm by arm, each model's mitigation batch before its diagnosis batch
# (study/round1_pending.sh).
MAIN_ORDER = ("nopolicy", "policy", "budget", "scored")
LADDER_ORDER = ("budgetmedian", "combined", "budgetonce")
PURPOSE = {"main": "main2", "ladder": "ladder2"}


def _batch(study: str, arm: str, model: str, label: str, task: str, round_: int) -> dict:
    _, env, steps, texts, countdown = ARMS[arm]
    max_steps = steps[task]
    problems = {"": [*MITIGATION, *LOCALIZATION], "mitigation": list(MITIGATION),
                "diagnosis": list(LOCALIZATION)}[task]
    condition = "-".join(p for p in (PURPOSE[study], label, arm, task, f"r{round_}" if round_ > 1 else "") if p)
    budget = env.get("AGENT_STEP_BUDGET") or (str(max_steps) if "AGENT_BUDGET_FILE" in env else None)
    full_env = {**env, **({"AGENT_STEP_BUDGET": budget} if budget else {})}
    return {
        "condition": condition, "study": study, "arm": arm, "task": task or "both", "round": round_,
        "model": model, "label": label, "max_steps": max_steps, "problems": problems,
        "env": dict(sorted(full_env.items())),
        "expect": {
            "model": model,
            "instructed_texts": [{"role": r, "file": f, "task": t, "sha256": h} for r, f, t, h in texts[task]],
            "step_budget": int(budget) if budget else None,
            "budget_countdown": countdown,
            "escalation": [],
            **AGENT_SETTINGS,
        },
    }


def expand() -> list[dict]:
    """Every batch of the fresh run, in the order it runs."""
    batches = []
    for round_, order in ((1, MAIN_ORDER), (2, tuple(reversed(MAIN_ORDER)))):
        for model, label in MODELS:
            batches += [_batch("main", arm, model, label, "", round_) for arm in order]
    for arm in LADDER_ORDER:
        for model, label in MODELS:
            batches += [_batch("ladder", arm, model, label, task, 1) for task in ("mitigation", "diagnosis")]
    return batches


def render() -> str:
    batches = expand()
    return json.dumps({"plan": "fresh run of the main study and the ladder",
                       "note": "notes/2026-09-27-fresh-run.md",
                       "batches": len(batches), "episodes": sum(len(b["problems"]) for b in batches),
                       "items": batches}, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    if args.write:
        args.write.write_text(render())
        return 0
    if args.check.read_text() != render():
        print(f"{args.check} differs from runner/study_plan.py; re-render it and review the diff", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
