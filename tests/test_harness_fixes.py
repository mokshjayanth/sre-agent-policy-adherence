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

    def __init__(self, namespaces, objects, stuck=(), releases=()):
        self.namespaces = set(namespaces)
        self.objects = {ns: list(items) for ns, items in objects.items()}
        self.stuck = set(stuck)                       # namespaces that never finish terminating
        self.releases = list(releases)                # Helm releases in `observe`
        self.deleted = []

    def run(self, argv, **kwargs):
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        if argv[0] == "helm":                         # helm list -a -q -n observe
            return ok("\n".join(self.releases))
        args = argv[argv.index("kind-kind") + 1:]
        missing = types.SimpleNamespace(returncode=1, stdout="", stderr='Error from server (NotFound): namespaces "x" not found')
        if args[:2] == ["get", "namespace"]:
            return ok(f"namespace/{args[2]}") if args[2] in self.namespaces else missing
        if args[:2] == ["delete", "sc"] or args[:2] == ["delete", "-f"]:
            self.deleted.append(" ".join(args[:3]))
            if args[1] == "-f":
                self.namespaces.discard("openebs")
            return ok()
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


def test_reset_deletes_app_namespaces_and_clears_default_but_keeps_the_clusters_own(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"},
                          {"test-social-network": [_obj("Pod", "debug-pod")], "default": DEFAULT_NS})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    result = harness_fixes.reset_app_state(poll_s=0)
    assert result == {"deleted_namespaces": ["test-social-network"],
                      "deleted_default": ["Job/wrk2-job", "ConfigMap/wrk2-payload-script", "Pod/geo-debug",
                                          "Job/mitigate-rate-mongo"],
                      "removed_harness_services": []}
    assert "test-social-network" not in cluster.namespaces
    kept = {o["metadata"]["name"] for o in cluster.objects["default"]}
    # The earlier problem's workload goes too: the harness recreates it only for a problem that uses it.
    assert {"default", "kubernetes", "kube-root-ca.crt"} <= kept
    assert not {"geo-debug", "mitigate-rate-mongo", "wrk2-job", "wrk2-payload-script"} & kept


def test_reset_is_a_noop_on_a_clean_cluster(monkeypatch):
    cluster = FakeCluster({"default"}, {"default": DEFAULT_NS[:3]})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    assert harness_fixes.reset_app_state(poll_s=0) == {"deleted_namespaces": [], "deleted_default": [],
                                                       "removed_harness_services": []}
    assert cluster.deleted == []


def test_reset_removes_prometheus_and_openebs_a_failed_problem_left(monkeypatch):
    cluster = FakeCluster({"default", "openebs", "observe"}, {"default": DEFAULT_NS[:3]}, releases=["prometheus"])
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    torn_down = []
    import aiopslab.service.telemetry.prometheus as prometheus
    monkeypatch.setattr(prometheus.Prometheus, "teardown", lambda self: torn_down.append("prometheus"))
    result = harness_fixes.reset_app_state(poll_s=0)
    assert result["removed_harness_services"] == ["prometheus", "openebs"] and torn_down == ["prometheus"]
    assert "openebs" not in cluster.namespaces
    assert f"delete -f {harness_fixes.OPENEBS_MANIFEST}" in cluster.deleted


def test_reset_raises_when_a_namespace_will_not_go(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"}, {"default": DEFAULT_NS[:3]},
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
        "default": DEFAULT_NS[:3] + [_obj("Pod", "geo-debug", "2026-09-23T03:29:42Z"),
                                     # the same second as the start, after the reset: not earlier
                                     _obj("Job", "wrk2-job", "2026-09-27T16:00:00Z")]})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    assert harness_fixes.preexisting_objects(started) == [
        "test-social-network/Deployment/post-storage-service-fixed", "default/Pod/geo-debug"]


def test_preexisting_objects_skips_a_namespace_that_does_not_exist(monkeypatch):
    cluster = FakeCluster({"default"}, {"default": DEFAULT_NS[:3]})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    assert harness_fixes.preexisting_objects("2026-09-27T16:00:00+00:00") == []


