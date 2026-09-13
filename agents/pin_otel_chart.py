"""Pins the OpenTelemetry demo (Astronomy Shop) Helm chart version.

third_party/aiopslab installs it unpinned: AstronomyShop.deploy() calls
Helm.install(**self.helm_configs) against the remote `open-telemetry` repo
with no "version" key, so it floats onto whatever's newest at install time.
That chart releases roughly monthly (13 times in 2026 as of this writing) —
the one input in the harness that will almost certainly move mid-study. See
notes/2026-09-13-harness-pin-coverage.md.

Fix lives here, not in third_party/aiopslab: monkeypatch
ProblemRegistry.get_problem_instance to set helm_configs["version"] on any
AstronomyShop-backed problem, which Helm.install already knows how to turn
into `--version X`. Only relevant once Astronomy Shop problems are in scope
(not used by Day 1's misconfig_app_hotel_res-detection-1).

Usage: import and call apply_pin() once before creating an Orchestrator.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
sys.path.insert(0, str(AIOPSLAB_ROOT))

from aiopslab.orchestrator.problems.registry import ProblemRegistry  # noqa: E402
from aiopslab.service.apps.astronomy_shop import AstronomyShop  # noqa: E402

# Latest opentelemetry-demo chart release as of 2026-09-13 (0.41.1, published
# 2026-09-11). Re-verify and bump deliberately, never silently.
PINNED_OTEL_CHART_VERSION = "0.41.1"

_ORIGINAL_GET_PROBLEM_INSTANCE = ProblemRegistry.get_problem_instance
_applied = False


def _get_problem_instance_pinned(self, problem_id: str):
    prob = _ORIGINAL_GET_PROBLEM_INSTANCE(self, problem_id)
    if isinstance(getattr(prob, "app", None), AstronomyShop):
        prob.app.helm_configs["version"] = PINNED_OTEL_CHART_VERSION
    return prob


def apply_pin():
    """Idempotently monkeypatch ProblemRegistry to pin the OTel chart version."""
    global _applied
    if not _applied:
        ProblemRegistry.get_problem_instance = _get_problem_instance_pinned
        _applied = True
