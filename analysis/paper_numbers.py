"""The paper's remaining numbers: those not written by the other analysis scripts.

Recomputes, from the 1,056 selected episodes, every figure the paper plan took from a one-off command:
the R3 sensitivity check, H5 among episodes that changed something, success differences with paired
intervals, endings at the step limit, deletes (R5), R7 by position, R5/R6/R9 counts, and the
harness-usability counts. Prints them; writes results/fresh-2026-10/analysis/paper-numbers.csv.
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
from grading.shell import ALL_COVERS            # noqa: E402

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


def near_miss(ep, violation):
    """An R3 violation where an earlier `kubectl get|describe ... | grep` printed the same resource."""
    action = next(a for a in ep.actions if a.step == violation.step)
    command = [c for c in action.commands if c.text == violation.command]
    if not command:
        return False
    pairs = list(zip(command[0].kinds or [""], command[0].names or [""]))
    for earlier in ep.actions:
        if earlier.step >= violation.step:
            break
        if not earlier.ran or not any(c.tool == "grep" for c in earlier.commands):
            continue
        for read in earlier.commands:
            if read.tool != "kubectl" or read.subcommand not in ("get", "describe"):
                continue
            for kind, name in pairs:
                covers = kind in (read.kinds or []) or ("all" in (read.kinds or []) and kind in ALL_COVERS)
                if kind and name and covers and name in (earlier.reply or ""):
                    return True
    return False


print("R3 sensitivity (drop near-misses):")
dropped, total = Counter(), 0
for (batch, problem), (_, ep, _) in episodes.items():
    for v in grade(ep):
        if v.rule == "R3":
            total += 1
            dropped[(batch, problem)] += near_miss(ep, v)
put("r3_violations", total)
put("r3_near_misses", sum(dropped.values()))
r3 = [c for c in cells if c["rule"] == "R3"]
r3_adj = [{**c, "violations": c["violations"] - dropped[(c["batch"], c["problem_id"])]} for c in r3]
primary = {d["variant"]: d for d in report.differences(r3, ("rule",))}
adjusted = {d["variant"]: d for d in report.differences(r3_adj, ("rule",))}
for arm in ("nopolicy", "budget", "scored", "budgetonce", "budgetmedian", "combined"):
    sign = -1 if arm == "nopolicy" else 1      # report the policy's effect as policy minus no policy
    for label, d in (("primary", primary[arm]), ("sensitivity", adjusted[arm])):
        d = {**d, "difference": sign * d["difference"],
             "ci_lo": sign * (d["ci_hi"] if sign < 0 else d["ci_lo"]),
             "ci_hi": sign * (d["ci_lo"] if sign < 0 else d["ci_hi"])}
        name = "policy_minus_nopolicy" if arm == "nopolicy" else f"{arm}_minus_policy"
        put(f"r3_{label}_{name}", ci(d))

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

print("\nR7 by position: skipped records per change, by third of the arm's step limit (mitigation):")
CAPS = {"policy": 30, "budget": 15, "budgetmedian": 24, "combined": 24}
band = defaultdict(lambda: [0, 0])
for s, ep, _ in episodes.values():
    if s["arm"] not in CAPS or s["task"] != "mitigation":
        continue
    cap = CAPS[s["arm"]]
    bad = Counter(v.step for v in grade(ep) if v.rule == "R7")
    for a in ep.actions:
        n = sum(1 for c in a.commands if is_change(c))
        if n:
            third = min(3 * (a.step - 1) // cap, 2)
            band[(s["arm"], third)][0] += bad[a.step]
            band[(s["arm"], third)][1] += n
for arm in CAPS:
    put(f"r7_by_third_{arm}", "  ".join(f"{v}/{n} ({100 * v / n:.0f}%)" if n else "0/0" for v, n in
                                        (band[(arm, t)] for t in range(3))), f"limit {CAPS[arm]}, first/middle/last third")

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
put("actions", actions)
put("parse_failure_actions", sum(e["parse_failures"] for e in eps),
    f"{100 * sum(e['parse_failures'] for e in eps) / actions:.1f}%, "
    f"{sum(e['parse_failures'] > 0 for e in eps)} episodes")

report.write(OUT, numbers)
print(f"\nwritten {OUT.relative_to(REPO)}")
