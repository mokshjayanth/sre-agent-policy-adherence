"""Registered reporting items not yet computed: by split, avg@2/best@2, attempts vs executed changes,
per-model success/CuP, app breakdown, token totals.
    python analysis/reporting.py
"""
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading import report                      # noqa: E402
from grading.episode import load                # noqa: E402
from grading.grade import app_by_problem        # noqa: E402
from grading.rules import is_change             # noqa: E402

table = {r["problem_id"]: r for r in csv.DictReader(open(REPO / "configs/problem-table.csv"))}
selection = list(csv.DictReader(open(REPO / "results/fresh-2026-10/selection.csv")))
eps, cells = report.collect(sorted({REPO / "runs" / s["batch_id"] for s in selection}))
report.choose_attempts(eps, cells)
eps = [e for e in eps if e["used"]]
cells = [c for c in cells if c["used"]]
for x in eps + cells:
    x["split"] = table[x["problem_id"]]["aoi_split"]
    x["app"] = table[x["problem_id"]]["app"]
PROH = ("R1", "R2", "R5", "R6", "R9")
PROC = ("R3", "R7", "R8")


def fam(cs):
    out = []
    for c in cs:
        if c["rule"] in PROC:
            out.append({**c, "rule": "procedures"})
        elif c["rule"] in PROH:
            out.append({**c, "rule": "prohibitions"})
    return out


print("By split (registered: results reported by split) — family rates, no policy vs policy:")
for r in report.rates(fam([c for c in cells if c["variant"] in ("nopolicy", "policy")]), ("split", "variant", "rule")):
    print(f"  {r['split']:5} {r['variant']:9} {r['rule']:12} {100 * r['rate']:5.1f}% [{100 * r['ci_lo']:4.1f}, {100 * r['ci_hi']:4.1f}]  "
          f"({r['violations']}/{r['opportunities']})")
print("  H1 by split (policy arm, per model): procedures > prohibitions?")
h1s = defaultdict(dict)
for r in report.rates(fam([c for c in cells if c["variant"] == "policy"]), ("split", "model", "rule")):
    h1s[(r["split"], r["model"])][r["rule"]] = r["rate"]
for split in ("train", "test"):
    held = [m for (s, m), v in h1s.items() if s == split and v.get("procedures", 0) > v.get("prohibitions", 0)]
    allm = [m for (s, m) in h1s if s == split]
    print(f"    {split}: holds in {len(held)} of {len(allm)} models")
print("  Pressure vs policy by split (procedures):")
for r in report.differences(fam(cells), ("split", "rule")):
    if r["rule"] == "procedures" and r["variant"] in ("budget", "scored", "budgetonce", "budgetmedian", "combined"):
        print(f"    {r['split']:5} {r['variant']:12} diff {100 * r['difference']:+5.1f} [{100 * r['ci_lo']:+5.1f}, {100 * r['ci_hi']:+5.1f}]")
print("  Success by split and arm (mitigation / diagnosis):")
for split in ("train", "test"):
    row = []
    for arm in ("nopolicy", "policy", "budget", "scored"):
        for task in ("mitigation", "diagnosis"):
            sub = [e for e in eps if e["split"] == split and e["variant"] == arm and e["task"] == task]
            row.append(f"{arm[:4]}-{task[:3]} {sum(e['success'] for e in sub)}/{len(sub)}")
    print(f"    {split}: " + "  ".join(row))

print("\navg@2 / best@2 success (main arms; per problem x model over the two rounds):")
for arm in ("nopolicy", "policy", "budget", "scored"):
    for task in ("mitigation", "diagnosis"):
        pairs = defaultdict(list)
        for e in eps:
            if e["variant"] == arm and e["task"] == task:
                pairs[(e["model"], e["problem_id"])].append(e["success"])
        assert all(len(v) == 2 for v in pairs.values()), arm
        avg = sum(sum(v) / 2 for v in pairs.values()) / len(pairs)
        best = sum(any(v) for v in pairs.values()) / len(pairs)
        both = sum(all(v) for v in pairs.values()) / len(pairs)
        print(f"  {arm:9} {task:10} avg@2 {100 * avg:5.1f}%  best@2 {100 * best:5.1f}%  both runs {100 * both:5.1f}%  (n={len(pairs)} pairs)")

print("\nAttempted vs executed changes (mitigation, by arm):")
apps = app_by_problem()
att = defaultdict(lambda: [0, 0])
for s in selection:
    if s["task"] != "mitigation":
        continue
    ep = load(REPO / "runs" / s["batch_id"] / "problems" / s["problem_id"] / "trajectory.json", apps)
    for a in ep.actions:
        n = sum(1 for c in a.commands if is_change(c))
        att[s["arm"]][0] += n
        att[s["arm"]][1] += n if a.ran else 0
for arm, (a, r) in att.items():
    print(f"  {arm:12} attempted {a:4}  executed {r:4}  ({100 * r / a:.0f}%)  per episode {a / sum(1 for s in selection if s['arm'] == arm and s['task'] == 'mitigation'):.1f}")

print("\nPer model under the policy (success / CuP, mitigation and diagnosis):")
for m in sorted({e["model"] for e in eps}):
    out = []
    for task in ("mitigation", "diagnosis"):
        sub = [e for e in eps if e["model"] == m and e["variant"] == "policy" and e["task"] == task]
        out.append(f"{task[:4]} succ {sum(e['success'] for e in sub)}/{len(sub)} CuP {sum(e['cup'] for e in sub)}/{len(sub)}")
    print(f"  {m:16} " + "  |  ".join(out))

print("\nBy app (policy arm, family rates):")
for r in report.rates(fam([c for c in cells if c["variant"] == "policy"]), ("app", "rule")):
    print(f"  {r['app']:17} {r['rule']:12} {100 * r['rate']:5.1f}%  ({r['violations']}/{r['opportunities']})")

tok = Counter()
for s in selection:
    t = json.loads((REPO / "runs" / s["batch_id"] / "problems" / s["problem_id"] / "trajectory.json").read_text())
    for c in (t.get("agent_record") or {}).get("calls") or []:
        u = c.get("usage") or {}
        tok["prompt"] += u.get("prompt_tokens") or 0
        tok["completion"] += u.get("completion_tokens") or 0
        tok["calls"] += 1
print(f"\nTokens over the 1,056 episodes: {tok['calls']} model calls, {tok['prompt'] / 1e6:.1f}M prompt, "
      f"{tok['completion'] / 1e6:.2f}M completion; per episode {tok['prompt'] / 1056 / 1e3:.0f}K prompt")
print("Actions:", sum(e["steps"] for e in eps), "| episodes per model:", Counter(e["model"] for e in eps))
