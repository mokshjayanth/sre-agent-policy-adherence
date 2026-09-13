"""Run a batch of AIOpsLab problems with one agent and record everything.

One folder per batch; a single problem is just a batch of one.

    runs/<batch_id>/                  batch_id = <UTC time>_<condition>
      batch.json                      environment manifest, recorded before any problem runs
      resume-<n>.json                 manifest re-recorded at each resume
      index.jsonl                     one line appended per finished problem attempt
      problems/<problem_id>/
        trajectory.json               harness history and results (partial if the run failed)
        pods.json                     image digests across all namespaces, after deploy
        error.txt                     traceback, only when the attempt failed
        metrics_output/, trace_output/  telemetry exported by the agent's actions
      problems/<problem_id>.failed-<n>/  an earlier failed or interrupted attempt

Resume with --resume <batch_id>. Problems whose latest index entry is "ok" are
skipped and the rest are retried with the batch's recorded selection, agent
and max steps. Resume refuses to continue when the environment differs from
batch.json, since the batch would silently mix two setups, unless
--allow-env-change is passed.

Working directory: the harness writes exported metrics and traces under the
current directory and shows that absolute path to the agent in observations.
The runner switches to a neutral scratch directory (default ~/aiopslab-work)
so the path an agent reads names neither this project nor the condition,
then moves the exports into the problem folder.

When a problem fails, the orchestrator has already recovered the injected
fault if the agent loop was running; the runner additionally deletes the app
so leftover pods don't disturb the next problem.
"""

import argparse
import asyncio
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
RUNS_ROOT = REPO_ROOT / "runs"
sys.path.insert(0, str(AIOPSLAB_ROOT))

from aiopslab.orchestrator import Orchestrator  # noqa: E402

from pin_otel_chart import PINNED_OTEL_CHART_VERSION, apply_pin  # noqa: E402
from problem_sets import TASK_TYPES, select_problems, task_type  # noqa: E402
from run_manifest import collect_cluster_images, collect_static_manifest  # noqa: E402

AGENTS = {
    "scripted-probe": "scripted_probe_agent:ScriptedProbeAgent",
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
    ("python", "prefix"),
    ("python", "version"),
    ("python", "poetry_lock_sha256"),
    ("python", "pip_freeze"),
    ("pins",),
]

