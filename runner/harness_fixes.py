"""Workarounds for the vendored AIOpsLab harness, applied from outside it.

third_party/aiopslab stays unmodified, so everything that compensates for its
behaviour lives here, and this file is the complete list of places where a run
deviates from stock AIOpsLab. Revisit it whenever the harness pin moves.

- OTel demo chart pin: AstronomyShop installs its Helm chart unpinned.
  See notes/2026-09-13-harness-pin-coverage.md.
- Port-forward cleanup: a failed metrics query leaks `kubectl port-forward` and
  two reader threads, and even a successful one orphans kubectl on port 32000.
  See notes/2026-09-13-get-metrics-failures.md.
- exec_shell doc fix: its docstring advertises a `timeout` parameter the parser
  can never accept, and a quoted-timeout variant parses silently into a
  mangled shell command instead of raising. See
  notes/2026-09-14-exec-shell-timeout-unreachable.md.
- Failed pods: a bare pod left Failed in an app namespace blocks every later
  deploy of that app. See notes/2026-09-20-failed-pods-block-deploys.md.
- Reset between problems: SocialNetwork's namespace is never deleted, so objects
  an agent created there, or in `default`, persist into later episodes. Every
  problem now starts from deleted app namespaces and a cleared `default`. See
  notes/2026-09-27-cross-episode-contamination.md.
- Cluster baseline: the rest of the cluster (other namespaces, cluster-scoped
  objects, nodes) is checked against a baseline taken once on a fresh cluster,
  when a run names one. See notes/2026-09-27-fresh-run.md.
- Control-plane container: agent commands run inside it; files they write and
  processes they leave would outlive the episode. Every agent command is
  followed by killing what it left running, the reset deletes new files and
  restores changed ones from a snapshot taken with the baseline, and the
  baseline covers both. See notes/2026-09-28-control-plane-persistence.md.
"""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
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


# --- failed pods left in an app namespace -------------------------------------
#
# The harness waits for *every* pod in the app's namespace to be ready before a
# problem starts (kubectl.py:114-143, via helm.assert_if_deployed). A pod left
# behind in Failed state never becomes ready, so every later deploy of that app
# waits the full 300 s and raises. The harness creates such pods itself: the
# MongoDB faults run `test-connect`, `mongo-check` and `mongo-fix` pods, and a
# crashed one is never cleaned up. One leftover therefore poisons every
# subsequent episode on that app, whatever the agent does. Seen on 2026-09-20:
# `test-connect` failed at 10:42 and broke 35 SocialNetwork episodes.

APP_NAMESPACES = ("test-social-network", "test-hotel-reservation", "astronomy-shop")


def leftover_pods(namespaces: tuple[str, ...] = APP_NAMESPACES, min_age_s: int = 0) -> list[str]:
    """Bare pods (no owner) in the app namespaces that aren't ready, and so block a deploy.

    A pod the harness creates directly -- test-connect, mongo-check, mongo-fix -- has no controller
    to replace it. Once it fails or crash-loops it stays, and every later deploy of that app waits
    for it forever. Pods owned by a ReplicaSet or Job are left alone: those belong to the app.
    `min_age_s` guards a pod a running episode may still be using.
    """
    stale = []
    for namespace in namespaces:
        listing = subprocess.run(
            ["kubectl", "--context", "kind-kind", "get", "pods", "-n", namespace, "-o", "json"],
            capture_output=True, text=True, check=False)
        try:
            pods = json.loads(listing.stdout or "{}").get("items", [])
        except json.JSONDecodeError:
            continue
        for pod in pods:
            meta, status = pod.get("metadata", {}), pod.get("status", {})
            if meta.get("ownerReferences"):
                continue
            phase = status.get("phase")
            ready = phase == "Succeeded" or (
                bool(status.get("containerStatuses"))
                and all(c.get("ready") for c in status["containerStatuses"]))
            if ready:
                continue
            if min_age_s and _age_seconds(status.get("startTime") or meta.get("creationTimestamp")) < min_age_s:
                continue
            stale.append(f"{namespace}/{meta.get('name')}")
    return stale


def _age_seconds(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    created = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created).total_seconds()


