"""Make the repo root and the harness importable, in the same order runner/run_batch.py uses, and
give the tests a stub kubeconfig.

Tests import `runner` and `agents` as packages; agents import harness modules
such as `clients.utils.templates`, which the runner makes importable at run time.
"""

import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
for path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# The harness loads a kubeconfig when its modules are imported, so without one no test can even be
# collected. Point every test at a stub whose `kind-kind` context names an address nothing listens
# on: the suite then needs no cluster and can never reach a real one.
_STUB_KUBECONFIG = Path(tempfile.mkdtemp(prefix="tests-kube-")) / "config"
_STUB_KUBECONFIG.write_text("""apiVersion: v1
kind: Config
current-context: kind-kind
clusters:
- name: kind-kind
  cluster: {server: "https://127.0.0.1:9"}
contexts:
- name: kind-kind
  context: {cluster: kind-kind, user: kind-kind}
users:
- name: kind-kind
  user: {token: stub}
""")
os.environ["KUBECONFIG"] = str(_STUB_KUBECONFIG)

# aiopslab/observer/__init__.py loads its own path (~/.kube/config) at import, so the variable alone
# doesn't reach it: every load_kube_config reads the stub instead, whatever file it names.
import kubernetes.config  # noqa: E402
import kubernetes.config.kube_config  # noqa: E402

_load_kube_config = kubernetes.config.kube_config.load_kube_config


def _load_stub(config_file=None, context=None, **kwargs):
    return _load_kube_config(config_file=str(_STUB_KUBECONFIG), context="kind-kind", **kwargs)


kubernetes.config.load_kube_config = kubernetes.config.kube_config.load_kube_config = _load_stub
