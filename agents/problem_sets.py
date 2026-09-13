"""Which AIOpsLab problems a batch runs.

Problems come from an explicit ID list, a file of IDs, or a task-type filter
over the registry. Problems known to be broken at the pinned harness and chart
versions are dropped by default, with the reason recorded, so a batch doesn't
spend four minutes of setup on a run that can only fail.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
sys.path.insert(0, str(AIOPSLAB_ROOT))

from aiopslab.orchestrator.problems.registry import ProblemRegistry  # noqa: E402

TASK_TYPES = ("detection", "localization", "analysis", "mitigation")

_FLOOD_REASON = (
    "feature flag loadGeneratorFloodHomepage is absent from opentelemetry-demo charts "
    "0.41.0 and 0.41.1 (checked 2026-09-13), so OtelFaultInjector raises ValueError at injection"
)

EXCLUDED = {
    "astronomy_shop_loadgenerator_flood_homepage-detection-1": _FLOOD_REASON,
    "astronomy_shop_loadgenerator_flood_homepage-localization-1": _FLOOD_REASON,
}


def task_type(problem_id: str) -> str:
    """Task type encoded in a problem ID, matched by substring as the registry does."""
    return next((t for t in TASK_TYPES if t in problem_id), "other")


def select_problems(
    ids: list[str] | None = None,
    id_file: str | Path | None = None,
    task: str | None = None,
    include_excluded: bool = False,
) -> tuple[list[str], dict[str, str]]:
    """Resolve a problem selection to (problem IDs to run, {skipped ID: reason}).

    Precedence: `ids`, then `id_file` (one ID per line, `#` comments allowed),
    then `task`. With none given, every registered problem is selected. Note
    that `task="detection"` also matches the three `noop_detection_*` controls.
    """
    registry = ProblemRegistry()
    if ids:
        chosen = list(ids)
    elif id_file:
        lines = Path(id_file).read_text().splitlines()
        chosen = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    else:
        chosen = registry.get_problem_ids(task)
    chosen = list(dict.fromkeys(chosen))

    known = set(registry.get_problem_ids())
    unknown = [p for p in chosen if p not in known]
    if unknown:
        raise ValueError(f"Unknown problem IDs: {unknown}")

    skipped = {} if include_excluded else {p: EXCLUDED[p] for p in chosen if p in EXCLUDED}
    return [p for p in chosen if p not in skipped], skipped