def delete_failed_pods(namespaces: tuple[str, ...] = APP_NAMESPACES, min_age_s: int = 0) -> list[str]:
    """Delete the pods leftover_pods() finds; return what was deleted."""
    deleted = leftover_pods(namespaces, min_age_s)
    for entry in deleted:
        namespace, name = entry.split("/", 1)
        subprocess.run(["kubectl", "--context", "kind-kind", "delete", "pod", name, "-n", namespace,
                        "--ignore-not-found", "--wait=false"], capture_output=True, check=False)
    return deleted


# --- state left behind by earlier episodes -------------------------------------
#
# The harness removes only its own Helm release between problems. HotelReservation's cleanup also
# deletes its namespace (hotelres.py:87), but SocialNetwork's has that line commented out
# (socialnet.py:72), so its namespace lives from one problem to the next. Anything an agent created
# there -- a copied deployment, a debug pod, a config map -- is still present, and visible, in every
# later episode; agents also leave pods and jobs in `default`. Found on 2026-09-27: objects from
# 2026-09-20 onwards had been visible to later agents, and a crash-looping copied deployment made
# every SocialNetwork deploy time out (notes/2026-09-27-cross-episode-contamination.md).
#
# Every problem therefore starts from a reset: the app namespaces are deleted and waited for (the
# harness recreates its namespace and TLS secret when it builds the app, socialnet.py:21-22), and
# `default` is cleared of everything except the cluster's own objects and the harness's workload
# generator. preexisting_objects() then records what, if anything, predates the problem, which
# should always be nothing.

# The cluster's own objects in `default`. The harness's wrk2 job and its config map are not kept: the
# harness recreates them only for a problem that starts a workload, and a delete that is slow makes its
# create fail, so an earlier problem's job and pods could otherwise still be there
# (generators/workload/wrk.py:31-105).
DEFAULT_KEEP = {("ServiceAccount", "default"), ("Service", "kubernetes"), ("ConfigMap", "kube-root-ca.crt")}
# Kinds an agent can create in a namespace. Endpoints are left out: the cluster rewrites them whenever a
# service's pods change, and a service's own are created with it.
NAMESPACED_KINDS = ("pods,jobs,cronjobs,deployments,statefulsets,daemonsets,replicasets,services,configmaps,"
                    "secrets,ingresses,persistentvolumeclaims,serviceaccounts,roles,rolebindings,networkpolicies,"
                    "horizontalpodautoscalers,resourcequotas,limitranges,poddisruptionbudgets")
# What the harness installs for every problem and removes only when the problem ends normally
# (orchestrator.py:55-67 and 205-214). After a runner or harness error both stay, and the next problem's
# deploy would reuse a Prometheus that still holds the earlier episode's metrics.
OPENEBS_MANIFEST = "https://openebs.github.io/charts/openebs-operator.yaml"
PROMETHEUS_NAMESPACE = "observe"


def _kubectl(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", "--context", "kind-kind", *args], capture_output=True, text=True,
                          check=False, timeout=timeout)


def _items(*args: str) -> list[dict]:
    """`kubectl get ... -o json` items. Raises rather than answer "nothing": an empty answer proves a
    clean start, so a listing that failed must never read as one."""
    listing = _kubectl("get", *args, "-o", "json")
    if listing.returncode != 0:
        raise RuntimeError(f"kubectl get {' '.join(args)} failed: {listing.stderr.strip()[:300]}")
    return json.loads(listing.stdout or "{}").get("items", [])


def _namespaced_objects(namespace: str) -> list[dict]:
    """Every object of NAMESPACED_KINDS in the namespace that no other object owns."""
    items = _items(NAMESPACED_KINDS, "-n", namespace)
    return [{"kind": item["kind"], "name": item["metadata"]["name"],
             "created": item["metadata"].get("creationTimestamp")}
            for item in items if not item["metadata"].get("ownerReferences")]


def _namespace_exists(namespace: str) -> bool:
    """True or False only on an answer from the cluster; a failed call raises, never reads as absent."""
    result = _kubectl("get", "namespace", namespace, "-o", "name")
    if result.returncode == 0:
        return True
    if "NotFound" in result.stderr or "not found" in result.stderr:
        return False
    raise RuntimeError(f"kubectl get namespace {namespace} failed: {result.stderr.strip()[:300]}")


