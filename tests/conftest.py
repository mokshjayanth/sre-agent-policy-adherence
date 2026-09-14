"""Make the repo root and the harness importable, in the same order runner/run_batch.py uses.

Tests import `runner` and `agents` as packages; agents import harness modules
such as `clients.utils.templates`, which the runner makes importable at run time.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
for path in (AIOPSLAB_ROOT, REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
