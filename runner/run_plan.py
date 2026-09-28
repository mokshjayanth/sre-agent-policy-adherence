"""Run a study plan batch by batch, and refuse any batch that is not exactly its registered arm.

    python -m runner.run_plan --plan configs/study-plan-fresh-stage1.json --baseline configs/cluster-baseline-fresh.json --dry-run
    python -m runner.run_plan --plan configs/study-plan-fresh-stage1.json --baseline configs/cluster-baseline-fresh.json

The plan (runner/study_plan.py, one JSON file per stage, committed) is the only source of what runs.
Before anything runs: the plan file must equal its renderer's output, the repo and the harness must be
committed and clean at the pin, the cluster baseline must exist, and no other copy may be running.

Per batch, in plan order:
1. Gate. With exactly the plan item's variables set (every other AGENT_* variable removed), the agent
   describes itself; any difference from the item's expectation -- model, texts and their hashes, budget,
   countdown, escalation, sampling -- stops the whole run before the batch exists.
2. Run. A new batch through runner/run_batch.py, or a resume of the one batch that already carries the
   condition. More than one such batch stops the run.
3. Verify. runner/verify_plan.py on the batch. A configuration or prompt difference, an episode that
   was refused for starting next to earlier objects or a changed cluster, a run_batch that exited
   without running any episode, or a reset that keeps timing out stops the run: those need a person.
   Episodes that ended in a runner or harness error are resumed, up to --attempts in all.
An end pass resumes anything still incomplete, then the whole plan is verified. Only runner/run_batch.py
creates run folders (CLAUDE.md). Why: notes/2026-09-27-fresh-run.md.
"""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
for _path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from runner.harness_fixes import BASELINE_VARIABLE, check_free_disk  # noqa: E402
from runner.study_plan import AGENT_VARIABLES, render  # noqa: E402
from runner.verify_plan import HARNESS_PIN, description_mismatches, find_batches, verify  # noqa: E402

LOCK = Path.home() / ".run_plan.lock"
# Index errors that mean the cluster itself is not clean; resuming would only repeat them.
UNCLEAN = ("episode would start next to earlier objects", "cluster differs from its baseline", "low disk")
# A reset that timed out (a namespace slow to terminate) is resumable: the next attempt waits again. This
# many in one batch within one run means it is not going away.
RESET_FAILURE = "reset_app_state"
RESET_FAILURES_BEFORE_STOP = 3
DESCRIBE = ("import json, sys; sys.path[:0] = [{aiopslab!r}, {repo!r}]; "
            "from agents.openai_compatible import OpenAICompatibleAgent as A; print(json.dumps(A.describe()))")


class Stop(Exception):
    """Something only a person should decide; the run ends here."""


def log(message: str) -> None:
    print(f"== {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ} {message}", flush=True)


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def preconditions(plan_path: Path, baseline: Path) -> list[str]:
    """Everything that must hold before the first batch; empty when all do."""
    failed = []
    try:
        rendered = render(json.loads(plan_path.read_text())["stage"])
    except (OSError, KeyError, ValueError) as exc:
        rendered = f"cannot render: {exc}"
    if plan_path.read_text() != rendered:
        failed.append(f"{plan_path} differs from runner/study_plan.py's rendering ({rendered[:80]})")
    if _git("status", "--porcelain"):
        failed.append("the repo has uncommitted or untracked changes")
    submodules = _git("submodule", "status", "--recursive")
    if any(line[:1] in "+-U" for line in submodules.splitlines()):
        failed.append("a submodule has moved or is missing")
    if HARNESS_PIN not in submodules or _git("status", "--short", cwd=AIOPSLAB_ROOT):
        failed.append("the harness is not at the pin with a clean tree")
    if not baseline.exists():
        failed.append(f"no cluster baseline at {baseline}")
    elif _git("ls-files", str(baseline.resolve().relative_to(REPO_ROOT))) == "":
        failed.append(f"{baseline} is not committed")
    for variable in ("OPENAI_BASE_URL", "OPENAI_API_KEY"):
        if not os.environ.get(variable):
            failed.append(f"{variable} is not set")
    return failed


