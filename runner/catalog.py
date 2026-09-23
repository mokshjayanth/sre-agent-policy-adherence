"""One row per batch: which study, arm and round it belongs to, and whether its prompts still stand.

    python -m runner.catalog --out results/main-2026-09/batches.csv

Built from each batch's own `batch.json` and `index.jsonl`, never from a name or from memory. The
arm is recoverable from content as well as from the label: `texts` lists every instructed text with
its SHA-256, and `text_status` says whether those files still exist unchanged in the working tree.
A batch whose texts have since been replaced reads `superseded`, which is how an arm is retired —
nothing in `runs/` is ever moved or renamed (CLAUDE.md). Per-run provenance lives in
runner/manifest.py; this module only reads back what that one recorded.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from grading.report import condition_parts

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "runs"
FIELDS = ["batch_id", "started_utc", "study", "model", "arm", "task", "round", "condition", "max_steps",
          "step_budget", "countdown", "problems", "attempts", "ok", "failed", "resumes", "texts", "text_status",
          "status", "note", "repo_commit", "repo_dirty", "harness_commit"]
# Arms retired by a later decision, which no hash can tell you about. Keyed by (study, arm, round).
RETIRED: dict[tuple[str, str, int], str] = {}


def _sha256(path: Path) -> str:
    """The agent hashes the stripped text and keeps 12 hex characters; match that exactly."""
    return hashlib.sha256(path.read_text().strip().encode()).hexdigest()[:12]


def text_status(texts: list[dict]) -> str:
    """Do the instructed texts this batch used still exist, unchanged, in the working tree?"""
    notes = []
    for text in texts:
        name = text.get("file")
        if not name:
            notes.append(f"{text['role']}:inline")
            continue
        path = REPO_ROOT / name
        if not path.exists():
            notes.append(f"{name}:gone")
        elif _sha256(path) != text["sha256"][:12]:
            notes.append(f"{name}:changed")
    return "; ".join(notes) if notes else "matches"


def counts(batch: Path) -> dict:
    """Episodes as the batch itself recorded them."""
    index = batch / "index.jsonl"
    records = [json.loads(line) for line in index.read_text().splitlines() if line.strip()] \
        if index.exists() else []
    ok = {r["problem_id"] for r in records if r.get("status") == "ok"}
    attempted = {r["problem_id"] for r in records if r.get("problem_id")}
    problems = {p.name.split(".failed-")[0] for p in (batch / "problems").iterdir()} \
        if (batch / "problems").is_dir() else set()
    return {"problems": len(problems | attempted), "attempts": len(records), "ok": len(ok),
            "failed": len(attempted - ok), "resumes": len(list(batch.glob("resume-*.json")))}


def row(batch: Path) -> dict:
    data = json.loads((batch / "batch.json").read_text())
    run = data["run"]
    described = run.get("agent_description") or {}
    texts = described.get("instructed_texts") or []
    study, model, arm, task, round_ = condition_parts(run["condition"])
    status = text_status(texts)
    state = "current" if status == "matches" else "inline text" if "inline" in status and \
        "changed" not in status and "gone" not in status else "superseded"
    return {"batch_id": batch.name, "started_utc": data.get("timestamp_utc", ""), "study": study,
            "model": model or described.get("model", ""), "arm": arm, "task": task, "round": round_,
            "condition": run["condition"], "max_steps": run.get("max_steps", ""),
            "step_budget": described.get("step_budget") or "",
            "countdown": described.get("budget_countdown", ""),
            "texts": "; ".join(f"{t['role']}:{t.get('file') or 'inline'}@{t['sha256'][:12]}" for t in texts),
            "text_status": status, "status": state,
            "note": RETIRED.get((study, arm, round_), ""),
            "repo_commit": data.get("repo", {}).get("commit", "")[:12],
            "repo_dirty": data.get("repo", {}).get("dirty", ""),
            "harness_commit": data.get("harness", {}).get("aiopslab_commit", "")[:12],
            **counts(batch)}


def build(runs_root: Path = RUNS_ROOT) -> list[dict]:
    batches = [b for b in sorted(runs_root.iterdir())
               if b.is_dir() and not b.name.startswith("_") and (b / "batch.json").exists()]
    return [row(b) for b in batches]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=Path, default=RUNS_ROOT)
    parser.add_argument("--study", help="keep only batches of this study, e.g. main or ladder")
    args = parser.parse_args(argv)
    rows = [r for r in build(args.runs) if not args.study or r["study"] == args.study]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)
    states = Counter(r["status"] for r in rows)
    print(json.dumps({"batches": len(rows), **states, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
