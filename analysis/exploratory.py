"""Exploratory analyses (not registered), and the checks the 2026-10-03 review of draft v1 asked for.

Every number here is labelled exploratory in the paper unless it only checks a registered one. The
review's own scripts weren't kept; each of its claims is computed again here from the 1,056 selected
episodes (notes/2026-10-05-draft-review.md says which held). Writes
results/fresh-2026-10/analysis/exploratory.csv (name, value, note) and episodes-acted-by-model.csv
(Fig. 2: mitigation episodes that executed a change, and how many broke a prohibition or a procedure).
    python analysis/exploratory.py
"""
import csv
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "third_party" / "aiopslab"), str(REPO)]
from grading import report                                  # noqa: E402
from grading.episode import load                            # noqa: E402
from grading.grade import app_by_problem                    # noqa: E402
from grading.rules import PROTECTED_KINDS, grade, is_change, opportunities   # noqa: E402

OUT = REPO / "results/fresh-2026-10/analysis/exploratory.csv"
PROHIB_M = ("R4", "R5", "R6", "R9")            # the prohibitions that apply in mitigation
PROC = ("R3", "R7", "R8")
POLICY_ARMS = ("policy", "budget", "scored", "budgetonce", "budgetmedian", "combined")
ADOPTERS = ("ministral3-14b", "gpt-oss-120b", "mistral-large3")     # record most changes under the policy
REPAIR_SCRIPT = re.compile(r"mitigate[\w-]*\.sh")                   # the harness's own fault-recovery scripts
EXEC_WRITE = re.compile(r"createUser|grantRoles?ToUser|updateUser|dropUser|/scripts/\S+\.sh|sed -i"
                        r"|\bapt(-get)? install|\bkill ")
apps = app_by_problem()
rows = []


def put(name, value, note=""):
    rows.append({"name": name, "value": value, "note": note})
    print(f"  {name:60} {value}  {note}")


def frac(a, b):
    return f"{a}/{b} ({100 * a / b:.1f}%)" if b else f"{a}/0"


selection = list(csv.DictReader(open(REPO / "results/fresh-2026-10/selection.csv")))
E = []
for s in selection:
    path = REPO / "runs" / s["batch_id"] / "problems" / s["problem_id"] / "trajectory.json"
    raw = json.loads(path.read_text())
    ep = load(path, apps)
    E.append({"ep": ep, "calls": (raw.get("agent_record") or {}).get("calls") or [], "v": grade(ep),
              "arm": s["arm"], "model": s["model"], "task": s["task"], "problem": s["problem_id"],
              "success": bool(ep.success)})
assert len(E) == 1056
eps, cells = report.collect(sorted({REPO / "runs" / s["batch_id"] for s in selection}))
report.choose_attempts(eps, cells)
eps = [e for e in eps if e["used"]]
cells = [c for c in cells if c["used"]]


def changes(e):
    """Every change command in order, with its R7 and R8 verdicts."""
    bad = Counter((v.step, v.rule, v.command) for v in e["v"])
    out = []
    for a in e["ep"].actions:
        for c in a.commands:
            if is_change(c):
                out.append({"cmd": c, "ran": a.ran,
                            "r7": bad[(a.step, "R7", c.text)] > 0, "r8": bad[(a.step, "R8", c.text)] > 0,
                            "restart": c.subcommand == "rollout" and "restart" in c.argv})
    return out


def acted(e):
    return any(a.ran and any(is_change(c) for c in a.commands) for a in e["ep"].actions)


def fisher(a, b, c, d):
    """Two-sided Fisher exact p for [[a, b], [c, d]]."""
    n1, n2, k, n = a + b, c + d, a + c, a + b + c + d
    pr = lambda x: comb(n1, x) * comb(n2, k - x) / comb(n, k)            # noqa: E731
    return sum(pr(x) for x in range(max(0, k - n2), min(k, n1) + 1) if pr(x) <= pr(a) * (1 + 1e-9))


def sign_p(plus, minus):
    """Two-sided sign test over problems (ties dropped)."""
    n, k = plus + minus, min(plus, minus)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0


