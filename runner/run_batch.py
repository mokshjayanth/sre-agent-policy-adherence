"""Run a batch of AIOpsLab problems with one agent and record everything.

From the repo root, with the harness environment active:

    python -m runner.run_batch --problems <id> ... --condition <purpose>-<agent> --agent scripted-probe

One folder per batch; a single problem is just a batch of one.

    runs/<batch_id>/                  batch_id = <UTC time>_<condition>
      batch.json                      environment manifest, recorded before any problem runs
      resume-<n>.json                 manifest re-recorded at each resume
      index.jsonl                     one line appended per finished problem attempt
      problems/<problem_id>/
        trajectory.json               batch ID, condition and agent settings; why the episode ended;
                                      harness history and results; the agent's own messages
                                      (partial if the run failed)
        pods.json                     image digests across all namespaces, after deploy
        error.txt                     traceback, only when the attempt failed
        metrics_output/, trace_output/  telemetry exported by the agent's actions
      problems/<problem_id>.failed-<n>/  an earlier failed or interrupted attempt

Resume with --resume <batch_id>. Problems whose latest index entry is "ok" are
skipped and the rest are retried with the batch's recorded selection, agent
and max steps. Resume refuses to continue when the environment or the agent's
recorded description (model, sampling settings) differs from batch.json, since
the batch would silently mix two setups, unless --allow-env-change is passed.

Working directory: the harness writes exported metrics and traces under the
current directory and shows that absolute path to the agent in observations.
The runner switches to a neutral scratch directory (default ~/aiopslab-work)
so the path an agent reads names neither this project nor the condition,
then moves the exports into the problem folder.

When a problem fails, the orchestrator has already recovered the injected
fault if the agent loop was running; the runner additionally deletes the app
so leftover pods don't disturb the next problem. Harness port-forward leaks
are cleaned up before and after every problem (runner/harness_fixes.py).
"""

import argparse
import asyncio
import importlib
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
RUNS_ROOT = REPO_ROOT / "runs"
# Importable as `python -m runner.run_batch` or by file path; the repo root wins name clashes.
for _path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from aiopslab.orchestrator import Orchestrator  # noqa: E402

from runner.harness_fixes import (  # noqa: E402
    PINNED_OTEL_CHART_VERSION,
    fix_exec_shell_doc,
    pin_otel_chart,
    stop_leaked_port_forwards,
    stop_orphaned_port_forwards,
)
from runner.manifest import collect_cluster_images, collect_static_manifest  # noqa: E402
from runner.problem_sets import TASK_TYPES, select_problems, task_type  # noqa: E402
from runner.trajectory_checks import (  # noqa: E402
    count_tool_call_issues,
    final_submission_state,
    submitted,
    termination_reason,
)

AGENTS = {
    "scripted-probe": "agents.scripted_probe:ScriptedProbeAgent",
    "openai-compatible": "agents.openai_compatible:OpenAICompatibleAgent",
    "noop-submit": "agents.noop_submit:NoopSubmitAgent",
}

# batch.json fields that must be unchanged for a resumed batch to stay one setup.
ENV_KEYS = [
    ("repo", "commit"),
    ("repo", "status"),
    ("harness", "aiopslab_commit"),
    ("harness", "aiopslab_applications_commit"),
    ("harness", "status"),
    ("harness", "config_yml"),
    ("cluster", "kind_node_image"),
    ("cluster", "api_server"),
    # host.memory_total_mb is recorded but not compared: kernel updates shift it slightly.
    ("host", "ec2_instance_type"),
    ("host", "cpu_count"),
    ("host", "gpus"),
    ("python", "prefix"),
    ("python", "version"),
    ("python", "poetry_lock_sha256"),
    ("python", "pip_freeze"),
    ("pins",),
    # Agents read their model and settings from the environment (e.g. AGENT_MODEL), so
    # without this a resume could continue a batch with a different model.
    ("run", "agent_description"),
]

# Batch labels are <purpose>-<agent>[-<variant>], lowercase; see CLAUDE.md.
CONDITION_PURPOSES = ("smoke", "validation", "noise", "pilot", "main", "b1", "b2", "b3", "t1", "t2")
CONDITION_PATTERN = re.compile(
    rf"(?:{'|'.join(CONDITION_PURPOSES)})-[a-z0-9][a-z0-9.]*(?:-[a-z0-9][a-z0-9.]*)*"
)

