"""Check that every batch and every episode of a study plan ran exactly as its arm was registered.

    python -m runner.verify_plan --plan configs/study-plan-fresh.json --baseline configs/cluster-baseline-fresh.json
    python -m runner.verify_plan ... --out results/<study>/verification.csv

Reads only what the runner recorded, never a name or a log line. A batch passes when its batch.json
matches the plan item (condition, problems, step limit, the agent's description) and every environment
record is clean and identical across the plan. An episode passes when its latest attempt ran, started
from a reset with nothing earlier present anywhere in the cluster, and the model received exactly its
arm's prompt: the system prompt ends with the arm's texts for that task type and nothing else, and every
per-turn message ends with the harness's instructions plus the countdown the arm has, or none.
notes/2026-09-27-fresh-run.md says why each check exists.
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
for _path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agents.openai_compatible import (  # noqa: E402
    BUDGET_TEXT,
    COUNTDOWN,
    DOCS,
    RESP_INSTR,
    THOUGHT_PLACEMENT,
)
from runner.problem_sets import task_type  # noqa: E402

RUNS_ROOT = REPO_ROOT / "runs"
HARNESS_PIN = "ddf7e40619689dad75eaf8f2174e263c4157ec76"
# The fixed end of the system prompt template; instructed texts, if any, follow it.
DOCS_TAIL = DOCS.rsplit("{submit_api}", 1)[1]
PER_TURN = RESP_INSTR + THOUGHT_PLACEMENT
DESCRIPTION_KEYS = ("model", "base_url", "step_budget", "budget_countdown", "escalation", "temperature", "top_p",
                    "max_tokens", "context_token_limit", "observation_token_cap", "prompt_template_sha256")


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def description_mismatches(described: dict | None, expect: dict) -> list[str]:
    """How an agent description differs from the plan's expectation; empty when it is that arm."""
    described = described or {}
    out = [f"{key}: expected {expect[key]!r}, got {described.get(key)!r}"
           for key in DESCRIPTION_KEYS if described.get(key) != expect[key]]
    got = [{k: t.get(k) for k in ("role", "file", "task")} | {"sha256": (t.get("sha256") or "")[:12]}
           for t in described.get("instructed_texts") or []]
    if got != expect["instructed_texts"]:
        out.append(f"instructed_texts: expected {expect['instructed_texts']!r}, got {got!r}")
    return out