def test_preexisting_objects_is_empty_after_a_reset(monkeypatch):
    cluster = FakeCluster({"test-social-network", "default"},
                          {"test-social-network": [_obj("Pod", "debug-pod")], "default": DEFAULT_NS})
    monkeypatch.setattr(harness_fixes.subprocess, "run", cluster.run)
    harness_fixes.reset_app_state(poll_s=0)
    assert harness_fixes.preexisting_objects("2026-09-27T16:00:00+00:00") == []


# --- the cluster baseline ---------------------------------------------------------


def _listing(*items):
    return {"items": list(items)}


def _item(kind, name, ns=None, created="2026-09-28T00:00:00Z", spec=None, owned=False, annotations=None):
    meta = {"name": name, "creationTimestamp": created}
    if ns:
        meta["namespace"] = ns
    if owned:
        meta["ownerReferences"] = [{"kind": "ReplicaSet"}]
    if annotations:
        meta["annotations"] = annotations
    return {"kind": kind, "metadata": meta, "spec": spec or {}}


def _cluster(monkeypatch, namespaced, scoped):
    def items(*args):
        return scoped if args[0] == harness_fixes.CLUSTER_KINDS else namespaced
    monkeypatch.setattr(harness_fixes, "_items", items)


BASE_NS = [_item("ConfigMap", "coredns", "kube-system", spec={"a": 1}),
           _item("Pod", "coredns-x", "kube-system", owned=True),
           _item("Pod", "debug-pod", "test-social-network")]
BASE_SCOPED = [_item("Node", "kind-worker", spec={"taints": []}), _item("Namespace", "observe"),
               _item("Namespace", "test-social-network"),
               _item("PersistentVolume", "pvc-1", annotations={"pv.kubernetes.io/provisioned-by": "openebs"})]


def test_cluster_objects_leave_out_what_the_reset_or_the_harness_owns(monkeypatch):
    _cluster(monkeypatch, BASE_NS, BASE_SCOPED)
    assert sorted(harness_fixes.cluster_objects()) == ["Namespace/observe", "Node/kind-worker",
                                                       "kube-system/ConfigMap/coredns"]


def test_no_drift_against_its_own_baseline(monkeypatch, tmp_path):
    _cluster(monkeypatch, BASE_NS, BASE_SCOPED)
    harness_fixes.write_cluster_baseline(tmp_path / "b.json")
    assert harness_fixes.cluster_drift("2026-09-28T01:00:00+00:00", tmp_path / "b.json") == []


def test_drift_finds_new_changed_and_gone_objects(monkeypatch, tmp_path):
    _cluster(monkeypatch, BASE_NS, BASE_SCOPED)
    harness_fixes.write_cluster_baseline(tmp_path / "b.json")
    later = [_item("ConfigMap", "coredns", "kube-system", spec={"a": 2}),                 # changed
             _item("ConfigMap", "prometheus-temp-config", "observe", created="2026-09-28T00:30:00Z"),  # new, earlier
             _item("Deployment", "prometheus-server", "observe", created="2026-09-28T01:00:05Z")]      # this problem's
    scoped = [_item("Namespace", "observe"), _item("Namespace", "debug", created="2026-09-28T00:40:00Z")]
    _cluster(monkeypatch, later, scoped)                                                    # node gone
    assert harness_fixes.cluster_drift("2026-09-28T01:00:00+00:00", tmp_path / "b.json") == [
        "changed: kube-system/ConfigMap/coredns", "gone: Node/kind-worker", "new: Namespace/debug",
        "new: observe/ConfigMap/prometheus-temp-config"]


def test_a_node_taint_or_label_is_drift(monkeypatch, tmp_path):
    _cluster(monkeypatch, BASE_NS, BASE_SCOPED)
    harness_fixes.write_cluster_baseline(tmp_path / "b.json")
    tainted = [_item("Node", "kind-worker", spec={"taints": [{"key": "x", "effect": "NoSchedule"}]}),
               *BASE_SCOPED[1:]]
    _cluster(monkeypatch, BASE_NS, tainted)
    assert harness_fixes.cluster_drift("2026-09-28T01:00:00+00:00", tmp_path / "b.json") == ["changed: Node/kind-worker"]


