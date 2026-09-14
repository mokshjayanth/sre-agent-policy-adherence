---
date: 2026-09-14
type: investigation
status: current
evidence:
  - third_party/aiopslab/aiopslab/orchestrator/actions/base.py:80-92 (exec_shell signature and docstring)
  - third_party/aiopslab/aiopslab/orchestrator/parser.py:105-172 (parse_args, is_shell_command branch)
  - runs/2026-09-14T083253Z_smoke-qwen3-32b/problems/misconfig_app_hotel_res-detection-1/trajectory.json
---

# exec_shell's documented `timeout` parameter can never be passed

## Question

The first real-LLM run (qwen.qwen3-32b via the Bedrock gateway, smoke test for wiring the
model in) got `misconfig_app_hotel_res-detection-1` wrong, spending 3 of 5 steps stuck on a
parser error before submitting an incorrect answer. Was that a model failure (hallucinated
argument, poor recovery) or a harness issue?

## What we checked

- Read the full trajectory: `runs/2026-09-14T083253Z_smoke-qwen3-32b/.../trajectory.json`.
- Read `exec_shell`'s real signature and docstring (`actions/base.py:80-92`).
- Read `ResponseParser.parse_args` (`parser.py:105-172`), specifically the `is_shell_command`
  branch used only for `exec_shell`.

## Findings

The model's first action guessed the wrong service name (`get_logs("test-hotel-reservation",
"hotel-reservation")` instead of `"geo"`) — a reasonable miss, not a harness issue: nothing in
the problem description or API docs names the faulty service, and our scripted probe agent only
"knows" it's `geo` because we hardcoded it from having read the fault injector's source, which
is not available to the agent.

Recovering from that, the model tried `exec_shell`'s own documented second parameter
(`timeout (int): Timeout in seconds for the command execution. Default is 30`,
`actions/base.py:88`) three times, not two: `timeout=60`, then positional `60`, then `timeout=60`
again — it looped back to a call it had already tried. All three failed to parse with
`commands must be quoted strings`.

The parser explains why: `parse_args` special-cases `exec_shell` (`is_shell_command=True`,
`parser.py:128-143`). That branch strips an optional `command=` prefix, then requires the
*entire* remaining argument string to start and end with a single matching quote character —
there is no code path in this branch that accepts a second argument, keyword or positional. The
normal multi-argument path (`ast.parse`-based, handling positional args, keywords, lists, dicts)
is only reached when `is_shell_command=False`, i.e. for every action except `exec_shell`.

So `exec_shell`'s `timeout` parameter is not hard to use correctly — it is unreachable through
the documented calling convention, for any agent, always. Any response using it fails, and the
error message (`commands must be quoted strings`) doesn't say why in a way that points at the
real constraint (no second argument, ever), so a model can spend multiple turns retrying
variants of the same broken call, as this one did.

**A worse, silent variant.** A quoted timeout value passes the same check it shouldn't:
`exec_shell("kubectl get pods -n ns", timeout="60")` starts and ends with `"`, so
`parse_args` accepts it and strips one leading and one trailing quote, producing the single
mangled argument `kubectl get pods -n ns", timeout="60` — a broken shell command, executed as
the agent's action, with no `ResponseParsingError` at all. Confirmed directly against
`ResponseParser.parse()`: it returns normally with that mangled command rather than raising.
`exec_shell("echo a", "echo b")` mangles the same way. A trajectory scan that only counts parser
errors misses this case entirely; it has to check the action text itself.

## Decision

1. **Fixed the documentation, not one agent's prompt.** `runner/harness_fixes.py:fix_exec_shell_doc`
   strips the `timeout` line from `exec_shell`'s docstring before `runner/run_batch.py` hands
   `apis` to any agent's `init_context`. Recorded in `batch.json` as `pins.exec_shell_doc: timeout-line-removed`.
   Rejected: a "don't pass a second argument" line in one agent's system prompt only covers that
   agent, and would need identical wording duplicated into every future one (B1, B2, B3, T1) or
   introduce a prompt difference between conditions — and B1 is defined as plain prompting, so it
   can't carry a correction the others don't.
   Also rejected: patching the parser to actually accept `timeout`. That changes environment
   behaviour (agents could then run long commands) rather than just correcting documentation that
   doesn't match the environment's real, unchanged behaviour, and moves further from stock
   AIOpsLab than a doc fix does.
2. **Recorded per problem, not just fixed.** `runner/trajectory_checks.py:count_tool_call_issues`
   scans each problem's trajectory for parse errors, invalid actions, and `exec_shell` calls with
   more than one argument — detected by parsing the action text itself, which is what catches the
   silent quoted-timeout case. Written to `index.jsonl` as `tool_call_issues` per problem, so
   affected runs can be identified or controlled for instead of silently moving success rates and
   adherence denominators.

## Open

- How often this actually fires across a real batch — one occurrence so far, now trivially
  countable per batch via `tool_call_issues` in `index.jsonl`.
- Whether any other action has an `is_shell_command`-style special case with the same problem;
  `exec_shell` is the only caller of that branch today, so likely not, but unverified for future
  harness versions.