EXPORT_DIRS = ("metrics_output", "trace_output")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_agent(name: str):
    module_name, class_name = AGENTS[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)


def _agent_description(name: str) -> dict | None:
    agent_cls = _load_agent(name)
    return agent_cls.describe() if hasattr(agent_cls, "describe") else None


def check_step_budget(agent_description: dict | None, max_steps: int) -> None:
    """An agent that states a step budget must be run with exactly that many steps."""
    budget = (agent_description or {}).get("step_budget")
    if budget is not None and budget != max_steps:
        raise SystemExit(f"The agent states a budget of {budget} steps but --max-steps is {max_steps}; "
                         "they must match so the budget the agent is told is the one it gets.")


def _lookup(data: dict, path: tuple) -> object:
    for key in path:
        data = (data or {}).get(key)
    return data


def _env_diff(recorded: dict, current: dict) -> list[str]:
    return [".".join(p) for p in ENV_KEYS if _lookup(recorded, p) != _lookup(current, p)]


def _freeze_by_package(lines: list[str] | None) -> dict[str, str]:
    by_package = {}
    for line in lines or []:
        if "#egg=" in line:
            name = line.rsplit("#egg=", 1)[1]
        else:
            name = re.split(r"===|==| @ ", line, maxsplit=1)[0]
        by_package[name.strip().lower()] = line
    return by_package


def _describe_change(key: str, recorded: dict, current: dict) -> str:
    """The changed key, plus what moved for the keys where that's short enough to show."""
    if key == "run.agent_description":
        path = ("run", "agent_description")
        return f"{key} (batch: {_lookup(recorded, path)}; now: {_lookup(current, path)})"
    if key != "python.pip_freeze":
        return key
    old = _freeze_by_package(_lookup(recorded, ("python", "pip_freeze")))
    new = _freeze_by_package(_lookup(current, ("python", "pip_freeze")))
    parts = [f"{old[n]} -> {new[n]}" for n in sorted(old.keys() & new.keys()) if old[n] != new[n]]
    parts += [f"added {new[n]}" for n in sorted(new.keys() - old.keys())]
    parts += [f"removed {old[n]}" for n in sorted(old.keys() - new.keys())]
    return f"{key} ({'; '.join(parts) or 'order or formatting only'})"


def _read_index(index_path: Path) -> list[dict]:
    if not index_path.exists():
        return []
    return [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]


def _snapshot_exports(workdir: Path) -> dict[str, set[str]]:
    return {d: set(os.listdir(workdir / d)) if (workdir / d).is_dir() else set() for d in EXPORT_DIRS}


def _move_exports(workdir: Path, before: dict[str, set[str]], problem_dir: Path) -> None:
    for d in EXPORT_DIRS:
        src = workdir / d
        if not src.is_dir():
            continue
        for name in sorted(set(os.listdir(src)) - before[d]):
            dest = problem_dir / d
            dest.mkdir(exist_ok=True)
            shutil.move(str(src / name), str(dest / name))


def _cleanup_after_failure(orch: Orchestrator) -> None:
    problem = getattr(orch.session, "problem", None) if orch.session else None
    if problem is None:
        return
    try:
        problem.app.cleanup()
    except Exception as exc:  # best effort; the failure itself is already recorded
        print(f"App cleanup after failure also failed: {exc}")


def _set_aside_previous_attempt(problem_dir: Path) -> None:
    if not problem_dir.exists():
        return
    n = 1
    while (failed := problem_dir.with_name(f"{problem_dir.name}.failed-{n}")).exists():
        n += 1
    problem_dir.rename(failed)


def _results_for_record(results: dict | None) -> dict | None:
    """The harness's return value without its two traps.

    `history` repeats the session history as Python repr strings once serialised,
    so it's dropped; the trajectory's own `history` holds the same turns properly.
    `final_state` is the last env response, a submission status or a raw
    observation, so it's reduced to the status name or None.
    """
    if not results:
        return results
    kept = {k: v for k, v in results.items() if k != "history"}
    kept["final_state"] = final_submission_state(results)
    return kept