def test_a_failed_listing_raises_instead_of_reading_as_clean(monkeypatch):
    failed = types.SimpleNamespace(returncode=1, stdout="", stderr="connection refused")
    monkeypatch.setattr(harness_fixes.subprocess, "run", lambda *a, **k: failed)
    with pytest.raises(RuntimeError):
        harness_fixes.preexisting_objects("2026-09-28T00:00:00+00:00")
    with pytest.raises(RuntimeError):
        harness_fixes.cluster_objects()


# --- the control-plane container ----------------------------------------------------


class FakeNode:
    """Just enough of `docker exec kind-control-plane` for the process and file checks."""

    def __init__(self, processes=(), files=None):
        self.processes = dict(processes)              # pid -> command line
        self.files = dict(files or {})                # path -> "d" or "f <size> <mtime>"
        self.calls = []

    def run(self, argv, **kwargs):
        ok = lambda out="": types.SimpleNamespace(returncode=0, stdout=out, stderr="")
        assert argv[:3] == ["docker", "exec", harness_fixes.CONTROL_PLANE], argv
        args = argv[3:]
        self.calls.append(args)
        if args[:2] == ["sh", "-c"] and "init.scope" in args[2]:
            lister = f"9999 sh -c {args[2]}"          # the lister lists itself, as the real one does
            return ok("\n".join(["1 /sbin/init", *(f"{p} {c}" for p, c in self.processes.items()), lister]))
        if args[:2] == ["sh", "-c"] and args[2].startswith("find"):
            lines = [("d\t4096\t1.0\t" if v == "d" else f"{v.split()[0]}\t{v.split()[1]}\t{v.split()[2]}\t") + p
                     for p, v in self.files.items()]
            return ok("\n".join(lines) + "\n")
        if args[:2] == ["kill", "-9"]:
            for pid in args[2:]:
                self.processes.pop(pid, None)
            return ok()
        if args[0] == "rm":
            for path in args[args.index("--") + 1:]:
                self.files = {p: v for p, v in self.files.items() if p != path and not p.startswith(path + "/")}
            return ok()
        raise AssertionError(f"unexpected docker exec: {args}")


BASE_FILES = {"/": "d", "/etc": "d", "/etc/hosts": "f 200 1.0", "/tmp": "d", "/.dockerenv": "f 0 1.0"}


def test_exec_processes_are_the_init_scope_members_but_init_and_the_lister(monkeypatch):
    node = FakeNode({"72701": "sleep 300", "72702": "awk /spec:/ {print}"})
    monkeypatch.setattr(harness_fixes.subprocess, "run", node.run)
    assert harness_fixes.exec_processes() == ["72701 sleep 300", "72702 awk /spec:/ {print}"]
    assert harness_fixes.reap_exec_processes() == ["72701 sleep 300", "72702 awk /spec:/ {print}"]
    assert node.processes == {} and harness_fixes.exec_processes() == []


def test_every_agent_command_is_followed_by_a_reap_even_when_it_times_out(monkeypatch):
    node = FakeNode({"500": "awk runaway"})
    monkeypatch.setattr(harness_fixes.subprocess, "run", node.run)
    def timed_out(container, command, timeout=30):
        raise RuntimeError("Failed to execute command in Docker container")
    monkeypatch.setattr(harness_fixes, "_original_docker_exec", timed_out)
    harness_fixes.take_reaped()
    with pytest.raises(RuntimeError):
        harness_fixes._docker_exec_then_reap(harness_fixes.CONTROL_PLANE, "awk ... > f.yaml")
    assert node.processes == {} and harness_fixes.take_reaped() == ["500 awk runaway"]
    assert harness_fixes.take_reaped() == []