EXPORT_DIRS = ("metrics_output", "trace_output")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_agent(name: str):
    module_name, class_name = AGENTS[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)


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
    """The changed key, plus which packages moved when it's the pip freeze."""
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


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _terminate_pids(pids: list[int], grace_s: float = 5) -> None:
    """SIGTERM each process, then SIGKILL whatever is still alive after the grace period."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_s
    for pid in pids:
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _terminate_shell_process(process: subprocess.Popen) -> None:
    """Terminate a `shell=True` process and the command it started.

    /bin/sh is dash here, and `sh -c "kubectl ..."` forks kubectl rather than
    exec'ing it, so terminating the shell alone leaves kubectl running as an
    orphan. Children are listed before the shell dies, while they still have it
    as their parent.
    """
    listed = subprocess.run(["pgrep", "-P", str(process.pid)], capture_output=True, text=True).stdout
    _terminate_pids([int(pid) for pid in listed.split()])
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


# Exactly the port-forward commands AIOpsLab runs: PrometheusAPI (observer/metric_api.py)
# and TraceAPI (observer/trace_api.py). Anything else, including their `sh -c` wrappers,
# is left alone.
HARNESS_PORT_FORWARD = re.compile(
    r"kubectl port-forward (?:svc/prometheus-server \d+:80 -n observe"
    r"|pod/\S+ 16686:16686 -n \S+"
    r"|svc/jaeger 16686:16686 -n \S+)"
)


def _harness_port_forward_pids(listing: str | None = None) -> list[int]:
    """PIDs of processes whose command line is exactly a harness port-forward command."""
    if listing is None:
        listing = subprocess.run(
            ["pgrep", "-a", "-f", "kubectl port-forward"], capture_output=True, text=True
        ).stdout
    pids = []
    for line in listing.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and HARNESS_PORT_FORWARD.fullmatch(command):
            pids.append(int(pid))
    return pids


def _stop_orphaned_port_forwards() -> int:
    """Stop kubectl processes still running a harness port-forward; return how many.

    Even when a query succeeds, the harness's stop_port_forward() terminates only
    the `sh -c` wrapper, so kubectl keeps running and holding its local port. The
    next PrometheusAPI then finds port 32000 taken and forwards another port, while
    get_metrics still queries localhost:32000, so that call fails. Called before
    and after every problem; batches run one at a time on one cluster, so no other
    run can own a live harness port-forward. See
    notes/2026-09-13-get-metrics-failures.md.
    """
    pids = _harness_port_forward_pids()
    _terminate_pids(pids)
    return len(pids)


def _stop_leaked_port_forwards() -> int:
    """Stop harness port-forwards their owner never cleaned up; return how many.

    AIOpsLab's PrometheusAPI and TraceAPI start `kubectl port-forward` plus two
    non-daemon threads that read its output until the owner's stop_event is set.
    When a metrics query raises, export_all_metrics exits before its cleanup(),
    so the threads never stop and Python can't exit once the batch is done.
    See notes/2026-09-13-get-metrics-failures.md.
    """
    owners = {}
    for thread in threading.enumerate():
        target = getattr(thread, "_target", None)
        owner = getattr(target, "__self__", None)
        if getattr(target, "__name__", None) == "print_output" and hasattr(owner, "stop_event"):
            owners[id(owner)] = owner
    for owner in owners.values():
        owner.stop_event.set()
        process = getattr(owner, "port_forward_process", None)
        if process is not None and process.poll() is None:
            _terminate_shell_process(process)
        for thread in getattr(owner, "output_threads", []):
            thread.join(timeout=5)
    return len(owners)


async def run_problem(
    problem_id: str,
    agent_cls,
    agent_name: str,
    max_steps: int,
    problem_dir: Path,
    workdir: Path,
) -> dict:
    _set_aside_previous_attempt(problem_dir)
    problem_dir.mkdir(parents=True)
    record = {"problem_id": problem_id, "task": task_type(problem_id), "started_utc": _utcnow()}
    # A harness port-forward left from an earlier run would hold port 32000 and break get_metrics.
    record["stale_port_forwards"] = _stop_orphaned_port_forwards()
    if record["stale_port_forwards"]:
        print(f"    stopped {record['stale_port_forwards']} port-forward(s) left over from an earlier run")
    exports_before = _snapshot_exports(workdir)

    orch = Orchestrator()
    orch.register_agent(agent_cls(), name=agent_name)
    results = None
    try:
        problem_desc, instructions, apis = orch.init_problem(problem_id)
        orch.agent.init_context(problem_desc, instructions, apis)
        # Deploy, fault injection and workload start are done, so the pods exist.
        _write_json(problem_dir / "pods.json", collect_cluster_images())
        results = await orch.start_problem(max_steps=max_steps)
        record["status"] = "ok"
    except Exception as exc:
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        (problem_dir / "error.txt").write_text(traceback.format_exc())
        _cleanup_after_failure(orch)
    finally:
        session = orch.session
        _write_json(problem_dir / "trajectory.json", {
            "problem_id": problem_id,
            "session_id": str(session.session_id) if session else None,
            "agent_name": agent_name,
            "solution": session.solution if session else None,
            "results": results,
            "history": [item.model_dump() for item in session.history] if session else [],
        })
        _move_exports(workdir, exports_before, problem_dir)
        # A non-zero count also marks a problem whose get_metrics or get_traces call failed.
        leaked = _stop_leaked_port_forwards()
        if leaked:
            print(f"    stopped {leaked} port-forward(s) the harness left running")
        # Expected to be non-zero whenever get_metrics or get_traces ran, even successfully.
        orphaned = _stop_orphaned_port_forwards()
        if orphaned:
            print(f"    stopped {orphaned} orphaned kubectl port-forward(s)")

    record.update(
        finished_utc=_utcnow(),
        session_id=str(session.session_id) if session else None,
        solution=session.solution if session else None,
        results=(results or {}).get("results"),
        framework_overhead_s=(results or {}).get("framework_overhead"),
        leaked_port_forwards=leaked,
        orphaned_port_forwards=orphaned,
    )
    return record


# Batch labels are <purpose>-<agent>[-<variant>], lowercase; see CLAUDE.md.
CONDITION_PURPOSES = ("smoke", "validation", "noise", "b1", "b2", "b3", "t1", "t2")
CONDITION_PATTERN = re.compile(
    rf"(?:{'|'.join(CONDITION_PURPOSES)})-[a-z0-9][a-z0-9.]*(?:-[a-z0-9][a-z0-9.]*)*"
)


def _start_or_resume(args) -> tuple[Path, dict, list[str], dict[str, str]]:
    """Create the batch folder or reopen it; return (batch dir, run settings, problems, skipped)."""
    apply_pin()
    pins = {"otel_demo_chart": PINNED_OTEL_CHART_VERSION}

    if args.resume:
        batch_dir = RUNS_ROOT / args.resume
        recorded = json.loads((batch_dir / "batch.json").read_text())
        settings = recorded["run"]
        current = collect_static_manifest(pins=pins, run={**settings, "argv": sys.argv})
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
        return batch_dir, settings, settings["problems"], settings["skipped"]

    if not args.condition or not CONDITION_PATTERN.fullmatch(args.condition):
        raise SystemExit(
            "--condition must be <purpose>-<agent>[-<variant>] in lowercase, with purpose one of "
            f"{', '.join(CONDITION_PURPOSES)} (e.g. validation-scripted, b1-qwen3-1.7b); "
            f"got {args.condition!r}."
        )
    problems, skipped = select_problems(args.problems, args.problem_file, args.task, args.include_excluded)
    agent_cls = _load_agent(args.agent)
    settings = {
        "condition": args.condition,
        "agent": args.agent,
        "agent_description": agent_cls.describe() if hasattr(agent_cls, "describe") else None,
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
