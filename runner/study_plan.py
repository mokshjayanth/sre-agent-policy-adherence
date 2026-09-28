"""The fresh run of the main study and the ladder: every batch, in order, with its arm's registered settings.

It runs in two stages, each its own plan file (notes/2026-09-27-fresh-run.md, Correction):

    stage 1   main4 no-policy and policy arms, both rounds (24 batches, 384 episodes). A checkpoint.
    stage 2   main4 budget and scored arms, both rounds, and the ladder at caps derived from stage 1's
              policy arm (60 batches, 672 episodes).

    python -m runner.study_plan --stage 1 --write configs/study-plan-fresh-stage1.json
    python -m runner.study_plan --derive-caps configs/study-plan-fresh-stage1.json \\
        --baseline configs/cluster-baseline-fresh.json --write configs/ladder-caps-fresh.json
    python -m runner.study_plan --stage 2 --write configs/study-plan-fresh-stage2.json
    python -m runner.study_plan --stage N --check <plan file>      (fail if it drifted from this file)

The arms are the ones registered in notes/2026-09-20-main-study-preregistration.md (main: 4 arms,
2 rounds) and notes/2026-09-23-ladder-round1-registration.md (ladder: 3 arms, 1 round). The purpose
is `main4` and `ladder4`, so no fresh batch can pool with an earlier one by name (`main2`/`ladder2` and
`main3`/`ladder3` were earlier attempts, retired).

Each arm carries the instructed texts, with the SHA-256 prefixes, that the earlier batches of that arm
recorded in their batch.json. They are copied here by hand from those records, not computed from the
policy files, so they are an independent check: a batch whose agent describes different texts is not
that arm, and runner/run_plan.py refuses to start it. The ladder's budget text is rendered with its cap,
so at a re-derived cap its hash is new; the file is first proven unchanged by rendering it at the caps
the earlier batches recorded (24 and 7) and matching their hashes.
"""

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPS_FILE = REPO_ROOT / "configs" / "ladder-caps-fresh.json"

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

POLICY = [("policy", "policy/draft-v3-mitigation.txt", "mitigation", "d4d898ad8625"),
          ("policy", "policy/draft-v3-diagnosis.txt", "diagnosis", "57356491965c")]
MAIN_SCORED = [("pressure", "policy/draft-pressure-scored-v1-mitigation.txt", "mitigation", "afd8ad3b39fe"),
               ("pressure", "policy/draft-pressure-scored-v1-diagnosis.txt", "diagnosis", "cfa0952aae04")]
# The built-in budget sentence (agents/openai_compatible.py BUDGET_TEXT) at 15, counted down every turn.
MAIN_BUDGET = [("budget", None, "mitigation", "983915b27a32"), ("budget", None, "diagnosis", "e725d591b074")]
LADDER_SCORED = [("pressure", "policy/draft-pressure-scored-mitigation.txt", "mitigation", "ff25ea7becdd"),
                 ("pressure", "policy/draft-pressure-scored-diagnosis.txt", "diagnosis", "278ef7fb7f19")]
# The ladder's own budget text, as the earlier ladder batches recorded it at each cap: {n} rendered.
LADDER_BUDGET_FILES = {"mitigation": "policy/draft-pressure-budget-mitigation.txt",
                       "diagnosis": "policy/draft-pressure-budget-diagnosis.txt"}
LADDER_BUDGET_RECORDED = {24: {"mitigation": "f38783bad03e", "diagnosis": "5c7ebf59e049"},
                          7: {"mitigation": "16e1339671c0", "diagnosis": "33e3d9bf7c58"}}

# arm -> (study, env, registered texts as (role, file, task, sha256) in prompt order, countdown, main steps)
MAIN_ARMS = {
    "nopolicy": ({}, [], False, 30),
    "policy": ({"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt"}, POLICY, False, 30),
    "budget": ({"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt", "AGENT_STEP_BUDGET": "15"},
               [*MAIN_BUDGET, *POLICY], True, 15),
    "scored": ({"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt",
                "AGENT_PRESSURE_FILE": "policy/draft-pressure-scored-v1-{task}.txt"}, [*MAIN_SCORED, *POLICY], False, 30),
}
LADDER_ENV = {"AGENT_POLICY_FILE": "policy/draft-v3-{task}.txt",
              "AGENT_BUDGET_FILE": "policy/draft-pressure-budget-{task}.txt"}
