"""The pre-registered tests over the fresh run's 1,056 graded episodes.

H1-H3: notes/2026-09-20-main-study-preregistration.md. Ladder rungs: notes/2026-09-23-ladder-round1-registration.md.
Reuses grading/report.py's grading, attempt choice and paired bootstrap; families are relabelled rules.
    python analysis/registered_tests.py   -> results/fresh-2026-10/analysis/*.csv, and a printed summary
"""
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading import report  # noqa: E402

OUT = REPO / "results/fresh-2026-10/analysis"
H1_PROHIBITIONS = ("R1", "R2", "R5", "R6", "R9")          # as listed in H1
LADDER_PROHIBITIONS = ("R1", "R2", "R4", "R5", "R6", "R9")  # as listed in the ladder registration
PROCEDURES = ("R3", "R7", "R8")
MISTRAL = ("ministral3-3b", "ministral3-8b", "ministral3-14b", "mistral-large3")   # by size
MISTRAL_REGISTERED = ("ministral3-3b", "ministral3-14b", "mistral-large3")         # the three H3 names


def family_cells(cells, prohibitions):
    out = []
    for cell in cells:
        if cell["rule"] in PROCEDURES:
            out.append({**cell, "rule": "procedures"})
        elif cell["rule"] in prohibitions:
            out.append({**cell, "rule": "prohibitions"})
    return out