def batch_env(item: dict, baseline: Path) -> dict:
    """The process environment for one batch: the plan item's variables and nothing left from another."""
    env = {k: v for k, v in os.environ.items() if k not in AGENT_VARIABLES and k != "AGENT_MODEL"}
    env.update(item["env"])
    env["AGENT_MODEL"] = item["model"]
    env[BASELINE_VARIABLE] = str(baseline.resolve())
    return env


def describe(env: dict, tries: int = 5, wait_s: int = 60) -> dict:
    """The agent's description under env, as run_batch will record it. Retries a failing endpoint."""
    code = DESCRIBE.format(aiopslab=str(AIOPSLAB_ROOT), repo=str(REPO_ROOT))
    for attempt in range(1, tries + 1):
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout.strip().splitlines()[-1])
        log(f"describe failed ({attempt}/{tries}): {result.stderr.strip()[-200:]}")
        if attempt < tries:
            time.sleep(wait_s)
    raise Stop("the agent could not describe itself; the endpoint may be down")


def gate(item: dict, baseline: Path) -> None:
    mismatches = description_mismatches(describe(batch_env(item, baseline)), item["expect"])
    if mismatches:
        raise Stop(f"{item['condition']} would not be its arm: " + "; ".join(mismatches))


def healthy() -> bool:
    """Every node reports Ready, and there is at least one node."""
    nodes = subprocess.run(["kubectl", "--context", "kind-kind", "get", "nodes", "--no-headers"],
                           capture_output=True, text=True)
    rows = [line.split() for line in nodes.stdout.splitlines() if line.strip()]
    return nodes.returncode == 0 and bool(rows) and all(len(row) > 1 and row[1] == "Ready" for row in rows)


def wait_healthy(minutes: int = 30) -> None:
    for i in range(minutes):
        if healthy():
            return
        log(f"cluster not healthy ({i + 1}/{minutes}), waiting 60 s")
        time.sleep(60)
    raise Stop(f"cluster unhealthy for {minutes} minutes")


def run_batch(item: dict, baseline: Path, resume: Path | None) -> int:
    args = ["--resume", resume.name] if resume else [
        "--problems", *item["problems"], "--condition", item["condition"], "--agent", "openai-compatible",
        "--max-steps", str(item["max_steps"])]
    return subprocess.run([sys.executable, "-m", "runner.run_batch", *args], cwd=REPO_ROOT,
                          env=batch_env(item, baseline)).returncode


def settle(item: dict, baseline: Path) -> tuple[list[dict], list[str]]:
    try:
        return verify({"items": [item]}, baseline)
    except (ValueError, OSError) as exc:                     # e.g. a policy file edited mid-run
        raise Stop(f"{item['condition']} cannot be verified: {exc}") from exc


def _records(batch: Path | None) -> int:
    index = batch / "index.jsonl" if batch else None
    return len(index.read_text().splitlines()) if index and index.exists() else 0


def run_item(item: dict, baseline: Path, attempts: int, since: str) -> bool:
    """Run or resume one batch until every episode passes or `attempts` runs are spent. True if complete."""
    for attempt in range(1, attempts + 1):
        batches = find_batches(item["condition"])
        if len(batches) > 1:
            raise Stop(f"{item['condition']} has {len(batches)} batch folders")
        if batches:
            rows, problems = settle(item, baseline)
            if problems:
                raise Stop("; ".join(problems))
            if all(r["ok"] for r in rows):
                return True
            _stop_if_unfixable(item, batches[0], rows, since)
        gate(item, baseline)
        wait_healthy()
        try:
            check_free_disk()
        except RuntimeError as exc:
            raise Stop(str(exc)) from exc
        log(f"{'resume' if batches else 'start'} {item['condition']} (run {attempt}/{attempts})")
        before = _records(batches[0] if batches else None)
        code = run_batch(item, baseline, batches[0] if batches else None)
        log(f"{item['condition']} exited {code}")
        after = find_batches(item["condition"])
        if code != 0 and _records(after[0] if len(after) == 1 else None) == before:
            # It ran no episode: a refused resume (a changed environment, say, after a cluster rebuild on
            # another port) or a failure before the batch existed. Retrying would only repeat it.
            raise Stop(f"{item['condition']}: run_batch exited {code} without running an episode")
    rows, problems = settle(item, baseline)
    if problems:
        raise Stop("; ".join(problems))
    batches = find_batches(item["condition"])
    if batches:
        _stop_if_unfixable(item, batches[0], rows, since)
    return all(r["ok"] for r in rows)