# ---- A. Factual checks of draft v1 ------------------------------------------------------------------
print("A. Deletes, records, parse failures")
for arm in ("nopolicy", "policy"):
    kinds = Counter()
    for e in E:
        if e["arm"] == arm and e["task"] == "mitigation":
            for c in (x["cmd"] for x in changes(e)):
                if c.subcommand == "delete":
                    kinds["pods" if "pods" in c.kinds else "protected" if set(c.kinds) & PROTECTED_KINDS else "other"] += 1
    put(f"deletes_{arm}", dict(kinds), f"all deletes {sum(kinds.values())}")
for e in E:
    if e["arm"] == "policy":
        for v in e["v"]:
            if v.rule == "R5":
                put("r5_policy_arm", f"{e['model']} {e['problem']}", v.command[:100])
records = [c for e in E for a in e["ep"].actions for c in a.commands if c.records_change]
put("change_records", len(records), f"to /dev/null: {sum('/dev/null' in c.text for c in records)}")
calls = sum(len(e["calls"]) for e in E)
put("parse_failures_of_model_calls", frac(sum(e["ep"].parse_failures for e in E), calls))

# ---- B. What the policy changes, by rule type ------------------------------------------------------
print("\nB. Families with and without the policy; episode level; difference of drops")


def family(cs, prohib, proc, by):
    out = defaultdict(lambda: {"prohib": [0, 0], "proc": [0, 0]})
    for c in cs:
        fam = "prohib" if c["rule"] in prohib else "proc" if c["rule"] in proc else None
        if fam:
            k = tuple(c[x] for x in by)
            out[k][fam][0] += c["violations"]
            out[k][fam][1] += c["opportunities"]
    return out


H1_PROHIB = ("R1", "R2", "R5", "R6", "R9")
for arm in ("nopolicy", "policy"):
    f = family([c for c in cells if c["variant"] == arm], H1_PROHIB, PROC, ())[()]
    per = family([c for c in cells if c["variant"] == arm], H1_PROHIB, PROC, ("model",))
    above = sum(v["proc"][0] / v["proc"][1] > v["prohib"][0] / v["prohib"][1] for v in per.values())
    put(f"family_{arm}", f"prohibitions {frac(*f['prohib'])}; procedures {frac(*f['proc'])}",
        f"procedures above prohibitions in {above} of 6 models")
rates = {(r["variant"], r["rule"]): r for r in report.rates(cells, ("variant", "rule"))}
put("policy_over_nopolicy_by_rule", {rule: round(rates[("policy", rule)]["rate"] / rates[("nopolicy", rule)]["rate"], 2)
                                     for rule in ("R1", "R2", "R3", "R6", "R7", "R8", "R9")}, "rate ratio")
per = family([c for c in cells if c["variant"] == "policy"], ("R2", "R5", "R6", "R9"), ("R3", "R8"), ("model",))
for (m,), v in sorted(per.items()):
    put(f"h1_without_r1_r7_{m}", f"prohibitions {frac(*v['prohib'])}; procedures {frac(*v['proc'])}")

fig2 = []
for arm in ("nopolicy", "policy"):
    a = [e for e in E if e["arm"] == arm and e["task"] == "mitigation" and acted(e)]
    for m in sorted({e["model"] for e in E}) + ["all"]:
        am = [e for e in a if m in ("all", e["model"])]
        fig2.append({"arm": arm, "model": m, "acted": len(am),
                     "broke_prohibition": sum(any(v.rule in PROHIB_M for v in e["v"]) for e in am),
                     "broke_procedure": sum(any(v.rule in PROC for v in e["v"]) for e in am)})
    put(f"acted_mitigation_{arm}",
        f"broke a prohibition {frac(sum(any(v.rule in PROHIB_M for v in e['v']) for e in a), len(a))}; "
        f"a procedure {frac(sum(any(v.rule in PROC for v in e['v']) for e in a), len(a))}; "
        f"R3 or R8 {frac(sum(any(v.rule in ('R3', 'R8') for v in e['v']) for e in a), len(a))}",
        f"R6 alone accounts for {sum(any(v.rule == 'R6' for v in e['v']) and not any(v.rule in ('R4', 'R5', 'R9') for v in e['v']) for e in a)} of the prohibition episodes")
    for m in sorted({e["model"] for e in E}):
        am = [e for e in a if e["model"] == m]
        put(f"acted_mitigation_{arm}_{m}",
            f"prohibition {sum(any(v.rule in PROHIB_M for v in e['v']) for e in am)}/{len(am)}; "
            f"procedure {sum(any(v.rule in PROC for v in e['v']) for e in am)}/{len(am)}")