def default_leftovers() -> list[dict]:
    """Objects in `default` that are not the cluster's own."""
    return [o for o in _namespaced_objects("default") if (o["kind"], o["name"]) not in DEFAULT_KEEP]


def _harness_releases() -> list[str]:
    listing = subprocess.run(["helm", "list", "-a", "-q", "-n", PROMETHEUS_NAMESPACE, "--kube-context", "kind-kind"],
                             capture_output=True, text=True, check=False, timeout=120)
    if listing.returncode != 0:
        raise RuntimeError(f"helm list -n {PROMETHEUS_NAMESPACE} failed: {listing.stderr.strip()[:300]}")
    return listing.stdout.split()


def teardown_harness_services() -> list[str]:
    """Remove Prometheus and OpenEBS if a problem left them, exactly as the harness's own teardown does.

    A no-op after a problem that ended normally, since the harness removed both itself.
    """
    removed = []
    if _harness_releases():
        from aiopslab.service.telemetry.prometheus import Prometheus
        Prometheus().teardown()
        removed.append("prometheus")
    if _namespace_exists("openebs"):
        _kubectl("delete", "sc", "openebs-hostpath", "openebs-device", "--ignore-not-found")
        _kubectl("delete", "-f", OPENEBS_MANIFEST, "--ignore-not-found", "--wait=false", timeout=300)
        removed.append("openebs")
    return removed


def reset_app_state(namespaces: tuple[str, ...] = APP_NAMESPACES, timeout_s: int = 600,
                    poll_s: float = 2, baseline_path: Path | None = None) -> dict:
    """Delete the app namespaces, clear `default` and remove harness services a failed problem left,
    then wait until all of it is gone.

    Raises if anything is still present after `timeout_s`: a problem that cannot start clean must
    fail, not run next to an earlier episode's objects. The error names the reset, and is resumable:
    the next attempt waits again (runner/run_plan.py).
    """
    deleted_namespaces = [ns for ns in namespaces if _namespace_exists(ns)]
    for ns in deleted_namespaces:
        _kubectl("delete", "namespace", ns, "--wait=false")
    deleted_default = default_leftovers()
    for obj in deleted_default:
        # Foreground, so a job's pods are gone before the job itself is.
        _kubectl("delete", obj["kind"].lower(), obj["name"], "-n", "default", "--ignore-not-found",
                 "--cascade=foreground", "--wait=false")
    removed_services = teardown_harness_services()
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = [f"namespace/{ns}" for ns in (*deleted_namespaces, *(["openebs"] if "openebs" in removed_services
                                                                          else [])) if _namespace_exists(ns)]
        remaining += [f"default/{o['kind']}/{o['name']}" for o in default_leftovers()]
        if not remaining:
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f"reset_app_state: still present after {timeout_s} s: {remaining}")
        time.sleep(poll_s)
    result = {"deleted_namespaces": deleted_namespaces,
              "deleted_default": [f"{o['kind']}/{o['name']}" for o in deleted_default],
              "removed_harness_services": removed_services}
    if baseline_path is not None:
        # The control plane's file system and processes (see "the control-plane container" below).
        recorded = json.loads(Path(baseline_path).read_text())
        result["reaped_processes"] = reap_exec_processes()
        container = reset_container_files(recorded["container_files"], recorded.get("container_snapshot"))
        result["deleted_container_files"] = container["deleted"]
        result["restored_container_files"] = container["restored"]
    return result


def preexisting_objects(started_utc: str, namespaces: tuple[str, ...] = APP_NAMESPACES) -> list[str]:
    """Objects in the app namespaces or `default` created before this problem started.

    Called once the problem is deployed and its fault injected. After reset_app_state() the answer
    should be empty; a non-empty list marks an episode that did not start clean.
    """
    cutoff = _to_second(started_utc)
    found = []
    for ns in (*namespaces, "default"):
        # Listing a namespace that doesn't exist should return nothing, but that is kubectl's
        # behaviour, not ours to rely on; one that doesn't exist holds nothing.
        if not _namespace_exists(ns):
            continue
        for obj in _namespaced_objects(ns):
            if ns == "default" and (obj["kind"], obj["name"]) in DEFAULT_KEEP:
                continue
            created = obj["created"]
            if created and _created(created) < cutoff:
                found.append(f"{ns}/{obj['kind']}/{obj['name']}")
    return found


