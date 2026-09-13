"""Batch runner behaviour without a cluster: failures, resume, environment checks, labels.

Problem setup is replaced by a failure and the port-forward sweeps are disabled,
so nothing here touches the cluster or any running process.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from runner import run_batch as rb

REPO_ROOT = Path(__file__).resolve().parents[1]
P1 = "misconfig_app_hotel_res-detection-1"
P2 = "noop_detection_hotel_reservation-1"


def _fail_setup(self, problem_id):
    raise RuntimeError("simulated init failure")


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # run_batch changes directory; restore it afterwards
    monkeypatch.setattr(rb, "RUNS_ROOT", tmp_path / "runs")
    monkeypatch.setattr(rb.Orchestrator, "init_problem", _fail_setup)
    monkeypatch.setattr(rb, "stop_orphaned_port_forwards", lambda: 0)
    monkeypatch.setattr(rb, "stop_leaked_port_forwards", lambda: 0)

    def main(*argv):
        return rb.main([*argv, "--workdir", str(tmp_path / "work")])

    return main


def _batch(tmp_path) -> Path:
    [batch] = list((tmp_path / "runs").iterdir())
    return batch


def _index(batch: Path) -> list[dict]:
    return [json.loads(line) for line in (batch / "index.jsonl").read_text().splitlines()]


def test_failed_problems_are_recorded_and_the_batch_continues(run, tmp_path):
    assert run("--problems", P1, P2, "--condition", "smoke-unit", "--max-steps", "1") == 1
    batch = _batch(tmp_path)
    records = _index(batch)
    assert [r["status"] for r in records] == ["error", "error"]
    assert records[0]["error"] == "RuntimeError: simulated init failure"
    assert (batch / "problems" / P1 / "error.txt").exists()
    trajectory = json.loads((batch / "problems" / P1 / "trajectory.json").read_text())
    assert trajectory["history"] == [] and trajectory["results"] is None


def test_resume_retries_failures_and_keeps_earlier_attempts(run, tmp_path):
    run("--problems", P1, "--condition", "smoke-unit", "--max-steps", "1")
    batch = _batch(tmp_path)
    assert run("--resume", batch.name) == 1
    assert (batch / "problems" / f"{P1}.failed-1").is_dir()
    assert [r["attempt"] for r in _index(batch)] == [1, 2]
    assert json.loads((batch / "resume-1.json").read_text())["changed_from_batch"] == []


def test_resume_refuses_a_changed_environment_and_names_changed_packages(run, tmp_path):
    run("--problems", P1, "--condition", "smoke-unit", "--max-steps", "1")
    batch = _batch(tmp_path)
    recorded = json.loads((batch / "batch.json").read_text())
    freeze = recorded["python"]["pip_freeze"]
    pandas_line = next(line for line in freeze if line.startswith("pandas=="))
    recorded["python"]["pip_freeze"] = ["pandas==0.0.1" if line == pandas_line else line for line in freeze]
    recorded["python"]["pip_freeze"].append("zzz-fake==1.0")
    recorded["pins"] = {"otel_demo_chart": "0.0.0"}
    (batch / "batch.json").write_text(json.dumps(recorded))

    with pytest.raises(SystemExit) as refusal:
        run("--resume", batch.name)
    message = str(refusal.value)
    assert f"pandas==0.0.1 -> {pandas_line}" in message
    assert "removed zzz-fake==1.0" in message
    assert "pins" in message
    assert not (batch / "resume-1.json").exists()

    assert run("--resume", batch.name, "--allow-env-change") == 1
    changed = json.loads((batch / "resume-1.json").read_text())["changed_from_batch"]
    assert changed == ["python.pip_freeze", "pins"]


@pytest.mark.parametrize("label", ["smoke-scripted", "validation-scripted", "noise-sonnet5",
                                   "b1-qwen3-1.7b", "t2-qwen3-1.7b-grpo"])
def test_condition_labels_accepted(label):
    assert rb.CONDITION_PATTERN.fullmatch(label)


@pytest.mark.parametrize("label", ["runner-validation", "unit", "B1-qwen", "b4-x", "smoke",
                                   "smoke-", "b1_qwen", "smoke--x"])
def test_condition_labels_rejected(label):
    assert not rb.CONDITION_PATTERN.fullmatch(label)


def test_bad_label_is_rejected_before_any_folder_is_created(run, tmp_path):
    with pytest.raises(SystemExit, match="purpose"):
        run("--problems", P1, "--condition", "runner-validation")
    assert not (tmp_path / "runs").exists()


SUBPROCESS = """
import sys
sys.path.insert(0, {repo!r})
from pathlib import Path
from runner import run_batch as rb
rb.RUNS_ROOT = Path({runs!r})
def fail(self, problem_id):
    raise RuntimeError("simulated init failure")
rb.Orchestrator.init_problem = fail
rb.stop_orphaned_port_forwards = lambda: 0
rb.stop_leaked_port_forwards = lambda: 0
sys.exit(rb.main({argv!r}))
"""


def test_resume_under_python3_accepts_a_batch_started_with_python(tmp_path):
    bin_dir = Path(sys.executable).parent
    python, python3 = bin_dir / "python", bin_dir / "python3"
    if not (python.exists() and python3.exists()):
        pytest.skip("interpreter has no python/python3 pair")
    runs = tmp_path / "runs"

    def run_with(interpreter: Path, argv: list[str]) -> subprocess.CompletedProcess:
        code = SUBPROCESS.format(repo=str(REPO_ROOT), runs=str(runs),
                                 argv=[*argv, "--workdir", str(tmp_path / "work")])
        return subprocess.run([str(interpreter), "-c", code], capture_output=True, text=True,
                              timeout=180, cwd=tmp_path)

    started = run_with(python, ["--problems", P1, "--condition", "smoke-unit", "--max-steps", "1"])
    assert started.returncode == 1, started.stderr
    [batch] = list(runs.iterdir())

    resumed = run_with(python3, ["--resume", batch.name])
    assert "Environment differs" not in resumed.stdout + resumed.stderr
    assert resumed.returncode == 1, resumed.stderr
    assert json.loads((batch / "resume-1.json").read_text())["changed_from_batch"] == []