def dd_table(cs, prohib, proc):
    t = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0])))
    for c in cs:
        if c["task"] == "mitigation" and c["variant"] in ("nopolicy", "policy"):
            fam = "prohib" if c["rule"] in prohib else "proc" if c["rule"] in proc else None
            if fam:
                t[c["problem_id"]][c["variant"]][fam][0] += c["violations"]
                t[c["problem_id"]][c["variant"]][fam][1] += c["opportunities"]
    return t


def dd(t, problems):
    r = []
    for arm, fam in (("policy", "prohib"), ("nopolicy", "prohib"), ("policy", "proc"), ("nopolicy", "proc")):
        v, n = (sum(t[p][arm][fam][i] for p in problems) for i in (0, 1))
        if not n:
            return None
        r.append(v / n)
    return (r[0] - r[1]) - (r[2] - r[3]), r


for label, prohib in (("with_R6", ("R5", "R6", "R9")), ("without_R6", ("R5", "R9"))):
    t = dd_table(cells, prohib, ("R3", "R8"))
    probs = sorted(t)
    est, r = dd(t, probs)
    rng = random.Random(20261005)
    draws = sorted(x[0] for x in (dd(t, [rng.choice(probs) for _ in probs]) for _ in range(10000)) if x)
    put(f"difference_of_drops_{label}", f"{100 * est:+.1f} [{100 * draws[250]:+.1f}, {100 * draws[9750]:+.1f}]",
        f"prohibitions {100 * r[1]:.1f} -> {100 * r[0]:.1f}; procedures {100 * r[3]:.1f} -> {100 * r[2]:.1f} (mitigation)")
by_model = {m: dd(dd_table([c for c in cells if c["model"] == m], ("R5", "R6", "R9"), ("R3", "R8")),
                  sorted({c["problem_id"] for c in cells if c["task"] == "mitigation"})) for m in sorted({c["model"] for c in cells})}
put("difference_of_drops_by_model", {m: round(100 * x[0], 1) for m, x in by_model.items() if x})

print("\n   Policy minus no policy, per problem (sign counts):")
per_problem = defaultdict(lambda: [0, 0])
for c in cells:
    per_problem[(c["variant"], c["rule"], c["problem_id"])][0] += c["violations"]
    per_problem[(c["variant"], c["rule"], c["problem_id"])][1] += c["opportunities"]
for rule in ("R2", "R3", "R6", "R7", "R8", "R9"):
    signs = Counter()
    for p in sorted({k[2] for k in per_problem if k[1] == rule}):
        a, b = per_problem[("nopolicy", rule, p)], per_problem[("policy", rule, p)]
        if a[1] and b[1]:
            d = b[0] / b[1] - a[0] / a[1]
            signs["down" if d < 0 else "up" if d > 0 else "same"] += 1
    put(f"policy_effect_signs_{rule}", dict(signs), f"sign test p = {sign_p(signs['up'], signs['down']):.3f}")

# ---- C. How procedures fail ------------------------------------------------------------------------
print("\nC. Recording (R7) and verifying (R8) across an episode")
for m in sorted({e["model"] for e in E}):
    ch = [x for e in E if e["arm"] == "policy" and e["model"] == m for x in changes(e)]
    put(f"r7_unrecorded_policy_arm_{m}", frac(sum(x["r7"] for x in ch), len(ch)))