def _created(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _to_second(started_utc: str) -> datetime:
    """The problem's start at Kubernetes' one-second resolution. An object created in the same second
    as the start, after the reset, must not read as earlier than it."""
    return datetime.fromisoformat(started_utc).replace(microsecond=0)


# --- the rest of the cluster ----------------------------------------------------
#
# The reset covers the app namespaces and `default`. An agent can also create or change objects
# elsewhere: 1 write in the main study and ladder did (a config map in `observe`, batch
# 2026-09-21T074218Z_main-ministral3-8b-policy). So a run can take a baseline of everything else once,
# on a fresh cluster before its first episode, and each problem then checks the cluster against it:
# nothing new that predates the problem, nothing changed, nothing gone (notes/2026-09-27-fresh-run.md).

# Kinds without a namespace that an agent could create or change the cluster through.
CLUSTER_KINDS = ("nodes,namespaces,persistentvolumes,clusterroles,clusterrolebindings,storageclasses,"
                 "priorityclasses,customresourcedefinitions,mutatingwebhookconfigurations,"
                 "validatingwebhookconfigurations,ingressclasses,apiservices,csidrivers,volumeattachments")
BASELINE_VARIABLE = "RUNNER_CLUSTER_BASELINE"


def _fingerprint(item: dict) -> str:
    """What an agent's change would alter: everything but metadata and status, plus the labels."""
    body = {k: v for k, v in item.items() if k not in ("metadata", "status")}
    body["labels"] = item["metadata"].get("labels") or {}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def cluster_objects() -> dict[str, dict]:
    """Objects the reset does not cover, keyed "<ns>/<Kind>/<name>" or "<Kind>/<name>".

    Unowned objects of NAMESPACED_KINDS in every namespace but the app namespaces, and every object of
    CLUSTER_KINDS, except the app namespaces themselves (the reset deletes them) and volumes a
    provisioner made for a claim. What the harness makes for a problem is newer than the problem's
    start, so cluster_drift() does not count it.
    """
    found = {}
    for item in _items(NAMESPACED_KINDS, "-A"):
        meta = item["metadata"]
        ns = meta.get("namespace", "")
        if ns in APP_NAMESPACES or meta.get("ownerReferences"):
            continue
        found[f"{ns}/{item['kind']}/{meta['name']}"] = {"created": meta.get("creationTimestamp"),
                                                         "fingerprint": _fingerprint(item)}
    for item in _items(CLUSTER_KINDS):
        meta = item["metadata"]
        if item["kind"] == "Namespace" and meta["name"] in APP_NAMESPACES:
            continue
        if item["kind"] == "PersistentVolume" and "pv.kubernetes.io/provisioned-by" in (meta.get("annotations") or {}):
            continue
        found[f"{item['kind']}/{meta['name']}"] = {"created": meta.get("creationTimestamp"),
                                                   "fingerprint": _fingerprint(item)}
    return found


def write_cluster_baseline(path: Path, snapshot: Path | None = None) -> dict:
    """Record cluster_objects() and container_files() as the state every later problem is checked against,
    with a snapshot of the container's files for the reset to restore from (container_snapshot())."""
    snapshot = snapshot or CONTAINER_SNAPSHOT_DIR / f"{path.stem}.files.tar"
    files, snapshot_sha = container_snapshot(snapshot)
    baseline = {"taken_utc": datetime.now(timezone.utc).isoformat(), "objects": cluster_objects(),
                "container_files": files,
                "container_snapshot": {"file": _repo_relative(snapshot), "sha256": snapshot_sha}}
    path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n")
    return baseline


def _repo_relative(path: Path) -> str:
    path = Path(path).resolve()
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def cluster_drift(started_utc: str, baseline_path: Path) -> list[str]:
    """How the cluster outside the reset differs from the baseline, for a problem started at started_utc.

    "new: <key>" for an object absent from the baseline and created before the problem started (one the
    harness made during this problem's deploy is newer), "changed: <key>" and "gone: <key>" for baseline
    objects. Empty means the problem starts in the cluster the baseline recorded.
    """
    cutoff = _to_second(started_utc)
    baseline = json.loads(Path(baseline_path).read_text())["objects"]
    now = cluster_objects()
    drift = [f"new: {key}" for key, obj in now.items()
             if key not in baseline and (not obj["created"] or _created(obj["created"]) < cutoff)]
    drift += [f"changed: {key}" for key, obj in now.items()
              if key in baseline and obj["fingerprint"] != baseline[key]["fingerprint"]]
    drift += [f"gone: {key}" for key in baseline if key not in now]
    recorded = json.loads(Path(baseline_path).read_text())
    if "container_files" in recorded:
        drift += container_drift(recorded["container_files"])
        drift += [f"process: {p}" for p in exec_processes()]
    return sorted(drift)


# --- the control-plane container ----------------------------------------------
#
# exec_shell runs every agent command as `docker exec kind-control-plane sh -c "<command>"`, with `/` as
# the working directory (service/shell.py:101-117, actions/base.py:104). Two things outlived their
# episode there, and neither the reset nor the baseline covered them (notes/2026-09-28-control-plane-
# persistence.md):
# - Files. Whatever an agent wrote in the container stayed for every later agent to list or read; 5
#   files in `/` and 7 in `/tmp` were there on 2026-09-28, and later episodes listed them.
# - Processes. The 30 s timeout kills the docker client on the host, not the command in the container,
#   and a background or runaway process is reparented to the container's init. One agent's awk loop
#   wrote for 14 minutes after its episode had moved on, 74 GB, and filled the disk.
# The harness runs nothing else in the container, so a process or a path there that the baseline does
# not have is an agent's. Every agent command is followed by killing whatever it left running, the
# reset deletes new paths and restores changed or missing files from the snapshot taken with the
# baseline, and cluster_drift() reports any path the reset could not put back and any live process an
# agent command started.
# Restoring, not refusing, is what keeps the run going when a command changes a file that was already
# there: kubectl rewrites its discovery cache under /root/.kube/cache whenever an agent names a resource
# type it doesn't know, which stopped stage 1 on 2026-09-28, and an agent has run apt-get install on the
# node itself (runs/2026-09-20T095754Z_main-ministral3-3b-scored).

CONTROL_PLANE = "kind-control-plane"
# docker exec puts its process, and every orphan it leaves, in the container's init.scope cgroup; the
# only other member is init itself. Systemd services and pods have cgroups of their own.
_LIST_EXEC_PROCESSES = ('for p in /proc/[0-9]*; do [ "$(cat $p/cgroup 2>/dev/null)" = "0::/init.scope" ] '
                        '&& echo "${p#/proc/} $(tr "\\0" " " < $p/cmdline 2>/dev/null)"; done; true')
# Where an agent can write: the container's root file system and its writable mounts.
CONTAINER_FS_ROOTS = ("/", "/var", "/tmp", "/dev/shm", "/run")
# Subtrees the system itself rewrites: the kernel's views, the container runtime's, kubelet's and etcd's
# state, and logs; and, found by the calibration in notes/2026-09-28-control-plane-persistence.md, the
# volatile journal (/run/log/journal), the systemd units kubelet rewrites as pods come and go
# (/run/systemd/transient), and systemd's records of the scopes of pods that per-problem daemonsets start
# on this node (/run/systemd/units). Nothing else changed, between problems or during five of them.
CONTAINER_FS_SKIP = ("/proc", "/sys", "/dev/pts", "/var/lib/containerd", "/var/lib/kubelet", "/var/lib/etcd",
                     "/var/log", "/run/containerd", "/run/log/journal", "/run/systemd/transient",
                     "/run/systemd/units")


def _docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False, timeout=timeout)