def _stop_if_unfixable(item: dict, batch: Path, rows: list[dict], since: str) -> None:
    """Stop on anything a resume can't fix: a wrong setup, a wrong prompt, an unclean cluster.

    An unclean cluster counts only from this run's start (`since`), so after a person has cleaned it,
    starting run_plan again resumes the refused episodes.
    """
    for row in rows:
        if row["ok"] or row["why"] == "never run" or row["why"].startswith("latest attempt status 'error'"):
            continue
        raise Stop(f"{item['condition']} {row['problem_id']}: {row['why']}")
    index = batch / "index.jsonl"
    resets = 0
    for line in index.read_text().splitlines() if index.exists() else []:
        record = json.loads(line)
        if record.get("status") != "error" or record.get("started_utc", "") < since:
            continue
        if any(u in record.get("error", "") for u in UNCLEAN):
            raise Stop(f"{item['condition']} {record['problem_id']}: {record['error'][:300]}")
        resets += RESET_FAILURE in record.get("error", "")
        if resets >= RESET_FAILURES_BEFORE_STOP:
            raise Stop(f"{item['condition']}: the reset timed out {resets} times in this run: {record['error'][:300]}")


def dry_run(plan: dict, baseline: Path) -> int:
    failed = 0
    for n, item in enumerate(plan["items"], 1):
        mismatches = description_mismatches(describe(batch_env(item, baseline)), item["expect"])
        existing = find_batches(item["condition"])
        texts = ", ".join(f"{t['role']}:{t['task']}@{t['sha256']}" for t in item["expect"]["instructed_texts"]) or "none"
        print(f"{n:>2} {item['condition']:<48} steps {item['max_steps']:>2} budget {item['expect']['step_budget']} "
              f"countdown {item['expect']['budget_countdown']} | {texts} | "
              f"{'GATE OK' if not mismatches else 'GATE FAIL: ' + '; '.join(mismatches)}"
              f"{' | existing: ' + ', '.join(b.name for b in existing) if existing else ''}", flush=True)
        failed += bool(mismatches)
    print(f"{len(plan['items'])} batches, {sum(len(i['problems']) for i in plan['items'])} episodes, "
          f"{failed} failing the gate")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="check preconditions and gate every batch; run nothing")
    parser.add_argument("--attempts", type=int, default=3, help="runs of one batch (start plus resumes) per pass")
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text())

    failed = preconditions(args.plan, args.baseline)
    for reason in failed:
        log(f"PRECONDITION FAILED: {reason}")
    if args.dry_run:
        return dry_run(plan, args.baseline) or (1 if failed else 0)
    if failed:
        return 1

    with LOCK.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another run_plan is running")
            return 1
        commit = _git("rev-parse", "HEAD").strip()
        since = datetime.now(timezone.utc).isoformat()
        log(f"plan {args.plan} at commit {commit}: {len(plan['items'])} batches")
        try:
            for pass_name in ("pass 1", "end pass"):
                log(pass_name)
                for n, item in enumerate(plan["items"], 1):
                    log(f"[{n}/{len(plan['items'])}] {item['condition']}")
                    if not run_item(item, args.baseline, args.attempts, since):
                        log(f"{item['condition']} incomplete after {args.attempts} runs")
        except Stop as stop:
            log(f"STOPPED: {stop}")
            return 2
        rows, problems = verify(plan, args.baseline)
        passed = sum(r["ok"] for r in rows)
        log(f"done: {passed} of {len(rows)} episodes verified; plan problems: {problems or 'none'}")
        return 0 if passed == len(rows) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