def _trajectory(
    problem_id: str, agent_name: str, batch_info: dict, session, agent, results, termination: str
) -> dict:
    """trajectory.json, self-describing so it stays interpretable when copied out of its batch.

    `batch_info` carries batch_id, condition and agent_description.
    """
    record = getattr(agent, "record", None)
    return {
        "problem_id": problem_id,
        **batch_info,
        "agent_name": agent_name,
        "session_id": str(session.session_id) if session else None,
        "solution": session.solution if session else None,
        "termination_reason": termination,
        "results": _results_for_record(results),
        # What the harness recorded: the agent's replies and the raw observations.
        "history": [item.model_dump() for item in session.history] if session else [],
        # What the model received: rendered prompts, per-turn suffixes, trimming per call.
        # None for agents that don't expose record().
        "agent_record": record() if callable(record) else None,
    }


async def run_problem(
    problem_id: str,
    agent_cls,
    agent_name: str,
    max_steps: int,
    problem_dir: Path,
    workdir: Path,
    batch_info: dict,
) -> dict:
    _set_aside_previous_attempt(problem_dir)
    problem_dir.mkdir(parents=True)
    record = {"problem_id": problem_id, "task": task_type(problem_id), "started_utc": _utcnow()}
    # A harness port-forward left from an earlier run would hold port 32000 and break get_metrics.
    record["stale_port_forwards"] = stop_orphaned_port_forwards()
    if record["stale_port_forwards"]:
        print(f"    stopped {record['stale_port_forwards']} port-forward(s) left over from an earlier run")
    exports_before = _snapshot_exports(workdir)

    orch = Orchestrator()
    orch.register_agent(agent_cls(), name=agent_name)
    results = None
    error = None
    try:
        problem_desc, instructions, apis = orch.init_problem(problem_id)
        orch.agent.init_context(problem_desc, instructions, fix_exec_shell_doc(apis))
        # Deploy, fault injection and workload start are done, so the pods exist.
        _write_json(problem_dir / "pods.json", collect_cluster_images())
        results = await orch.start_problem(max_steps=max_steps)
        record["status"] = "ok"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        record["status"] = "error"
        record["error"] = error
        (problem_dir / "error.txt").write_text(traceback.format_exc())
        _cleanup_after_failure(orch)
    finally:
        session = orch.session
        termination = termination_reason(error, results)
        _write_json(
            problem_dir / "trajectory.json",
            _trajectory(problem_id, agent_name, batch_info, session, orch.agent, results, termination),
        )
        _move_exports(workdir, exports_before, problem_dir)
        # A non-zero count also marks a problem whose get_metrics or get_traces call failed.
        leaked = stop_leaked_port_forwards()
        if leaked:
            print(f"    stopped {leaked} port-forward(s) the harness left running")
        # Expected to be non-zero whenever get_metrics or get_traces ran, even successfully.
        orphaned = stop_orphaned_port_forwards()
        if orphaned:
            print(f"    stopped {orphaned} orphaned kubectl port-forward(s)")

    record.update(
        finished_utc=_utcnow(),
        session_id=str(session.session_id) if session else None,
        solution=session.solution if session else None,
        # "ok" status only means the episode ran; these say whether and how it ended with an answer.
        submitted=submitted(results),
        termination_reason=termination,
        results=(results or {}).get("results"),
        framework_overhead_s=(results or {}).get("framework_overhead"),
        leaked_port_forwards=leaked,
        orphaned_port_forwards=orphaned,
        tool_call_issues=count_tool_call_issues(
            [item.model_dump() for item in session.history] if session else []
        ),
    )
    return record


