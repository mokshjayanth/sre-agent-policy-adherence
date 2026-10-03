"""Readable dumps of the hand-check sample: every action with its outcome, then the grader's verdicts."""
import csv, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading.episode import load
from grading.grade import app_by_problem
from grading.rules import grade, opportunities
apps = app_by_problem()
out = REPO / "results/fresh-2026-10/hand-check"
for i, row in enumerate(csv.DictReader(open(REPO / "results/fresh-2026-10/analysis/hand-check-sample.csv")), 1):
    ep = load(REPO / "runs" / row["batch"] / "problems" / row["problem_id"] / "trajectory.json", apps)
    lines = [f"# {i:02d} {row['batch'].split('_',1)[1]} / {row['problem_id']}",
             f"task={ep.task} namespace={ep.namespace} end={ep.termination_reason} success={ep.success} steps={len(ep.actions)}", ""]
    for a in ep.actions:
        arg = " ".join(str(x) for x in a.args)
        lines.append(f"[{a.step:2}] {a.api}({arg[:400]})  -> {a.outcome}")
        lines.append(f"      reply: {(a.reply or '').strip()[:220].replace(chr(10), ' | ')}")
    lines += ["", "GRADER violations:"]
    for v in grade(ep):
        lines.append(f"  {v.rule} step {v.step}: {v.command[:200]}")
    lines.append("opportunities: " + str({k: n for k, n in opportunities(ep).items() if n}))
    (out / f"{i:02d}.txt").write_text("\n".join(lines) + "\n")
print("written", i)