def exec_processes() -> list[str]:
    """"<pid> <command line>" of every live process an exec into the control plane started."""
    listing = _docker("exec", CONTROL_PLANE, "sh", "-c", _LIST_EXEC_PROCESSES)
    if listing.returncode != 0:
        raise RuntimeError(f"listing processes in {CONTROL_PLANE} failed: {listing.stderr.strip()[:300]}")
    found = []
    for line in listing.stdout.splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and pid != "1" and "0::/init.scope" not in command:      # not init, not the lister
            found.append(f"{pid} {command.strip()[:200]}")
    return found


def reap_exec_processes() -> list[str]:
    """Kill every process an exec into the control plane left running; return what was killed."""
    found = exec_processes()
    if found:
        _docker("exec", CONTROL_PLANE, "kill", "-9", *[p.split(" ", 1)[0] for p in found])
    return found


# Processes killed after agent commands since the runner last took the list (take_reaped()).
_REAPED: list[str] = []


def take_reaped() -> list[str]:
    taken = list(_REAPED)
    _REAPED.clear()
    return taken


def _docker_exec_then_reap(container_name: str, command: str, timeout=30):
    try:
        return _original_docker_exec(container_name, command, timeout=timeout)
    finally:
        if container_name == CONTROL_PLANE:
            _REAPED.extend(reap_exec_processes())


