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
