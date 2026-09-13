"""Per-run provenance manifest.

Records the things the commit-hash pin in CLAUDE.md doesn't cover: local
config.yml (gitignored upstream, changes what gets scored via
qualitative_eval), the Python interpreter actually running, and the
image IDs actually deployed for this run's namespace. Not a gate — just a
debugging record, per notes/harness-pinning-hardening.md.
"""

import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_rev(repo_dir: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _kind_node_image_digest() -> str | None:
    try:
        out = subprocess.run(
            ["docker", "inspect", "kind-control-plane", "--format", "{{.Config.Image}}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        digest = subprocess.run(
            ["docker", "image", "inspect", out, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return digest or out
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        return None


def collect_static_manifest() -> dict:
    """Info known before a problem is deployed: harness, config, interpreter."""
    config_path = AIOPSLAB_ROOT / "aiopslab" / "config.yml"
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else None

    try:
        pip_freeze = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pip_freeze = None

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "harness": {
            "aiopslab_commit": _git_rev(AIOPSLAB_ROOT),
            "aiopslab_applications_commit": _git_rev(AIOPSLAB_ROOT / "aiopslab-applications"),
            "config_yml": config,
        },
        "cluster": {
            "kind_node_image": _kind_node_image_digest(),
        },
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "poetry_lock_sha256": _sha256_file(AIOPSLAB_ROOT / "poetry.lock"),
            "pip_freeze": pip_freeze,
        },
    }


def collect_pod_images(namespace: str) -> dict:
    """Image refs actually running in `namespace`. Call after deploy, before teardown."""
    try:
        out = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", namespace,
                "-o", "jsonpath={range .items[*]}{.metadata.name}{\"=\"}"
                      "{range .spec.containers[*]}{.image}{\",\"}{end}{\"\\n\"}{end}",
            ],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

    images = {}
    for line in out.splitlines():
        if "=" not in line:
            continue
        pod, imgs = line.split("=", 1)
        images[pod] = [i for i in imgs.split(",") if i]
    return images
