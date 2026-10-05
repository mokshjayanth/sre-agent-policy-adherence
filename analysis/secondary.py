"""The rest of the registered analysis (H4-H6, the dose-response) and the paper's tables.
    python analysis/secondary.py   -> results/fresh-2026-10/analysis/*.csv and a printed summary
"""
import csv
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading import report                      # noqa: E402
from grading.episode import load                # noqa: E402
from grading.grade import app_by_problem        # noqa: E402
from grading.rules import grade, opportunities, is_change   # noqa: E402

OUT = REPO / "results/fresh-2026-10/analysis"
ARMS = ["nopolicy", "policy", "budget", "scored", "budgetonce", "budgetmedian", "combined"]
apps = app_by_problem()
selection = list(csv.DictReader(open(REPO / "results/fresh-2026-10/selection.csv")))
rows = []          # one per episode, with what the later analyses need
for s in selection:
    path = REPO / "runs" / s["batch_id"] / "problems" / s["problem_id"] / "trajectory.json"
    ep = load(path, apps)
    raw = json.loads(path.read_text())
    calls = raw.get("agent_record", {}).get("calls") or []
    violations = grade(ep)
    rows.append({**s, "episode": ep, "violations": violations, "calls": calls,
                 "success": bool(ep.success), "termination": ep.termination_reason, "steps": len(ep.actions)})
assert len(rows) == 1056


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "  n/a"


# Table III: per arm, the rules that carry the story, paired difference to policy, success and CuP by task.
eps, cells = report.collect(sorted({REPO / "runs" / s["batch_id"] for s in selection}))
report.choose_attempts(eps, cells)
eps = [e for e in eps if e["used"]]
cells = [c for c in cells if c["used"]]
diffs = {(r["rule"], r["variant"]): r for r in report.differences(cells, ("rule",))}
rates = {(r["variant"], r["rule"]): r for r in report.rates(cells, ("variant", "rule"))}
table = []
for arm in ARMS:
    row = {"arm": arm}
    for rule in ("R2", "R3", "R6", "R7", "R8", "R9"):
        r = rates[(arm, rule)]
        row[rule] = round(100 * r["rate"], 1)
        if arm != "policy":
            d = diffs[(rule, arm)]
            row[f"{rule}_diff"] = f"{100 * d['difference']:+.1f} [{100 * d['ci_lo']:+.1f},{100 * d['ci_hi']:+.1f}]"
    for task in ("mitigation", "diagnosis"):
        sub = [e for e in eps if e["variant"] == arm and e["task"] == task]
        row[f"success_{task}"] = round(100 * sum(e["success"] for e in sub) / len(sub), 1)
        row[f"cup_{task}"] = round(100 * sum(e["cup"] for e in sub) / len(sub), 1)
        row[f"n_{task}"] = len(sub)
    table.append(row)
report.write(OUT / "table3-arms.csv", table)
print("TABLE III (rate %; diff vs policy [95% CI]; success/CuP by task)")
for r in table:
    print(f"  {r['arm']:12} R3 {r['R3']:5} R7 {r['R7']:5} R8 {r['R8']:5} R2 {r['R2']:5} R6 {r['R6']:5} R9 {r['R9']:5} | "
          f"succ mit {r['success_mitigation']:5} diag {r['success_diagnosis']:5} | CuP mit {r['cup_mitigation']:5} diag {r['cup_diagnosis']:5}")
    if r["arm"] != "policy":
        print("               " + "  ".join(f"{k}:{r[k + '_diff']}" for k in ("R3", "R7", "R8", "R2", "R6", "R9")))

# H4: per model, violations whose own Thought cites a rule or the policy (policy-bearing arms).
print("\nH4 recognition (violations whose Thought cites a rule), policy-bearing arms:")
h4 = defaultdict(lambda: [0, 0])
for e in eps:
    if e["variant"] != "nopolicy":
        h4[e["model"]][0] += e["recognised"]
        h4[e["model"]][1] += e["violations"]
for m, (rec, vio) in sorted(h4.items()):
    print(f"  {m:16} {rec}/{vio} ({pct(rec, vio)})")
print("  -> H4", "holds (every model shows some)" if all(r > 0 for r, _ in h4.values()) else "REFUTED for some model")
report.write(OUT / "h4-recognition.csv", [{"model": m, "recognised": r, "violations": v} for m, (r, v) in sorted(h4.items())])

# H5: within model x arm x task, do violating episodes succeed more than non-violating ones?
print("\nH5 violations don't pay (success, violating vs not, within model x arm x task):")
cells5, more, less, tie, pooled = [], 0, 0, 0, defaultdict(lambda: [0, 0, 0, 0])
by = defaultdict(list)
for e in eps:
    by[(e["model"], e["variant"], e["task"])].append(e)
for key, group in sorted(by.items()):
    v = [e for e in group if e["violations"]]
    n = [e for e in group if not e["violations"]]
    if not v or not n:
        continue
    sv, sn = sum(e["success"] for e in v) / len(v), sum(e["success"] for e in n) / len(n)
    more += sv > sn
    less += sv < sn
    tie += sv == sn
    p = pooled[key[2]]
    p[0] += sum(e["success"] for e in v); p[1] += len(v); p[2] += sum(e["success"] for e in n); p[3] += len(n)
    cells5.append({"model": key[0], "arm": key[1], "task": key[2], "violating": len(v), "success_violating": sv,
                   "clean": len(n), "success_clean": sn})
