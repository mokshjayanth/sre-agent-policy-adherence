"""The paper's remaining numbers: those not written by the other analysis scripts.

Recomputes, from the 1,056 selected episodes, every figure the paper plan took from a one-off command:
H5 among episodes that changed something, success differences with paired intervals, endings at the
step limit, R5/R6/R9 counts, and the harness-usability counts. Prints them; writes
results/fresh-2026-10/analysis/paper-numbers.csv. (Until 2026-10-05 it also held an R3 sensitivity
check, now applied by the grader itself, and R7 by thirds of the episode, replaced by
analysis/exploratory.py's within-episode comparison; notes/2026-10-05-draft-review.md.)
    python analysis/paper_numbers.py
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading import report                      # noqa: E402
from grading.episode import load                # noqa: E402
from grading.grade import app_by_problem        # noqa: E402
from grading.rules import grade, is_change      # noqa: E402

OUT = REPO / "results/fresh-2026-10/analysis/paper-numbers.csv"
apps = app_by_problem()
selection = list(csv.DictReader(open(REPO / "results/fresh-2026-10/selection.csv")))
assert len(selection) == 1056
numbers = []


def put(name, value, note=""):
    numbers.append({"name": name, "value": value, "note": note})
    print(f"  {name:48} {value}  {note}")


def ci(d):
    return f"{100 * d['difference']:+.1f} [{100 * d['ci_lo']:+.1f}, {100 * d['ci_hi']:+.1f}]"


episodes = {}
for s in selection:
    path = REPO / "runs" / s["batch_id"] / "problems" / s["problem_id"] / "trajectory.json"
    episodes[(s["batch_id"], s["problem_id"])] = (s, load(path, apps), json.loads(path.read_text()))
eps, cells = report.collect(sorted({REPO / "runs" / s["batch_id"] for s in selection}))
report.choose_attempts(eps, cells)
eps = [e for e in eps if e["used"]]
cells = [c for c in cells if c["used"]]
assert len(eps) == 1056


print("\nH5 among mitigation episodes that changed something (an executed change), policy-bearing arms:")
changed = defaultdict(lambda: [0, 0])
no_change_clean = clean_mit = 0
for e in eps:
    if e["task"] != "mitigation" or e["variant"] == "nopolicy":
        continue
    _, ep, _ = episodes[(e["batch"], e["problem_id"])]
    acted = any(a.ran and any(is_change(c) for c in a.commands) for a in ep.actions)
    if not e["violations"]:
        clean_mit += 1
        no_change_clean += not acted
    if acted:
        changed["violating" if e["violations"] else "clean"][0] += e["success"]
        changed["violating" if e["violations"] else "clean"][1] += 1
put("h5_clean_mitigation_without_change", f"{no_change_clean}/{clean_mit}", f"{100 * no_change_clean / clean_mit:.0f}%")
for k, (s, n) in changed.items():
    put(f"h5_changed_{k}_success", f"{s}/{n}", f"{100 * s / n:.0f}%")

print("\nSuccess, arm minus policy (paired over problems), per task:")
success_cells = [{**e, "rule": "success", "violations": int(e["success"]), "opportunities": 1} for e in eps]
for d in report.differences(success_cells, ("task",)):
    put(f"success_{d['task']}_{d['variant']}_minus_policy", ci(d),
        f"{100 * d['rate_baseline']:.1f}% -> {100 * d['rate_variant']:.1f}%")

print("\nEndings at the step limit, and changes per mitigation episode, by arm:")
ends = Counter((e["variant"], e["termination_reason"]) for e in eps)
for arm in report.VARIANTS:
    n = sum(1 for e in eps if e["variant"] == arm)
    if n:
        put(f"step_limit_endings_{arm}", f"{ends[(arm, 'max_steps')] + ends[(arm, 'step_limit')]}/{n}")
for arm in report.VARIANTS:
    mit = [v for v in episodes.values() if v[0]["arm"] == arm and v[0]["task"] == "mitigation"]
    if mit:
        n = sum(1 for _, ep, _ in mit for a in ep.actions for c in a.commands if is_change(c))
        put(f"changes_per_mitigation_episode_{arm}", f"{n / len(mit):.1f}")

print("\nR5 and R6 counts (no policy vs policy):")
for arm in ("nopolicy", "policy"):
    for rule in ("R5", "R6", "R9"):
        sub = [c for c in cells if c["variant"] == arm and c["rule"] == rule]
        put(f"{rule}_{arm}", f"{sum(c['violations'] for c in sub)}/{sum(c['opportunities'] for c in sub)}",
            "violations/opportunities")

print("\nHarness usability:")
calls = capped = not_full = 0
capped_eps, metrics_eps = set(), set()
get_logs = get_logs_rejected = 0
for (batch, problem), (s, ep, raw) in episodes.items():
    for c in (raw.get("agent_record") or {}).get("calls") or []:
        calls += 1
        if (c.get("observation_tokens_omitted") or 0) > 0:
            capped += 1
            capped_eps.add((batch, problem))
        if c.get("last_message_truncated") is not False:
            not_full += 1
    history = raw["history"]
    for i, m in enumerate(history):
        if m["role"] != "assistant":
            continue
        text = m["content"] or ""
        if re.search(r"exec_shell\([^)]*aiopslab-work", text):
            metrics_eps.add((batch, problem))
        if "get_logs(" in text:
            get_logs += 1
            if i + 1 < len(history) and "does not exist" in (history[i + 1]["content"] or ""):
                get_logs_rejected += 1
put("model_calls", calls)
put("calls_with_capped_observation", capped, f"{100 * capped / calls:.1f}% in {len(capped_eps)} episodes")
put("calls_not_sending_last_message_in_full", not_full)
put("episodes_seeking_get_metrics_output_from_shell", len(metrics_eps))
put("get_logs_calls_rejected", f"{get_logs_rejected}/{get_logs}", f"{100 * get_logs_rejected / get_logs:.0f}%")
actions = sum(e["steps"] for e in eps)
put("actions", actions, "parsed actions; model calls = parsed actions + parse failures")
# Until 2026-10-05 this divided by parsed actions (7.9%); a parse failure is a model call that produced
# no action, so the share is of model calls.
put("parse_failures", sum(e["parse_failures"] for e in eps),
    f"{100 * sum(e['parse_failures'] for e in eps) / calls:.1f}% of model calls, "
    f"{sum(e['parse_failures'] > 0 for e in eps)} episodes")

report.write(OUT, numbers)
print(f"\nwritten {OUT.relative_to(REPO)}")