# arm -> (extra env, extra texts after the budget, countdown)
LADDER_ARMS = {
    "budgetonce": ({"AGENT_BUDGET_COUNTDOWN": "0"}, [], False),
    "budgetmedian": ({"AGENT_BUDGET_COUNTDOWN": "1"}, [], True),
    "combined": ({"AGENT_BUDGET_COUNTDOWN": "1", "AGENT_PRESSURE_FILE": "policy/draft-pressure-scored-{task}.txt"},
                 LADDER_SCORED, True),
}

# Order, as registered, within each stage: main round 1 per model in the arm order, round 2 reversed
# (study/main_study.sh); the ladder arm by arm, each model's mitigation batch before its diagnosis batch
# (study/round1_pending.sh).
STAGE_MAIN_ARMS = {1: ("nopolicy", "policy"), 2: ("budget", "scored")}
LADDER_ORDER = ("budgetmedian", "combined", "budgetonce")
# main2/ladder2 and main3/ladder3 were stage 1's first two attempts, retired
# (notes/2026-09-28-control-plane-persistence.md).
PURPOSE = {"main": "main4", "ladder": "ladder4"}
# The registered cap rule (notes/2026-09-23-baseline-replication.md, Finding 5): the median number of
# actions a successful policy-arm episode took, per task type, pooled over both rounds; nearest integer,
# a tie rounds down.
CAP_RULE = ("median actions of a successful policy-arm episode, per task type, pooled over both rounds; "
            "nearest integer, a tie rounds down")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def ladder_budget_texts(cap: int, repo_root: Path = REPO_ROOT) -> list[tuple]:
    """The ladder budget texts as describe() lists them at this cap: both task types, {n} rendered.

    Raises unless each file still renders to the hashes the earlier batches recorded at 24 and 7.
    """
    texts = []
    for task, name in LADDER_BUDGET_FILES.items():
        raw = (repo_root / name).read_text().strip()
        for recorded_cap, hashes in LADDER_BUDGET_RECORDED.items():
            if _sha12(raw.replace("{n}", str(recorded_cap))) != hashes[task]:
                raise ValueError(f"{name} is not the text the earlier ladder batches recorded")
        texts.append(("budget", name, task, _sha12(raw.replace("{n}", str(cap)))))
    return texts


def _item(study: str, arm: str, model: str, label: str, task: str, round_: int, env: dict, texts: list,
          countdown: bool, max_steps: int, budget: int | None) -> dict:
    problems = {"": [*MITIGATION, *LOCALIZATION], "mitigation": list(MITIGATION),
                "diagnosis": list(LOCALIZATION)}[task]
    condition = "-".join(p for p in (PURPOSE[study], label, arm, task, f"r{round_}" if round_ > 1 else "") if p)
    return {
        "condition": condition, "study": study, "arm": arm, "task": task or "both", "round": round_,
        "model": model, "label": label, "max_steps": max_steps, "problems": problems,
        "env": dict(sorted(env.items())),
        "expect": {
            "model": model,
            "instructed_texts": [{"role": r, "file": f, "task": t, "sha256": h} for r, f, t, h in texts],
            "step_budget": budget,
            "budget_countdown": countdown,
            "escalation": [],
            **AGENT_SETTINGS,
        },
    }


def _main(arm: str, model: str, label: str, round_: int) -> dict:
    env, texts, countdown, steps = MAIN_ARMS[arm]
    budget = int(env["AGENT_STEP_BUDGET"]) if "AGENT_STEP_BUDGET" in env else None
    return _item("main", arm, model, label, "", round_, env, texts, countdown, steps, budget)


def _ladder(arm: str, model: str, label: str, task: str, caps: dict) -> dict:
    extra_env, extra_texts, countdown = LADDER_ARMS[arm]
    cap = caps[task]
    env = {**LADDER_ENV, **extra_env, "AGENT_STEP_BUDGET": str(cap)}
    texts = [*ladder_budget_texts(cap), *extra_texts, *POLICY]
    return _item("ladder", arm, model, label, task, 1, env, texts, countdown, cap, cap)