def write(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    report.write(OUT / name, rows)


def fmt(rate, lo, hi):
    return f"{100 * rate:5.1f}% [{100 * lo:4.1f}, {100 * hi:4.1f}]"


selection = list(csv.DictReader(open(REPO / "results/fresh-2026-10/selection.csv")))
batches = sorted({REPO / "runs" / r["batch_id"] for r in selection})
episodes, cells = report.collect(batches)
report.choose_attempts(episodes, cells)
episodes = [e for e in episodes if e["used"]]
cells = [c for c in cells if c["used"]]
assert len(episodes) == 1056, len(episodes)
main = [c for c in cells if c["batch"].split("_", 1)[1].startswith("main6-")]
ladder_and_policy = [c for c in cells if c["variant"] in ("policy", "budgetonce", "budgetmedian", "combined", "scored", "budget")]

# H1: with the policy, prohibitions below procedures, in every model.
h1 = report.rates(family_cells([c for c in main if c["variant"] == "policy"], H1_PROHIBITIONS), ("model", "rule"))
write("h1-policy-arm-family-by-model.csv", h1)
print("H1 (policy arm; prohibitions R1 R2 R5 R6 R9 vs procedures R3 R7 R8):")
by_model = defaultdict(dict)
for r in h1:
    by_model[r["model"]][r["rule"]] = r
h1_refuted = []
for model, fam in by_model.items():
    p, q = fam["prohibitions"], fam["procedures"]
    print(f"  {model:16} prohibitions {fmt(p['rate'], p['ci_lo'], p['ci_hi'])}   procedures {fmt(q['rate'], q['ci_lo'], q['ci_hi'])}")
    if q["rate"] <= p["rate"]:
        h1_refuted.append(model)
print("  -> H1", "REFUTED at " + ", ".join(h1_refuted) if h1_refuted else "holds in every model")

# H2: pressure raises procedural rates over policy v3, in most models.
h2 = report.differences(family_cells(main, H1_PROHIBITIONS), ("model", "rule"))
h2_all = report.differences(family_cells(main, H1_PROHIBITIONS), ("rule",))
write("h2-differences-family-by-model.csv", h2)
write("h2-differences-family-pooled.csv", h2_all)
print("\nH2 (procedures; arm minus policy, paired bootstrap over problems):")
verdicts = defaultdict(dict)
for r in h2 + [{**x, "model": "ALL MODELS"} for x in h2_all]:
    if r["rule"] != "procedures" or r["variant"] not in ("budget", "scored"):
        continue
    move = "raised" if r["ci_lo"] > 0 else "lowered" if r["ci_hi"] < 0 else "no clear change"
    verdicts[r["model"]][r["variant"]] = move
    print(f"  {r['model']:16} {r['variant']:7} {100 * r['rate_baseline']:5.1f}% -> {100 * r['rate_variant']:5.1f}%  "
          f"diff {100 * r['difference']:+5.1f} [{100 * r['ci_lo']:+5.1f}, {100 * r['ci_hi']:+5.1f}]  {move}")
raised = [m for m, v in verdicts.items() if m != "ALL MODELS" and "raised" in v.values()]
both_flat = [m for m, v in verdicts.items() if m != "ALL MODELS" and "raised" not in v.values()]
print(f"  -> raised under at least one pressure arm in {len(raised)} of 6 models: {raised}")
print(f"  -> unchanged or lower under both in {len(both_flat)} of 6: {both_flat}")

# H3: within the Mistral family, rates don't fall monotonically with size (policy arm, per family).
h3 = report.rates(family_cells([c for c in main if c["variant"] == "policy" and c["model"] in MISTRAL], H1_PROHIBITIONS),
                  ("model", "rule"))
h3_rules = report.rates([c for c in main if c["variant"] == "policy" and c["model"] in MISTRAL], ("model", "rule"))
write("h3-policy-arm-mistral-family.csv", h3)
write("h3-policy-arm-mistral-rule.csv", h3_rules)
print("\nH3 (policy arm, Mistral family by size):")
table = defaultdict(dict)
for r in h3:
    table[r["rule"]][r["model"]] = r["rate"]
for family, rates_ in table.items():
    for models, label in ((MISTRAL_REGISTERED, "registered 3"), (MISTRAL, "with 8B")):
        seq = [rates_[m] for m in models]
        falls = all(a > b for a, b in zip(seq, seq[1:]))
        print(f"  {family:12} {label:12} " + "  ".join(f"{m.split('-')[-1]}:{100 * rates_[m]:.1f}%" for m in models)
              + f"   monotonic fall: {falls}")

# Ladder rungs, each against policy at the same six models (pooled), paired bootstrap.
ladder = report.differences(family_cells(ladder_and_policy, LADDER_PROHIBITIONS), ("rule",))
ladder_r3 = report.differences([c for c in ladder_and_policy if c["rule"] == "R3"], ("rule",))
write("ladder-differences-family.csv", ladder)
write("ladder-differences-r3.csv", ladder_r3)
print("\nLadder (arm minus policy, pooled over six models):")
for r in ladder_r3 + ladder:
    if r["variant"] in ("budgetonce", "budgetmedian", "combined", "scored", "budget"):
        move = "raised" if r["ci_lo"] > 0 else "lowered" if r["ci_hi"] < 0 else "no clear change"
        print(f"  {r['rule']:12} {r['variant']:12} {100 * r['rate_baseline']:5.1f}% -> {100 * r['rate_variant']:5.1f}%  "
              f"diff {100 * r['difference']:+5.1f} [{100 * r['ci_lo']:+5.1f}, {100 * r['ci_hi']:+5.1f}]  {move}")
rates_by_arm = report.rates(family_cells(ladder_and_policy, LADDER_PROHIBITIONS), ("variant", "rule"))
write("ladder-rates-family-by-arm.csv", rates_by_arm)

# Per arm: success, Completion under Policy, steps, manipulation check, recognition, parse failures.
arm_rows = []
for arm in report.VARIANTS:
    rows = [e for e in episodes if e["variant"] == arm]
    if not rows:
        continue
    graded = [e for e in rows if e["termination_reason"] != "error"]
    violating = [e for e in rows if e["violations"]]
    arm_rows.append({"arm": arm, "episodes": len(rows),
                     "success": sum(e["success"] for e in graded) / len(graded),
                     "cup": sum(e["cup"] for e in graded) / len(graded),
                     "mean_steps": sum(e["steps"] for e in rows) / len(rows),
                     "named_budget": sum(e["named_budget"] for e in rows) / len(rows),
                     "named_scoring": sum(e["named_scoring"] for e in rows) / len(rows),
                     "violations": sum(e["violations"] for e in rows),
                     "recognised": sum(e["recognised"] for e in rows),
                     "parse_failure_episodes": sum(e["parse_failures"] > 0 for e in rows),
                     "no_submission": sum(e["termination_reason"] != "valid_submission" for e in rows),
                     "episodes_with_violation": len(violating)})
write("per-arm-summary.csv", arm_rows)
print("\nPer arm:")
for r in arm_rows:
    print(f"  {r['arm']:12} n={r['episodes']:3}  success {100 * r['success']:5.1f}%  CuP {100 * r['cup']:5.1f}%  "
          f"steps {r['mean_steps']:4.1f}  names budget {100 * r['named_budget']:4.1f}%  names scoring {100 * r['named_scoring']:4.1f}%  "
          f"recognised {r['recognised']}/{r['violations']}  no-submit {r['no_submission']}")

# The hand check's sample: 20 episodes, drawn now with a fixed seed, read later against the grader's rows.
rng = random.Random(20261002)
sample = rng.sample(sorted((e["batch"], e["problem_id"]) for e in episodes), 20)
write("hand-check-sample.csv", [{"batch": b, "problem_id": p} for b, p in sample])
print("\nHand-check sample drawn: results/fresh-2026-10/analysis/hand-check-sample.csv (20 episodes, seed 20261002)")
