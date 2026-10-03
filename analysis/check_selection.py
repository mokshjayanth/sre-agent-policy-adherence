"""Prove the analysis grades exactly the right episodes, before any grading.

The selection is built from the three plan files, then checked against the catalogue, the run settings
each batch recorded, the attempt folders on disk and the verifier's per-episode output. Writes the
selection to results/fresh-2026-10/selection.csv. Prints FAIL lines and exits 1 on any mismatch.
    python analysis/check_selection.py
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading.report import condition_parts       # noqa: E402

PLANS = {"stage1": "a2fc77315ece", "stage2a": "88713f11925d", "stage2b": "42b9fa5f39b0"}
PIN = "ddf7e4061968"
fails = []


def check(ok: bool, message: str) -> None:
    if not ok:
        fails.append(message)


# 1. The plan: every condition, with its expected labels and problems.
planned = {}
for stage, commit in PLANS.items():
    for item in json.loads((REPO / f"configs/study-plan-fresh-{stage}.json").read_text())["items"]:
        check(item["condition"] not in planned, f"{item['condition']} planned twice")
        planned[item["condition"]] = {**item, "stage": stage, "commit": commit}
check(len(planned) == 84, f"{len(planned)} planned conditions, not 84")

# 2. The catalogue: exactly one batch per planned condition, and no other main6/ladder6 batch.
catalogue = list(csv.DictReader(open(REPO / "results/fresh-2026-10/batches-all.csv")))
by_condition = {}
for row in catalogue:
    by_condition.setdefault(row["condition"], []).append(row)
for condition in planned:
    check(len(by_condition.get(condition, [])) == 1, f"{condition}: {len(by_condition.get(condition, []))} batches")
extra = [r["condition"] for r in catalogue if r["study"] in ("main6", "ladder6") and r["condition"] not in planned]
check(not extra, f"unplanned main6/ladder6 batches: {extra}")

# 3. Each batch's own record against the plan.
verified = {}
for stage in PLANS:
    for row in csv.DictReader(open(REPO / f"results/fresh-2026-10/verification/verify-{stage}.csv")):
        verified[(row["batch_id"], row["problem_id"])] = row["ok"] == "True"

selection, failed_attempts = [], []
for condition, item in planned.items():
    row = by_condition[condition][0]
    batch = REPO / "runs" / row["batch_id"]
    parts = condition_parts(condition)
    expect_task = item.get("task") or ""
    check((row["study"], row["model"], row["arm"], int(row["round"]), row["task"]) ==
          (parts.study, parts.model, parts.arm, parts.round, parts.task), f"{condition}: catalogue labels differ")
    check(parts.arm == item["arm"] and parts.round == item["round"], f"{condition}: arm/round differ from plan")
    check(row["repo_commit"] == item["commit"] and row["repo_dirty"] == "False",
          f"{condition}: commit {row['repo_commit']} dirty={row['repo_dirty']}, plan {item['commit']}")
    check(row["harness_commit"] == PIN, f"{condition}: harness {row['harness_commit']}")
    if parts.arm == "budget":
        # The main budget sentence is built into the agent, not a file; its hashes must be the registered ones.
        check(row["text_status"] == "budget:inline; budget:inline" and row["status"] == "inline text"
              and "budget:inline@983915b27a32" in row["texts"] and "budget:inline@e725d591b074" in row["texts"],
              f"{condition}: budget texts {row['texts'][:120]}")
    else:
        check(row["text_status"] == "matches" and row["status"] == "current", f"{condition}: texts {row['text_status']}")
    recorded = json.loads((batch / "batch.json").read_text())["run"]
    check(recorded["problems"] == item["problems"], f"{condition}: recorded problems differ from plan")
    # 4. Attempt folders: the latest attempt of every planned problem, and nothing else counted.
    latest = sorted(p.parent.name for p in batch.glob("problems/*/trajectory.json") if ".failed-" not in p.parent.name)
    failed_attempts += [f"{row['batch_id']}/{p.parent.name}" for p in batch.glob("problems/*.failed-*/trajectory.json")]
    check(latest == sorted(item["problems"]), f"{condition}: latest attempts {len(latest)} vs plan {len(item['problems'])}")
    for problem in item["problems"]:
        trajectory = json.loads((batch / "problems" / problem / "trajectory.json").read_text())
        check(trajectory.get("condition") == condition and trajectory.get("problem_id") == problem,
              f"{condition}/{problem}: trajectory labelled {trajectory.get('condition')}/{trajectory.get('problem_id')}")
        # 5. The verifier certified exactly this episode.
        check(verified.get((row["batch_id"], problem)) is True, f"{condition}/{problem}: not certified by verify_plan")
        selection.append({"stage": item["stage"], "study": parts.study, "model": parts.model, "arm": parts.arm,
                          "round": parts.round, "task_batch": parts.task, "condition": condition,
                          "batch_id": row["batch_id"], "problem_id": problem,
                          "task": "mitigation" if "-mitigation-" in problem else "diagnosis"})

check(len(verified) == len(selection) == 1056, f"verifier rows {len(verified)}, selection {len(selection)}")
check({(s["batch_id"], s["problem_id"]) for s in selection} == set(verified), "selection != verifier's episodes")

# 6. The cells the analysis expects.
main = Counter((s["model"], s["arm"], s["round"]) for s in selection if s["study"] == "main6")
ladder = Counter((s["model"], s["arm"], s["task"]) for s in selection if s["study"] == "ladder6")
check(len(main) == 6 * 4 * 2 and set(main.values()) == {16}, f"main cells: {len(main)}, sizes {set(main.values())}")
check(len(ladder) == 6 * 3 * 2 and set(ladder.values()) == {8}, f"ladder cells: {len(ladder)}, sizes {set(ladder.values())}")
tasks = Counter((s["study"], s["task"]) for s in selection)
check(all(tasks[(st, t)] == n for st, t, n in (("main6", "mitigation", 384), ("main6", "diagnosis", 384),
                                               ("ladder6", "mitigation", 144), ("ladder6", "diagnosis", 144))),
      f"task split {dict(tasks)}")
check(all(s["task"] == s["task_batch"] for s in selection if s["study"] == "ladder6"), "ladder task mismatch")

out = REPO / "results/fresh-2026-10/selection.csv"
with out.open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(selection[0]))
    writer.writeheader()
    writer.writerows(selection)
print(f"planned conditions {len(planned)}; selected episodes {len(selection)} "
      f"(main6 {sum(main.values())}, ladder6 {sum(ladder.values())}); main cells {len(main)}, ladder cells {len(ladder)}")
print(f"excluded: {len(catalogue) - 84} other batches ({dict(Counter(r['study'] for r in catalogue if r['condition'] not in planned))})")
print(f"set-aside failed attempts, not graded as episodes: {failed_attempts}")
print("models:", sorted({s['model'] for s in selection}), "| arms:", sorted({s['arm'] for s in selection}))
for message in fails:
    print("FAIL", message)
print("SELECTION OK" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