patterns, first, last, n = Counter(), 0, 0, 0
for e in E:
    if e["arm"] not in POLICY_ARMS or e["model"] not in ADOPTERS:
        continue
    ch = changes(e)
    if len(ch) < 2:
        continue
    flags = [x["r7"] for x in ch]
    n += 1
    first += flags[0]
    last += flags[-1]
    if not any(flags):
        patterns["recorded every change"] += 1
    elif all(flags):
        patterns["recorded none"] += 1
    elif all((not x["r7"]) or (x["restart"] and i and not flags[i - 1]) for i, x in enumerate(ch)):
        patterns["skipped only a restart right after a recorded change"] += 1
    elif all(flags[flags.index(True):]):
        patterns["recorded, then stopped for good"] += 1
    else:
        patterns["intermittent"] += 1
put("r7_adopters_first_last", f"first change unrecorded {frac(first, n)}; last {frac(last, n)}",
    "Ministral 3 14B, gpt-oss-120b, Mistral Large 3; policy-bearing arms; episodes with >= 2 changes")
put("r7_adopters_patterns", dict(patterns), f"of {n} episodes")
for key, arms in (("no_countdown", ("policy", "scored", "budgetonce")),
                  ("countdown", ("budget", "budgetmedian", "combined"))):
    ch = [changes(e) for e in E if e["arm"] in arms and e["model"] in ADOPTERS]
    ch = [c for c in ch if len(c) >= 2]
    put(f"r7_adopters_first_last_{key}", f"first unrecorded {frac(sum(c[0]['r7'] for c in ch), len(ch))}; "
                                         f"last {frac(sum(c[-1]['r7'] for c in ch), len(ch))}", ", ".join(arms))
lg = [e for e in E if e["arm"] in POLICY_ARMS and e["model"] == "mistral-large3" and len(changes(e)) >= 2]
put("r7_large3_first_last", f"first unrecorded {sum(changes(e)[0]['r7'] for e in lg)}/{len(lg)}; "
                            f"last {sum(changes(e)[-1]['r7'] for e in lg)}/{len(lg)}")
first = last = n = followed = total = 0
for e in E:
    if e["arm"] not in POLICY_ARMS:
        continue
    ch = changes(e)
    ran = [x for x in ch if x["ran"]]
    if len(ran) >= 2:
        n += 1
        first += ran[0]["r8"]
        last += ran[-1]["r8"]
    for i, x in enumerate(ch):
        if x["r8"]:
            total += 1
            followed += i + 1 < len(ch) and ch[i + 1]["restart"]
put("r8_first_last", f"first executed change unverified {frac(first, n)}; last {frac(last, n)}",
    "policy-bearing arms; episodes with >= 2 executed changes")
put("r8_next_change_is_rollout_restart", frac(followed, total))

# ---- D. Sanctioned paths, and the harness's own fixes ----------------------------------------------
print("\nD. Rejected get_logs before exec; the harness's repair scripts")
ok = ok_exec = rej = rej_exec = after = 0
for e in E:
    if e["arm"] not in POLICY_ARMS or e["task"] != "diagnosis":
        continue
    logs = [a for a in e["ep"].actions if a.api == "get_logs"]
    if not logs:
        continue
    rejected = [a.step for a in logs if "does not exist" in (a.reply or "")]
    execs = [a.step for a in e["ep"].actions if any(c.exec_like for c in a.commands)]
    if rejected:
        rej += 1
        rej_exec += bool(execs)
        after += bool(execs) and min(execs) > min(rejected)
    else:
        ok += 1
        ok_exec += bool(execs)
put("r2_when_get_logs_never_rejected", frac(ok_exec, ok), "diagnosis episodes, policy-bearing arms")
put("r2_when_get_logs_rejected", frac(rej_exec, rej), f"first exec after the first rejection in {after}")
arg = Counter()
for e in E:
    for a in e["ep"].actions:
        if a.api == "get_logs" and "does not exist" in (a.reply or ""):
            svc = str(a.args[1]).lower().replace(" ", "") if len(a.args) > 1 else ""
            arg["application name" if svc in ("hotelreservation", "hotel-reservation", "socialnetwork", "social-network")
                else "empty" if not svc else "other"] += 1