def _start_or_resume(args) -> tuple[Path, dict, list[str], dict[str, str]]:
    """Create the batch folder or reopen it; return (batch dir, current run settings, problems, skipped)."""
    pin_otel_chart()
    pins = {
        "otel_demo_chart": PINNED_OTEL_CHART_VERSION,
        # A stable ID; the reason is in notes/2026-09-14-exec-shell-timeout-unreachable.md.
        "exec_shell_doc": "timeout-line-removed",
    }

    if args.resume:
        batch_dir = RUNS_ROOT / args.resume
        recorded = json.loads((batch_dir / "batch.json").read_text())
        settings = recorded["run"]
        current_run = {**settings, "agent_description": _agent_description(settings["agent"]), "argv": sys.argv}
        current = collect_static_manifest(pins=pins, run=current_run)
        changed = _env_diff(recorded, current)
        if changed and not args.allow_env_change:
            details = "\n".join(f"  - {_describe_change(key, recorded, current)}" for key in changed)
            raise SystemExit(
                f"Environment differs from {batch_dir / 'batch.json'} in:\n{details}\n"
                "Resuming would mix two setups in one batch. Start a new batch, or pass "
                "--allow-env-change to continue anyway (the difference is recorded)."
            )
        n = 1
        while (batch_dir / f"resume-{n}.json").exists():
            n += 1
        _write_json(batch_dir / f"resume-{n}.json", {**current, "changed_from_batch": changed})
        # Current, not recorded, agent description: with --allow-env-change the two can differ.
        return batch_dir, current_run, settings["problems"], settings["skipped"]

    if not args.condition or not CONDITION_PATTERN.fullmatch(args.condition):
        raise SystemExit(
            "--condition must be <purpose>-<agent>[-<variant>] in lowercase, with purpose one of "
            f"{', '.join(CONDITION_PURPOSES)} (e.g. validation-scripted, b1-qwen3-1.7b); "
            f"got {args.condition!r}."
        )
    problems, skipped = select_problems(args.problems, args.problem_file, args.task, args.include_excluded)
    agent_description = _agent_description(args.agent)
    check_step_budget(agent_description, args.max_steps)
    settings = {
        "condition": args.condition,
        "agent": args.agent,
        "agent_description": agent_description,
        "max_steps": args.max_steps,
        "selection": {
            "problems": args.problems,
            "problem_file": args.problem_file,
            "task": args.task,
            "all": args.all,
            "include_excluded": args.include_excluded,
        },
        "problems": problems,
        "skipped": skipped,
    }
    batch_dir = RUNS_ROOT / f"{datetime.now(timezone.utc):%Y-%m-%dT%H%M%SZ}_{args.condition}"
    (batch_dir / "problems").mkdir(parents=True)
    _write_json(batch_dir / "batch.json", collect_static_manifest(pins=pins, run={**settings, "argv": sys.argv}))
    return batch_dir, settings, problems, skipped


async def run_batch(args) -> int:
    batch_dir, settings, problems, skipped = _start_or_resume(args)
    index_path = batch_dir / "index.jsonl"
    history = _read_index(index_path)
    latest = {rec["problem_id"]: rec["status"] for rec in history}
    todo = [p for p in problems if latest.get(p) != "ok"]

    agent_cls = _load_agent(settings["agent"])
    batch_info = {
        "batch_id": batch_dir.name,
        "condition": settings["condition"],
        "agent_description": settings.get("agent_description"),
    }
    args.workdir.mkdir(parents=True, exist_ok=True)
    os.chdir(args.workdir)

    print(f"Batch {batch_dir.name}: {len(todo)} to run, {len(problems) - len(todo)} already ok, "
          f"{len(skipped)} excluded")
    for i, problem_id in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {problem_id}")
        record = await run_problem(
            problem_id,
            agent_cls,
            settings["agent"],
            settings["max_steps"],
            batch_dir / "problems" / problem_id,
            args.workdir,
            batch_info,
        )
        record["attempt"] = sum(1 for rec in history if rec["problem_id"] == problem_id) + 1
        history.append(record)
        with index_path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        print(f"    {record['status']}" + (f": {record['error']}" if record["status"] == "error" else ""))

    final = {rec["problem_id"]: rec["status"] for rec in history}
    failed = [p for p in problems if final.get(p) != "ok"]
    print(f"Done: {len(problems) - len(failed)} ok, {len(failed)} not ok -> {batch_dir}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run AIOpsLab problems as a recorded batch.")
    selection = p.add_mutually_exclusive_group(required=True)
    selection.add_argument("--problems", nargs="+", metavar="ID", help="explicit problem IDs")
    selection.add_argument("--problem-file", metavar="PATH", help="file with one problem ID per line")
    selection.add_argument("--task", choices=TASK_TYPES, help="every problem of one task type")
    selection.add_argument("--all", action="store_true", help="every registered problem")
    selection.add_argument("--resume", metavar="BATCH_ID", help="continue an existing batch in runs/")
    p.add_argument("--condition", help="batch label, e.g. b1-scripted (required for a new batch)")
    p.add_argument("--agent", choices=sorted(AGENTS), default="scripted-probe")
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--include-excluded", action="store_true", help="also run known-broken problems")
    p.add_argument("--allow-env-change", action="store_true", help="resume even if the environment changed")
    p.add_argument("--workdir", type=Path, default=Path.home() / "aiopslab-work",
                   help="neutral working directory for harness exports (default: ~/aiopslab-work)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_batch(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