report.write(OUT / "h5-cells.csv", cells5)
print(f"  cells with both kinds: {len(cells5)}; violating succeed more in {more}, less in {less}, equal in {tie}")
for task, (sv, nv, sn, nn) in pooled.items():
    print(f"  {task:10} violating {sv}/{nv} ({pct(sv, nv)})  clean {sn}/{nn} ({pct(sn, nn)})")

# H6: prompt size (tokens) at the call that produced a violating change vs a compliant one, per rule.
print("\nH6 context at the change (prompt tokens of the call that produced the action), mitigation:")
ctx = defaultdict(lambda: {"violating": [], "compliant": []})
for r in rows:
    ep = r["episode"]
    if ep.task != "mitigation" or not r["calls"]:
        continue
    tokens = [c.get("usage", {}).get("prompt_tokens") for c in r["calls"]]
    bad = defaultdict(set)
    for v in r["violations"]:
        bad[v.rule].add(v.step)
    for a in ep.actions:
        # the call that produced this action is the action's harness turn (parse failures included)
        if not any(is_change(c) for c in a.commands) or a.turn > len(tokens) or tokens[a.turn - 1] is None:
            continue
        for rule in ("R3", "R7", "R8"):
            ctx[rule]["violating" if a.step in bad[rule] else "compliant"].append(tokens[a.turn - 1])
h6 = []
for rule, d in ctx.items():
    mv, mc = statistics.median(d["violating"]), statistics.median(d["compliant"])
    h6.append({"rule": rule, "violating_n": len(d["violating"]), "violating_median_tokens": mv,
               "compliant_n": len(d["compliant"]), "compliant_median_tokens": mc})
    print(f"  {rule}: violating median {mv:7.0f} tokens (n={len(d['violating'])})  compliant median {mc:7.0f} (n={len(d['compliant'])})")
report.write(OUT / "h6-context.csv", h6)

# Registered dose-response: in countdown arms, violation rate per change by actions remaining.
print("\nDose-response (countdown arms, mitigation; procedural violations per change by share of budget left):")
dose = defaultdict(lambda: [0, 0])
for r in rows:
    ep = r["episode"]
    if r["arm"] not in ("budget", "budgetmedian", "combined") or ep.task != "mitigation":
        continue
    cap = 15 if r["arm"] == "budget" else 24
    bad = Counter((v.step) for v in r["violations"] if v.rule in ("R3", "R7", "R8"))
    for a in ep.actions:
        if not any(is_change(c) for c in a.commands):
            continue
        left = (cap - a.turn + 1) / cap          # the countdown counts harness turns
        band = "first third" if left > 2 / 3 else "middle third" if left > 1 / 3 else "last third"
        dose[(r["arm"], band)][0] += bad[a.step]
        dose[(r["arm"], band)][1] += 1
for arm in ("budget", "budgetmedian", "combined"):
    print(f"  {arm:12} " + "  ".join(f"{band}: {dose[(arm, band)][0]}/{dose[(arm, band)][1]} changes"
                                      for band in ("first third", "middle third", "last third")))
report.write(OUT / "dose-response.csv", [{"arm": a, "band": b, "violations": v, "changes": n} for (a, b), (v, n) in dose.items()])

# Facts the text needs.
print("\nFacts:")
pm = [r for r in rows if r["arm"] == "policy" and r["task"] == "mitigation" and r["success"]]
print(f"  successful policy-arm mitigation episodes: {len(pm)}; within 15 actions: {sum(r['steps'] <= 15 for r in pm)}")
r9 = defaultdict(lambda: [0, 0])
for c in cells:
    if c["rule"] == "R9":
        fault = c["problem_id"].rsplit("-", 2)[0]
        r9[fault][0] += c["violations"]; r9[fault][1] += c["opportunities"]
print("  R9 by fault (all arms):", {k: f"{v}/{n}" for k, (v, n) in sorted(r9.items())})
rounds = report.rates([c for c in cells if c["variant"] in ("nopolicy", "policy")], ("variant", "round", "rule"))
print("  round replication (policy-arm and no-policy rates by round):")
for arm in ("nopolicy", "policy"):
    for rule in ("R2", "R3", "R6", "R7", "R8", "R9"):
        rr = {r["round"]: r for r in rounds if r["variant"] == arm and r["rule"] == rule}
        print(f"    {arm:9} {rule}: r1 {100 * rr[1]['rate']:5.1f}%  r2 {100 * rr[2]['rate']:5.1f}%")
term = Counter((e["variant"], e["termination_reason"]) for e in eps)
print("  terminations:", {a: {t: n for (v, t), n in term.items() if v == a} for a in ARMS})
print("  parse-failure episodes:", sum(e["parse_failures"] > 0 for e in eps), "| actions total:", sum(e["steps"] for e in eps))
