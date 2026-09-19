"""Grade recorded episodes against policy v3 and write one row per violation.

    python -m grading.grade runs/<batch_id> [more batches ...] --out grades.csv

Reads only what the harness recorded; it never touches a cluster. Rows carry the batch, condition,
problem, step, rule and reason, so they can be counted per condition or read next to the episode.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "third_party" / "aiopslab", REPO_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from grading.episode import load  # noqa: E402
from grading.rules import grade  # noqa: E402

FIELDS = ["batch", "condition", "problem_id", "task", "episode_steps", "step", "rule", "outcome",
          "reading", "command", "reason"]


def app_by_problem() -> dict[str, str]:
    with open(REPO_ROOT / "configs" / "problem-table.csv") as handle:
        return {row["problem_id"]: row["app"] for row in csv.DictReader(handle)}


def grade_batches(batches: list[Path]) -> tuple[list[dict], list[dict]]:
    apps, rows, episodes = app_by_problem(), [], []
    for batch in batches:
        for trajectory in sorted(batch.glob("problems/*/trajectory.json")):
            episode = load(trajectory, apps)
            violations = grade(episode)
            episodes.append({"batch": batch.name, "condition": episode.condition,
                             "problem_id": episode.problem_id, "task": episode.task,
                             "steps": len(episode.actions), "parse_failures": episode.parse_failures,
                             "termination_reason": episode.termination_reason, "success": episode.success,
                             "violations": len(violations)})
            for violation in violations:
                rows.append({"batch": batch.name, "condition": episode.condition,
                             "problem_id": episode.problem_id, "task": episode.task,
                             "episode_steps": len(episode.actions), **violation.as_row()})
    return rows, episodes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batches", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, help="write violation rows here as CSV")
    parser.add_argument("--episodes-out", type=Path, help="write one row per episode here as CSV")
    args = parser.parse_args(argv)
    rows, episodes = grade_batches(args.batches)
    if args.out:
        with args.out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    if args.episodes_out:
        with args.episodes_out.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(episodes[0]))
            writer.writeheader()
            writer.writerows(episodes)
    print(json.dumps({"episodes": len(episodes), "violations": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
