"""Per-run provenance manifest.

Records the things the commit-hash pin in CLAUDE.md doesn't cover: this
repo's own code state, whether the harness working tree is clean, local
config.yml (gitignored upstream, changes what gets scored via
qualitative_eval), the Python interpreter actually running, version pins
applied from outside the harness, the cluster the harness targets, and the
image digests actually running in it during the run. Not a gate — just a
debugging record, per notes/harness-pinning-hardening.md.

Cluster facts come from AIOpsLab's own KubeCtl client rather than a separate
kubectl call, so they describe exactly the cluster the harness talks to.
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


def _git_status(repo_dir: Path) -> list[str] | None:
    """`git status --porcelain` lines; an empty list means a clean tree."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_dir), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [line for line in out.splitlines() if line]


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


def _harness_kubectl():
    """AIOpsLab's KubeCtl, which selects the kube context the harness itself uses."""
    if str(AIOPSLAB_ROOT) not in sys.path:
        sys.path.insert(0, str(AIOPSLAB_ROOT))
    from aiopslab.service.kubectl import KubeCtl

    return KubeCtl()


def _harness_api_server() -> str | None:
    try:
        return _harness_kubectl().core_v1_api.api_client.configuration.host
    except Exception:
        return None


def collect_static_manifest(pins: dict | None = None, run: dict | None = None) -> dict:
    """Info known before a problem is deployed.

    `pins` are version pins applied from outside the harness (e.g. the OTel
    chart version); `run` is whatever the caller wants recorded about the
    invocation: arguments, agent, problem selection.
    """
    config_path = AIOPSLAB_ROOT / "aiopslab" / "config.yml"
    config = yaml.safe_load(config_path.read_text()) if config_path.exists() else None

    try:
        pip_freeze = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, check=True,
        ).stdout.strip().splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pip_freeze = None

    repo_status = _git_status(REPO_ROOT)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "commit": _git_rev(REPO_ROOT),
            "dirty": bool(repo_status) if repo_status is not None else None,
            "status": repo_status,
        },
        "harness": {
            "aiopslab_commit": _git_rev(AIOPSLAB_ROOT),
            "aiopslab_applications_commit": _git_rev(AIOPSLAB_ROOT / "aiopslab-applications"),
            "status": _git_status(AIOPSLAB_ROOT),
            "config_yml": config,
        },
        "cluster": {
            "kind_node_image": _kind_node_image_digest(),
            # The API server the harness's KubeCtl is configured for. A rebuilt kind
            # cluster gets a new host port, so this also changes when the cluster does.
            "api_server": _harness_api_server(),
        },
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "poetry_lock_sha256": _sha256_file(AIOPSLAB_ROOT / "poetry.lock"),
            "pip_freeze": pip_freeze,
        },
        "pins": pins or {},
        "run": run or {},
    }


def collect_cluster_images() -> dict:
    """Images of every pod in the cluster, grouped by namespace then pod.

    `image` is the reference the pod spec asked for, often a floating tag such
    as `hashicorp/consul:latest`; `image_id` is the digest the container
    runtime actually started, and is the only field that shows whether such a
    tag moved between runs. `image_id` is None for containers that haven't
    started yet. Call after deploy, before teardown.
    """
    try:
        pods = _harness_kubectl().core_v1_api.list_pod_for_all_namespaces().items
    except Exception:
        return {}

    images: dict = {}
    for pod in pods:
        status = pod.status
        statuses = ((status.init_container_statuses or []) + (status.container_statuses or [])) if status else []
        started = {s.name: s.image_id for s in statuses}
        containers = (pod.spec.init_containers or []) + pod.spec.containers
        images.setdefault(pod.metadata.namespace, {})[pod.metadata.name] = [
            {"container": c.name, "image": c.image, "image_id": started.get(c.name) or None}
            for c in containers
        ]
    return images