def load_caps(path: Path = CAPS_FILE) -> dict:
    data = json.loads(path.read_text())
    return {"mitigation": int(data["caps"]["mitigation"]), "diagnosis": int(data["caps"]["diagnosis"])}


def expand(stage: int, caps: dict | None = None) -> list[dict]:
    """Every batch of one stage, in the order it runs. Stage 2 needs the derived caps."""
    batches = []
    arms = STAGE_MAIN_ARMS[stage]
    for round_, order in ((1, arms), (2, tuple(reversed(arms)))):
        for model, label in MODELS:
            batches += [_main(arm, model, label, round_) for arm in order]
    if stage == 2:
        caps = caps or load_caps()
        for arm in LADDER_ORDER:
            for model, label in MODELS:
                batches += [_ladder(arm, model, label, task, caps) for task in ("mitigation", "diagnosis")]
    return batches


def render(stage: int, caps: dict | None = None) -> str:
    batches = expand(stage, caps)
    return json.dumps({"plan": f"fresh run of the main study and the ladder, stage {stage}",
                       "note": "notes/2026-09-27-fresh-run.md", "stage": stage,
                       "batches": len(batches), "episodes": sum(len(b["problems"]) for b in batches),
                       "items": batches}, indent=1) + "\n"


def round_half_down(value: float) -> int:
    """Nearest integer, a tie rounding down: 24.5 -> 24, 24.6 -> 25, 7.0 -> 7."""
    return math.ceil(value - 0.5)


def derive_caps(stage1: dict, baseline: Path | None, runs_root: Path | None = None) -> dict:
    """The ladder's caps from stage 1's policy arm, under the registered rule.

    Only a stage 1 that runner/verify_plan.py passes in full is used, and only the attempts it certified
    (the latest, which grading/report.py also uses).
    """
    from grading.report import collect, choose_attempts
    from runner.verify_plan import RUNS_ROOT, find_batches, verify

    runs_root = runs_root or RUNS_ROOT
    rows, problems = verify(stage1, baseline, runs_root=runs_root)
    if problems or not all(r["ok"] for r in rows):
        raise ValueError(f"stage 1 does not verify: {len(rows) - sum(r['ok'] for r in rows)} episodes fail, "
                         f"plan problems {problems}")
    policy = [b for item in stage1["items"] if item["arm"] == "policy" for b in find_batches(item["condition"], runs_root)]
    if len(policy) != sum(item["arm"] == "policy" for item in stage1["items"]):
        raise ValueError("not every policy-arm batch of stage 1 has exactly one folder")
    episodes, cells = collect(policy)
    choose_attempts(episodes, cells)
    return {"source": "notes/2026-09-23-baseline-replication.md", "batches": sorted(b.name for b in policy),
            **caps_from(episodes)}


def caps_from(episodes: list[dict]) -> dict:
    """The registered rule over grading/report.py episode rows (with `used` marked)."""
    steps = {task: sorted(e["steps"] for e in episodes if e["used"] and e["success"] and e["task"] == task)
             for task in ("mitigation", "diagnosis")}
    if not all(steps.values()):
        raise ValueError(f"no successful policy-arm episode for {[t for t, s in steps.items() if not s]}")
    medians = {task: statistics.median(s) for task, s in steps.items()}
    return {"rule": CAP_RULE, "successes": {t: len(s) for t, s in steps.items()}, "steps": steps,
            "medians": medians, "caps": {t: round_half_down(m) for t, m in medians.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", type=int, choices=(1, 2))
    parser.add_argument("--derive-caps", type=Path, metavar="STAGE1_PLAN")
    parser.add_argument("--baseline", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    if args.derive_caps:
        text = json.dumps(derive_caps(json.loads(args.derive_caps.read_text()), args.baseline), indent=1) + "\n"
    elif args.stage:
        text = render(args.stage)
    else:
        parser.error("give --stage or --derive-caps")
    if args.write:
        args.write.write_text(text)
        return 0
    if args.check.read_text() != text:
        print(f"{args.check} differs from runner/study_plan.py; re-render it and review the diff", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