def reap_after_agent_commands() -> None:
    """Patch Shell.docker_exec so nothing an agent command starts outlives the command. Idempotent.

    The harness documents exec_shell as not stateful (actions/base.py:83), so a command's background
    children have no later use; this makes its timeout true of the command itself.
    """
    from aiopslab.service.shell import Shell
    Shell.docker_exec = staticmethod(_docker_exec_then_reap)


def _load_original_docker_exec():
    from aiopslab.service.shell import Shell
    return Shell.docker_exec


_original_docker_exec = _load_original_docker_exec()


def container_files() -> dict[str, str]:
    """Every path under CONTAINER_FS_ROOTS outside CONTAINER_FS_SKIP: "d" for a directory, "<type> <size>
    <mtime>" for anything else. Each root stays on its own mount."""
    prune = " -o ".join(f"-path {p}" for p in CONTAINER_FS_SKIP)
    script = " ; ".join(f"find {root} -xdev \\( {prune} \\) -prune -o -printf '%y\\t%s\\t%T@\\t%p\\n'"
                        for root in CONTAINER_FS_ROOTS)
    listing = _docker("exec", CONTROL_PLANE, "sh", "-c", script, timeout=300)
    if listing.returncode != 0 or not listing.stdout:
        raise RuntimeError(f"listing files in {CONTROL_PLANE} failed: {listing.stderr.strip()[:300]}")
    files = {}
    for line in listing.stdout.splitlines():
        kind, size, mtime, path = line.split("\t", 3)
        if path in CONTAINER_FS_SKIP:
            continue
        files[path] = "d" if kind == "d" else f"{kind} {size} {mtime}"
    return files


def _outermost(paths: list[str]) -> list[str]:
    """The paths that are not inside another of them."""
    kept = []
    for path in sorted(paths):
        if not any(path.startswith(k.rstrip("/") + "/") for k in kept):
            kept.append(path)
    return kept


def container_drift(baseline: dict[str, str]) -> list[str]:
    now = container_files()
    drift = [f"file new: {p}" for p in _outermost([p for p in now if p not in baseline])]
    drift += [f"file changed: {p}" for p, v in now.items() if p in baseline and v != baseline[p]]
    drift += [f"file gone: {p}" for p in baseline if p not in now]
    return drift


# Snapshots are ~600 MB, so they live in the gitignored study/ folder; the baseline records each one's
# sha256, and the reset checks it before restoring from it.
CONTAINER_SNAPSHOT_DIR = REPO_ROOT / "study" / "baselines"
# File types tar can snapshot and restore: regular files and symlinks. Sockets, pipes and devices are
# only compared.
_RESTORABLE = ("f", "l")
_TAR_CREATE = ["tar", "-C", "/", "--format=posix", "--hard-dereference", "--no-recursion", "-cf", "-", "-T", "-"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def container_snapshot(snapshot: Path) -> tuple[dict[str, str], str]:
    """Write every restorable file of container_files() to the tar `snapshot`; return the listing and the
    tar's sha256. Raises unless the listing is the same before and after, so the two agree."""
    before = container_files()
    names = [p.lstrip("/") for p, v in before.items() if v != "d" and v.split()[0] in _RESTORABLE]
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot, "wb") as out:
        made = subprocess.run(["docker", "exec", "-i", CONTROL_PLANE, *_TAR_CREATE],
                              input=("\n".join(names) + "\n").encode(), stdout=out, stderr=subprocess.PIPE,
                              check=False, timeout=600)
    if made.returncode != 0:
        raise RuntimeError(f"snapshot of {CONTROL_PLANE} failed: {made.stderr.decode()[-300:]}")
    if container_files() != before:
        raise RuntimeError(f"{CONTROL_PLANE}'s files changed while the snapshot was taken; take it again")
    return before, _sha256(snapshot)