put("rejected_get_logs_by_argument", dict(arg))
tried = [e for e in E if e["task"] == "mitigation" and any(
    c.exec_like and REPAIR_SCRIPT.search(c.text) for a in e["ep"].actions for c in a.commands)]
ran = [e for e in tried if any(a.ran and c.exec_like and REPAIR_SCRIPT.search(c.text)
                               for a in e["ep"].actions for c in a.commands)]
put("repair_script_episodes", f"tried {len(tried)}; ran {len(ran)}; succeeded {sum(e['success'] for e in ran)}",
    "CuP: " + ", ".join(f"{e['model']}/{e['arm']}/{e['problem']}" for e in ran if e["success"] and not e["v"]))
ew = [e for e in E if e["task"] == "mitigation" and any(
    a.ran and c.exec_like and EXEC_WRITE.search(c.text) for a in e["ep"].actions for c in a.commands)]
put("mitigation_episodes_with_an_executed_change_through_exec", frac(len(ew), sum(e["task"] == "mitigation" for e in E)),
    "narrow pattern: user/role changes, scripts, sed -i, installs, kill; a lower bound")

# ---- E. What successful mitigations broke ----------------------------------------------------------
print("\nE. Successful mitigations")
for arm in ("nopolicy", "policy"):
    good = [e for e in E if e["arm"] == arm and e["task"] == "mitigation" and e["success"]]
    n = sum(e["arm"] == arm and e["task"] == "mitigation" for e in E)
    put(f"successes_{arm}",
        f"{len(good)}: broke a prohibition {sum(any(v.rule in PROHIB_M for v in e['v']) for e in good)}; "
        f"a procedure {sum(any(v.rule in PROC for v in e['v']) for e in good)}; "
        f"only R7 {sum(bool(e['v']) and all(v.rule == 'R7' for v in e['v']) for e in good)}",
        f"CuP {sum(not e['v'] for e in good)}/{n}; ignoring R7 {sum(all(v.rule == 'R7' for v in e['v']) for e in good)}/{n}")

# ---- F. Budgets against truncation; the caps in harness turns ---------------------------------------
print("\nF. Truncation baselines (policy-arm episodes that succeeded and submitted by turn k)")
for task, k in (("diagnosis", 9), ("diagnosis", 15), ("mitigation", 24), ("mitigation", 15)):
    pol = [e for e in E if e["arm"] == "policy" and e["task"] == task]
    hit = sum(e["success"] and any(a.api == "submit" and a.turn <= k for a in e["ep"].actions) for e in pol)
    put(f"truncated_policy_{task}_{k}", frac(hit, len(pol)))
for task in ("mitigation", "diagnosis"):
    good = [e for e in E if e["arm"] == "policy" and e["task"] == task and e["success"]]
    put(f"cap_rule_{task}", f"median parsed actions {statistics.median(len(e['ep'].actions) for e in good)}; "
                            f"median harness turns {statistics.median(len(e['calls']) for e in good)} (n={len(good)})")
put("actions_whose_step_is_not_their_turn", frac(sum(a.step != a.turn for e in E for a in e["ep"].actions),
                                                 sum(len(e["ep"].actions) for e in E)))

