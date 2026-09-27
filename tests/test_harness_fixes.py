"""Port-forward cleanup, without a cluster. Only processes these tests start are signalled."""

import subprocess
import threading
import time

from runner import harness_fixes

LISTING = "\n".join([
    "101 kubectl port-forward svc/prometheus-server 32000:80 -n observe",
    "102 /bin/sh -c kubectl port-forward svc/prometheus-server 32001:80 -n observe",
    "103 kubectl port-forward pod/jaeger-7d9f 16686:16686 -n astronomy-shop",
    "104 kubectl port-forward svc/jaeger 16686:16686 -n test-hotel-reservation",
    "105 kubectl port-forward svc/my-db 5432:5432 -n default",
    "106 kubectl port-forward svc/prometheus-server 9090:9090 -n observe",
    "107 kubectl --context kind-kind port-forward svc/prometheus-server 32000:80 -n observe",
    "108 sh -c kubectl port-forward svc/jaeger 16686:16686 -n test-hotel-reservation",
])


def test_matches_only_exact_harness_port_forward_commands():
    assert harness_fixes.harness_port_forward_pids(LISTING) == [101, 103, 104]


def test_terminate_pids_falls_back_to_sigkill():
    polite = subprocess.Popen(["sleep", "300"], start_new_session=True)
    stubborn = subprocess.Popen(["sh", "-c", "trap '' TERM; while :; do sleep 1; done"], start_new_session=True)
    harness_fixes.terminate_pids([polite.pid, stubborn.pid], grace_s=1)
    assert polite.wait(timeout=5) is not None
    assert stubborn.wait(timeout=5) is not None


def test_stop_orphaned_port_forwards_stops_what_the_listing_reports(monkeypatch):
    target = subprocess.Popen(["sleep", "300"], start_new_session=True)
    monkeypatch.setattr(harness_fixes, "harness_port_forward_pids", lambda listing=None: [target.pid])
    assert harness_fixes.stop_orphaned_port_forwards() == 1
    assert target.wait(timeout=5) is not None


class FakePortForward:
    """Shaped like PrometheusAPI after a failed query: process running, reader thread looping."""

    def __init__(self):
        self.stop_event = threading.Event()
        self.port_forward_process = subprocess.Popen(["sleep", "300"])
        self.output_threads = [threading.Thread(target=self.print_output)]
        self.output_threads[0].start()

    def print_output(self):
        while not self.stop_event.is_set():
            time.sleep(0.05)


def test_stop_leaked_port_forwards_stops_reader_threads_and_process():
    leak = FakePortForward()
    assert harness_fixes.stop_leaked_port_forwards() == 1
    assert not leak.output_threads[0].is_alive()
    assert leak.port_forward_process.poll() is not None


EXEC_SHELL_DOC = """Execute any shell command in a predefined debugging environment.
        Note: this is NOT A STATEFUL OR INTERACTIVE shell session. So you cannot
        execute commands like "kubectl edit".

        Args:
            command (str): The command to execute.
            timeout (int): Timeout in seconds for the command execution. Default is 30.

        Returns:
            str: The output of the command."""


def test_fix_exec_shell_doc_removes_only_the_timeout_line():
    apis = {"exec_shell": EXEC_SHELL_DOC, "get_logs": "some other doc"}
    fixed = harness_fixes.fix_exec_shell_doc(apis)
    assert "timeout" not in fixed["exec_shell"]
    assert "command (str): The command to execute." in fixed["exec_shell"]
    assert fixed["get_logs"] == "some other doc"
    assert apis["exec_shell"] == EXEC_SHELL_DOC  # original dict untouched


def test_fix_exec_shell_doc_is_a_noop_without_exec_shell():
    assert harness_fixes.fix_exec_shell_doc({"submit": "doc"}) == {"submit": "doc"}


# --- reset between problems (notes/2026-09-27-cross-episode-contamination.md) ---

import json
import types

import pytest