def reset_container_files(baseline: dict[str, str], snapshot: dict | None = None) -> dict[str, list[str]]:
    """Put the container's files back to the baseline: delete every path it doesn't have, and restore every
    changed or missing one from `snapshot` (the baseline's "container_snapshot"). Return the outermost
    paths deleted and the paths restored. What can't be restored is left for cluster_drift() to report."""
    now = container_files()
    new = _outermost([p for p in now if p not in baseline])
    # A baseline directory that is missing or became something else; a file, symlink that changed or is gone.
    dirs = sorted(p for p, v in baseline.items() if v == "d" and now.get(p) != "d")
    files = sorted(p for p, v in baseline.items()
                   if v != "d" and v.split()[0] in _RESTORABLE and now.get(p) != v)
    if snapshot is None:
        dirs, files = [], []
    remove = _outermost(new + [p for p in dirs + files if p in now])
    if remove:
        removed = _docker("exec", CONTROL_PLANE, "rm", "-rf", "--one-file-system", "--", *remove)
        if removed.returncode != 0:
            raise RuntimeError(f"removing {remove} in {CONTROL_PLANE} failed: {removed.stderr.strip()[:300]}")
    if dirs:
        made = _docker("exec", CONTROL_PLANE, "mkdir", "-p", "--", *dirs)
        if made.returncode != 0:
            raise RuntimeError(f"recreating {dirs} in {CONTROL_PLANE} failed: {made.stderr.strip()[:300]}")
    if files:
        tar = REPO_ROOT / snapshot["file"]
        if _sha256(tar) != snapshot["sha256"]:
            raise RuntimeError(f"{tar} is not the snapshot the baseline recorded")
        with open(tar, "rb") as source:
            restored = subprocess.run(["docker", "exec", "-i", CONTROL_PLANE, "tar", "-C", "/", "-xpf", "-",
                                       "--no-recursion", "--", *[p.lstrip("/") for p in files]],
                                      stdin=source, capture_output=True, check=False, timeout=600)
        if restored.returncode != 0:
            raise RuntimeError(f"restoring {files[:20]} in {CONTROL_PLANE} failed: "
                               f"{restored.stderr.decode()[-300:]}")
    return {"deleted": new, "restored": dirs + files}


# The disk every run writes to, and the container's writable layer, share one volume. The episode that
# filled it on 2026-09-28 ended the run in the middle of writing, without a line saying why.
MIN_FREE_DISK_GB = 20


def check_free_disk(path: str = "/", minimum_gb: float = MIN_FREE_DISK_GB) -> float:
    """Free space in GB; raises below the minimum, before a problem can fill the rest."""
    free = shutil.disk_usage(path).free / 1e9
    if free < minimum_gb:
        raise RuntimeError(f"low disk: {free:.1f} GB free, below {minimum_gb} GB")
    return round(free, 1)


# --- exec_shell doc fix -------------------------------------------------------
#
# exec_shell(command: str, timeout: int = 30) documents a timeout parameter
# (actions/base.py) that ResponseParser.parse_args can never accept: its
# is_shell_command branch requires the entire argument string to be exactly one
# quoted string, with no path for a second argument. Worse, a quoted timeout
# value (timeout="60") passes that check and parses silently into a mangled
# command instead of raising -- e.g. exec_shell("cmd", timeout="60") becomes
# the single argument 'cmd", timeout="60'. Every agent sees this docstring
# verbatim (runner hands `apis` straight to init_context), so this is a
# condition-independent trap, not a quirk of one model. Fixed here, once, for
# every agent -- not in an agent's prompt, which would only cover one agent and
# would make B1 (plain prompting) stop being plain for the others.

_EXEC_SHELL_TIMEOUT_LINE = re.compile(r"\n[ \t]*timeout \(int\):[^\n]*")


def fix_exec_shell_doc(apis: dict) -> dict:
    """Return `apis` with the unusable `timeout` parameter removed from exec_shell's doc."""
    fixed = dict(apis)
    if "exec_shell" in fixed:
        fixed["exec_shell"] = _EXEC_SHELL_TIMEOUT_LINE.sub("", fixed["exec_shell"])
    return fixed