def test_the_patch_routes_the_harness_shell_through_the_reaper(monkeypatch):
    from aiopslab.service.shell import Shell
    monkeypatch.setattr(Shell, "docker_exec", Shell.docker_exec)
    harness_fixes.reap_after_agent_commands()
    assert Shell.docker_exec is harness_fixes._docker_exec_then_reap


def test_container_files_drift_and_reset(monkeypatch):
    node = FakeNode(files=BASE_FILES)
    monkeypatch.setattr(harness_fixes.subprocess, "run", node.run)
    baseline = harness_fixes.container_files()
    assert harness_fixes.container_drift(baseline) == []
    node.files.update({"/geo-deployment-fixed.yaml": "f 74434625536 5.0", "/tmp/work": "d",
                       "/tmp/work/a.sh": "f 10 5.0", "/etc/hosts": "f 260 6.0"})
    del node.files["/.dockerenv"]
    assert sorted(harness_fixes.container_drift(baseline)) == [
        "file changed: /etc/hosts", "file gone: /.dockerenv", "file new: /geo-deployment-fixed.yaml",
        "file new: /tmp/work"]
    assert harness_fixes.reset_container_files(baseline) == ["/geo-deployment-fixed.yaml", "/tmp/work"]
    assert "/tmp/work/a.sh" not in node.files and "/geo-deployment-fixed.yaml" not in node.files
    # what the reset cannot restore is still reported
    assert sorted(harness_fixes.container_drift(baseline)) == ["file changed: /etc/hosts", "file gone: /.dockerenv"]


def test_cluster_drift_reports_container_files_and_live_agent_processes(monkeypatch, tmp_path):
    node = FakeNode(files=BASE_FILES)
    monkeypatch.setattr(harness_fixes.subprocess, "run", node.run)
    _cluster(monkeypatch, BASE_NS, BASE_SCOPED)
    harness_fixes.write_cluster_baseline(tmp_path / "b.json")
    assert harness_fixes.cluster_drift("2026-09-28T01:00:00+00:00", tmp_path / "b.json") == []
    node.files["/pod.yaml"] = "f 4430 7.0"
    node.processes["600"] = "sleep 300"
    assert harness_fixes.cluster_drift("2026-09-28T01:00:00+00:00", tmp_path / "b.json") == [
        "file new: /pod.yaml", "process: 600 sleep 300"]


def test_reset_with_a_baseline_reaps_and_clears_the_control_plane(monkeypatch, tmp_path):
    cluster = FakeCluster({"default"}, {"default": DEFAULT_NS[:3]})
    node = FakeNode({"700": "sleep 300"}, files=BASE_FILES)
    def run(argv, **kwargs):
        return node.run(argv, **kwargs) if argv[0] == "docker" else cluster.run(argv, **kwargs)
    monkeypatch.setattr(harness_fixes.subprocess, "run", run)
    (tmp_path / "b.json").write_text(json.dumps({"objects": {}, "container_files": dict(BASE_FILES)}))
    node.files["/rate-deployment.yaml"] = "f 3533 5.0"
    result = harness_fixes.reset_app_state(poll_s=0, baseline_path=tmp_path / "b.json")
    assert result["reaped_processes"] == ["700 sleep 300"]
    assert result["deleted_container_files"] == ["/rate-deployment.yaml"]
    assert node.files == BASE_FILES and node.processes == {}


def test_a_failed_container_listing_raises(monkeypatch):
    failed = types.SimpleNamespace(returncode=1, stdout="", stderr="container not running")
    monkeypatch.setattr(harness_fixes.subprocess, "run", lambda *a, **k: failed)
    for check in (harness_fixes.exec_processes, harness_fixes.container_files):
        with pytest.raises(RuntimeError):
            check()


def test_low_disk_raises(monkeypatch):
    monkeypatch.setattr(harness_fixes.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=5e9))
    with pytest.raises(RuntimeError, match="low disk: 5.0 GB free"):
        harness_fixes.check_free_disk()
    monkeypatch.setattr(harness_fixes.shutil, "disk_usage", lambda p: types.SimpleNamespace(free=70e9))
    assert harness_fixes.check_free_disk() == 70.0