def expected_texts(expect: dict, task: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """The texts one task type's system prompt must end with, read from the tree and hash-checked."""
    texts = []
    for t in expect["instructed_texts"]:
        if t["task"] != task:
            continue
        if t["file"] is None:
            text = BUDGET_TEXT[task].format(n=expect["step_budget"])
        else:
            text = (repo_root / t["file"]).read_text().strip()
            if t["role"] == "budget":
                text = text.replace("{n}", str(expect["step_budget"]))
        if sha12(text) != t["sha256"]:
            raise ValueError(f"{t['file'] or 'built-in budget text'} ({task}) no longer hashes to {t['sha256']}")
        texts.append(text)
    return texts


def prompt_mismatches(trajectory: dict, expect: dict, max_steps: int, repo_root: Path = REPO_ROOT) -> list[str]:
    """Did the model receive exactly its arm's prompt on every call?"""
    record = trajectory.get("agent_record") or {}
    messages, calls = record.get("messages") or [], record.get("calls") or []
    if len(messages) < 2 or messages[0].get("role") != "system":
        return ["agent_record has no system prompt"]
    task = "mitigation" if task_type(trajectory["problem_id"]) == "mitigation" else "diagnosis"
    texts = expected_texts(expect, task, repo_root)
    tail = DOCS_TAIL + ("\n" + "\n\n".join(texts) + "\n" if texts else "")
    out = []
    if not messages[0]["content"].endswith(tail):
        out.append("system prompt does not end with the arm's texts")
    per_turn = [m for m in messages[2:] if m.get("role") == "user"]
    if len(per_turn) != len(calls):
        out.append(f"{len(per_turn)} per-turn messages for {len(calls)} calls")
    if len(calls) > max_steps:
        out.append(f"{len(calls)} calls, more than max_steps {max_steps}")
    n = expect["step_budget"]
    for i, message in enumerate(per_turn):
        suffix = PER_TURN + (COUNTDOWN.format(left=n - i, n=n) if expect["budget_countdown"] else "")
        if not message["content"].endswith(suffix):
            out.append(f"per-turn message {i + 1} does not end with the arm's instructions")
            break
    if any("escalation_delivered" in c for c in calls):
        out.append("an escalation message was delivered")
    return out


def _latest(index: list[dict]) -> dict[str, dict]:
    latest = {}
    for record in index:
        latest[record["problem_id"]] = record
    return latest


def episode_mismatches(record: dict, trajectory: dict, item: dict, batch_id: str, baseline_sha: str | None,
                       repo_root: Path = REPO_ROOT) -> list[str]:
    out = []
    if record.get("status") != "ok":
        return [f"latest attempt status {record.get('status')!r}"]
    if not isinstance(record.get("reset"), dict):
        out.append("no reset recorded")
    if record.get("preexisting_objects") != []:
        out.append(f"preexisting_objects {record.get('preexisting_objects')!r}")
    if record.get("cluster_drift") != []:
        out.append(f"cluster_drift {record.get('cluster_drift')!r}")
    if baseline_sha and record.get("cluster_baseline_sha256") != baseline_sha:
        out.append("checked against a different cluster baseline")
    for key, want in (("problem_id", record["problem_id"]), ("batch_id", batch_id), ("condition", item["condition"])):
        if trajectory.get(key) != want:
            out.append(f"trajectory {key} {trajectory.get(key)!r}, expected {want!r}")
    out += [f"trajectory {m}" for m in description_mismatches(trajectory.get("agent_description"), item["expect"])]
    out += prompt_mismatches(trajectory, item["expect"], item["max_steps"], repo_root)
    return out


def find_batches(condition: str, runs_root: Path = RUNS_ROOT) -> list[Path]:
    """Batch folders whose own batch.json names this condition."""
    found = []
    for batch in sorted(runs_root.glob(f"*_{condition}")):
        manifest = batch / "batch.json"
        if manifest.exists() and json.loads(manifest.read_text())["run"]["condition"] == condition:
            found.append(batch)
    return found


def batch_mismatches(batch: Path, item: dict) -> list[str]:
    manifest = json.loads((batch / "batch.json").read_text())
    run = manifest["run"]
    out = []
    for key, want in (("condition", item["condition"]), ("agent", "openai-compatible"),
                      ("max_steps", item["max_steps"]), ("problems", item["problems"]), ("skipped", {})):
        if run.get(key) != want and not (key == "skipped" and not run.get(key)):
            out.append(f"batch.json run.{key} {run.get(key)!r}, expected {want!r}")
    out += [f"batch.json {m}" for m in description_mismatches(run.get("agent_description"), item["expect"])]
    for resume in sorted(batch.glob("resume-*.json")):
        changed = json.loads(resume.read_text()).get("changed_from_batch")
        if changed:
            out.append(f"{resume.name} resumed with a changed environment: {changed}")
    return out


def environment(batch: Path) -> dict:
    """The environment fields that must be identical across every batch of the plan."""
    m = json.loads((batch / "batch.json").read_text())
    return {"repo_commit": m["repo"]["commit"], "repo_dirty": str(m["repo"].get("dirty")),
            "repo_status": m["repo"].get("status"), "harness_commit": m["harness"]["aiopslab_commit"],
            "harness_status": m["harness"].get("status"), "kind_node_image": m["cluster"]["kind_node_image"],
            "python": m["python"].get("pip_freeze"), "pins": m.get("pins")}


def verify(plan: dict, baseline: Path | None, runs_root: Path = RUNS_ROOT, repo_root: Path = REPO_ROOT,
           only: set[str] | None = None) -> tuple[list[dict], list[str]]:
    """(one row per planned episode, plan-level problems). A row's `ok` is True only if every check passed."""
    baseline_sha = hashlib.sha256(baseline.read_bytes()).hexdigest() if baseline else None
    rows, problems, environments = [], [], {}
    for item in plan["items"]:
        if only is not None and item["condition"] not in only:
            continue
        batches = find_batches(item["condition"], runs_root)
        if len(batches) != 1:
            problems.append(f"{item['condition']}: {len(batches)} batch folders")
            rows += [{"condition": item["condition"], "batch_id": "", "problem_id": p, "ok": False,
                      "why": f"{len(batches)} batch folders"} for p in item["problems"]]
            continue
        batch = batches[0]
        environments[batch.name] = environment(batch)
        batch_problems = batch_mismatches(batch, item)
        index_path = batch / "index.jsonl"
        index = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()] \
            if index_path.exists() else []
        latest = _latest(index)
        for problem_id in item["problems"]:
            why = list(batch_problems)
            record = latest.get(problem_id)
            if record is None:
                why.append("never run")
            else:
                trajectory_path = batch / "problems" / problem_id / "trajectory.json"
                trajectory = json.loads(trajectory_path.read_text()) if trajectory_path.exists() else {}
                why += episode_mismatches(record, trajectory, item, batch.name, baseline_sha, repo_root)
            rows.append({"condition": item["condition"], "batch_id": batch.name, "problem_id": problem_id,
                         "ok": not why, "why": "; ".join(why)})
    distinct = {json.dumps(e, sort_keys=True) for e in environments.values()}
    if len(distinct) > 1:
        problems.append(f"batches ran in {len(distinct)} different environments")
    for name, env in environments.items():
        if env["repo_dirty"] != "False" or env["repo_status"] not in ([], "[]"):
            problems.append(f"{name}: repo not clean ({env['repo_status']})")
        if env["harness_commit"] != HARNESS_PIN or env["harness_status"] not in ([], "[]"):
            problems.append(f"{name}: harness not at the pin with a clean tree")
    return rows, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rows, problems = verify(json.loads(args.plan.read_text()), args.baseline)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["condition", "batch_id", "problem_id", "ok", "why"])
            writer.writeheader()
            writer.writerows(rows)
    passed = sum(r["ok"] for r in rows)
    print(json.dumps({"episodes": len(rows), "passed": passed, "failed": len(rows) - passed,
                      "plan_problems": problems}, indent=1))
    for row in rows:
        if not row["ok"]:
            print(f"FAIL {row['condition']} {row['problem_id']}: {row['why']}")
    return 0 if passed == len(rows) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