# ---- G. How robust the R3 rises are ----------------------------------------------------------------
print("\nG. R3 by problem; interval lower bound over seeds")
for arm in ("budget", "scored", "nopolicy"):
    signs = Counter()
    for p in sorted({k[2] for k in per_problem if k[1] == "R3"}):
        a, b = per_problem[("policy", "R3", p)], per_problem[(arm, "R3", p)]
        if a[1] and b[1]:
            d = b[0] / b[1] - a[0] / a[1]
            signs["up" if d > 0 else "down" if d < 0 else "same"] += 1
            put(f"r3_{arm}_minus_policy_{p}", f"{100 * d:+.1f}", f"policy {a[0]}/{a[1]}, {arm} {b[0]}/{b[1]}")
    put(f"r3_{arm}_minus_policy_signs", dict(signs), f"sign test p = {sign_p(signs['up'], signs['down']):.3f}")
    r3 = [c for c in cells if c["rule"] == "R3" and c["variant"] in ("policy", arm)]
    lows = []
    for seed in range(10):
        rng, by = random.Random(seed), defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for c in r3:
            by[c["variant"]][c["problem_id"]][0] += c["violations"]
            by[c["variant"]][c["problem_id"]][1] += c["opportunities"]
        ps, d = sorted(by["policy"]), []
        for _ in range(10000):
            dr = [rng.choice(ps) for _ in ps]
            x = [sum(by[v][p][0] for p in dr) / max(1, sum(by[v][p][1] for p in dr)) for v in ("policy", arm)]
            d.append(x[1] - x[0])
        d.sort()
        lows.append(d[250])
    put(f"r3_{arm}_minus_policy_ci_low_over_10_seeds", f"{100 * min(lows):+.1f} to {100 * max(lows):+.1f}")

# ---- H. H5 as registered; recognition; the manipulation check with reasoning -------------------------
print("\nH. H5, recognition, manipulation check")
h5 = list(csv.DictReader(open(REPO / "results/fresh-2026-10/analysis/h5-cells.csv")))
for task in ("mitigation", "diagnosis"):
    g = [x for x in h5 if x["task"] == task]
    more = sum(float(x["success_violating"]) > float(x["success_clean"]) for x in g)
    less = sum(float(x["success_violating"]) < float(x["success_clean"]) for x in g)
    put(f"h5_cells_{task}", f"{len(g)} cells: violating succeed more in {more}, less in {less}, equal in {len(g) - more - less}")
put("h5_acted_fisher_p", f"{fisher(11, 27, 59, 266):.2f}", "clean 11/38 vs violating 59/325 (paper-numbers.csv)")
length = defaultdict(list)
for e in E:
    if e["task"] == "diagnosis" and e["arm"] in POLICY_ARMS:
        length["violating" if e["v"] else "clean"].append(len(e["ep"].actions))
put("diagnosis_mean_actions", {k: round(statistics.mean(v), 1) for k, v in length.items()})
cited = same = 0
for e in E:
    if e["arm"] == "nopolicy":
        continue
    text = {a.step: f"{a.thought}\n{a.reasoning}" for a in e["ep"].actions}
    for v in e["v"]:
        named = set(re.findall(r"\bR[1-9]\b", text.get(v.step, "")))
        if named:
            cited += 1
            same += v.rule in named
put("violations_naming_a_rule_that_name_the_broken_one", frac(same, cited))

# ---- I. Grader scope, serving, timing --------------------------------------------------------------
print("\nI. Grader scope, serving, when each arm ran")
mit = [c for e in E if e["task"] == "mitigation" for a in e["ep"].actions for c in a.commands if is_change(c)]
put("changes_without_a_namespace", frac(sum(c.namespace is None and not c.all_namespaces for c in mit), len(mit)))
allc = [c for e in E for a in e["ep"].actions for c in a.commands]
put("commands_unresolved", frac(sum(c.unresolved for c in allc), len(allc)))
put("r3_opportunities", f"{sum(opportunities(e['ep'])['R3'] for e in E)} of {len(mit)} changes (named, existing resource)")
for m in sorted({e["model"] for e in E}):
    cs = [c for e in E if e["model"] == m for c in e["calls"]]
    put(f"output_cap_reached_{m}", frac(sum(c.get("finish_reason") == "length" for c in cs), len(cs)))
cat = {r["batch_id"]: r for r in csv.DictReader(open(REPO / "results/fresh-2026-10/batches-all.csv"))}
when = defaultdict(list)
for s in selection:
    when[s["arm"]].append(cat[s["batch_id"]]["started_utc"][:16])
for arm in report.VARIANTS:
    if when[arm]:
        put(f"ran_{arm}", f"{min(when[arm])} to {max(when[arm])} UTC")

report.write(OUT, rows)
report.write(OUT.parent / "episodes-acted-by-model.csv", fig2)      # Fig. 2
print(f"\nwritten {OUT.relative_to(REPO)}")
