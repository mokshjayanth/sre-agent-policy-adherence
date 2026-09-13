"""Workarounds for the vendored AIOpsLab harness, applied from outside it.

third_party/aiopslab stays unmodified, so everything that compensates for its
behaviour lives here. Revisit this file whenever the harness pin moves.

- OTel demo chart pin: AstronomyShop installs its Helm chart unpinned.
  See notes/2026-09-13-harness-pin-coverage.md.
- Port-forward cleanup: a failed metrics query leaks `kubectl port-forward` and
  two reader threads, and even a successful one orphans kubectl on port 32000.
  See notes/2026-09-13-get-metrics-failures.md.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
if str(AIOPSLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(AIOPSLAB_ROOT))

from aiopslab.orchestrator.problems.registry import ProblemRegistry  # noqa: E402
from aiopslab.service.apps.astronomy_shop import AstronomyShop  # noqa: E402

# --- OTel demo chart pin -----------------------------------------------------
#
# AstronomyShop.deploy() calls Helm.install(**self.helm_configs) against the remote
# open-telemetry repo with no "version" key, so the chart floats onto whatever is
# newest at install time; it released 13 times in 2026 as of this writing.
# Helm.install already turns a "version" key into `--version X`. Only matters
# once Astronomy Shop problems are in scope.

# Latest opentelemetry-demo chart release as of 2026-09-13 (0.41.1, published
# 2026-09-11). Re-verify and bump deliberately, never silently.
PINNED_OTEL_CHART_VERSION = "0.41.1"

_original_get_problem_instance = ProblemRegistry.get_problem_instance


def _get_problem_instance_pinned(self, problem_id: str):
    prob = _original_get_problem_instance(self, problem_id)
    if isinstance(getattr(prob, "app", None), AstronomyShop):
        prob.app.helm_configs["version"] = PINNED_OTEL_CHART_VERSION
    return prob


def pin_otel_chart() -> None:
    """Patch ProblemRegistry so Astronomy Shop problems install the pinned chart. Idempotent."""
    ProblemRegistry.get_problem_instance = _get_problem_instance_pinned


# --- Port-forward cleanup ----------------------------------------------------

# Exactly the port-forward commands AIOpsLab runs: PrometheusAPI (observer/metric_api.py)
# and TraceAPI (observer/trace_api.py). Anything else, including their `sh -c` wrappers,
# is left alone.
HARNESS_PORT_FORWARD = re.compile(
    r"kubectl port-forward (?:svc/prometheus-server \d+:80 -n observe"
    r"|pod/\S+ 16686:16686 -n \S+"
    r"|svc/jaeger 16686:16686 -n \S+)"
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def terminate_pids(pids: list[int], grace_s: float = 5) -> None:
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
    terminate_pids([int(pid) for pid in listed.split()])
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def harness_port_forward_pids(listing: str | None = None) -> list[int]:
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


def stop_leaked_port_forwards() -> int:
    """Stop harness port-forwards their owner never cleaned up; return how many.

    PrometheusAPI and TraceAPI start `kubectl port-forward` plus two non-daemon
    threads that read its output until the owner's stop_event is set. When a
    metrics query raises, export_all_metrics exits before its cleanup(), so the
    threads never stop and Python can't exit once the batch is done.
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


def stop_orphaned_port_forwards() -> int:
    """Stop kubectl processes still running a harness port-forward; return how many.

    Even when a query succeeds, the harness's stop_port_forward() terminates only
    the `sh -c` wrapper, so kubectl keeps running and holding its local port. The
    next PrometheusAPI then finds port 32000 taken and forwards another port, while
    get_metrics still queries localhost:32000, so that call fails. Batches run one
    at a time on one cluster, so no other run can own a live harness port-forward.
    """
    pids = harness_port_forward_pids()
    terminate_pids(pids)
    return len(pids)