class FakeCluster:
    """Just enough of kubectl for reset_app_state and preexisting_objects: namespaces and objects."""

    def __init__(self, namespaces, objects, stuck=()):
        self.namespaces = set(namespaces)
        self.objects = {ns: list(items) for ns, items in objects.items()}
        self.stuck = set(stuck)                       # namespaces that never finish terminating
        self.deleted = []

    def run(self, argv, **kwargs):
        args = argv[argv.index("kind-kind") + 1:]
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        missing = types.SimpleNamespace(returncode=1, stdout="", stderr="NotFound")
        if args[:2] == ["get", "namespace"]:
            return ok(f"namespace/{args[2]}") if args[2] in self.namespaces else missing
        if args[:2] == ["delete", "namespace"]:
            self.deleted.append(f"namespace/{args[2]}")
            if args[2] not in self.stuck:
                self.namespaces.discard(args[2])
                self.objects.pop(args[2], None)
            return ok()
        if args[0] == "get":                          # get <kinds> -n <ns> -o json
            ns = args[args.index("-n") + 1]
            return ok(json.dumps({"items": self.objects.get(ns, [])}))
        if args[0] == "delete":                       # delete <kind> <name> -n <ns> ...
            kind, name, ns = args[1], args[2], args[args.index("-n") + 1]
            self.deleted.append(f"{ns}/{kind}/{name}")
            self.objects[ns] = [o for o in self.objects.get(ns, []) if o["metadata"]["name"] != name]
            return ok()
        raise AssertionError(f"unexpected kubectl call: {args}")


def _obj(kind, name, created="2026-09-20T07:54:17Z", owned=False):
    meta = {"name": name, "creationTimestamp": created}
    if owned:
        meta["ownerReferences"] = [{"kind": "Job"}]
    return {"kind": kind, "metadata": meta}


DEFAULT_NS = [_obj("ServiceAccount", "default"), _obj("Service", "kubernetes"),
              _obj("ConfigMap", "kube-root-ca.crt"), _obj("Job", "wrk2-job"),
              _obj("Pod", "wrk2-job-x1", owned=True), _obj("ConfigMap", "wrk2-payload-script"),
              _obj("Pod", "geo-debug"), _obj("Job", "mitigate-rate-mongo"),
              _obj("Pod", "mitigate-rate-mongo-a", owned=True)]


def test_reset_deletes_app_namespaces_and_clears_default_but_keeps_cluster_and_harness_objects(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"},
                          {"test-social-network": [_obj("Pod", "debug-pod")], "default": DEFAULT_NS})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    result = harness_fixes.reset_app_state(poll_s=0)
    assert result == {"deleted_namespaces": ["test-social-network"],
                      "deleted_default": ["Pod/geo-debug", "Job/mitigate-rate-mongo"]}
    assert "test-social-network" not in cluster.namespaces
    kept = {o["metadata"]["name"] for o in cluster.objects["default"]}
    assert {"default", "kubernetes", "kube-root-ca.crt", "wrk2-job", "wrk2-payload-script"} <= kept
    assert not {"geo-debug", "mitigate-rate-mongo"} & kept


def test_reset_is_a_noop_on_a_clean_cluster(monkeypatch):
    cluster = FakeCluster({"default"}, {"default": DEFAULT_NS[:6]})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    assert harness_fixes.reset_app_state(poll_s=0) == {"deleted_namespaces": [], "deleted_default": []}
    assert cluster.deleted == []


def test_reset_raises_when_a_namespace_will_not_go(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"}, {"default": DEFAULT_NS[:6]},
                          stuck={"test-social-network"})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    with pytest.raises(RuntimeError, match="namespace/test-social-network"):
        harness_fixes.reset_app_state(timeout_s=0, poll_s=0)


def test_preexisting_objects_reports_only_what_predates_the_problem(monkeypatch):
    started = "2026-09-27T16:00:00.123456+00:00"
    cluster = FakeCluster({"test-social-network", "default"}, {
        "test-social-network": [_obj("Deployment", "compose-post-service", "2026-09-27T16:00:05Z"),
                                _obj("Deployment", "post-storage-service-fixed", "2026-09-27T11:33:04Z"),
                                _obj("ReplicaSet", "old-rs", "2026-09-20T07:54:17Z", owned=True)],
        "default": DEFAULT_NS[:6] + [_obj("Pod", "geo-debug", "2026-09-23T03:29:42Z")]})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    assert harness_fixes.preexisting_objects(started) == [
        "test-social-network/Deployment/post-storage-service-fixed", "default/Pod/geo-debug"]


def test_preexisting_objects_is_empty_after_a_reset(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"},
                          {"test-social-network": [_obj("Pod", "debug-pod")], "default": DEFAULT_NS})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    harness_fixes.reset_app_state(poll_s=0)
    assert harness_fixes.preexisting_objects("2026-09-27T16:00:00+00:00") == []
