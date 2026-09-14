"""Checks computed from a finished problem and recorded per problem in index.jsonl.

Recording only: nothing here changes what an agent sees or how the harness
grades it. Deviations from stock AIOpsLab live in runner/harness_fixes.py.
"""

import ast
import re

_CODEBLOCK = re.compile(r"```\s*\n(.*?)\n```", re.DOTALL)


INVALID_SUBMISSION_ERROR = "ValueError: Invalid submission!"


def final_submission_state(results: dict | None) -> str | None:
    """The harness's final_state reduced to a submission status name, or None.

    The harness sets final_state to its last env response (orchestrator.py:227):
    a SubmissionStatus after a submit, but the raw last observation, such as a
    metrics CSV, when the step budget ran out. That observation is already the
    last entry of the trajectory's history.
    """
    state = (results or {}).get("final_state")
    name = getattr(state, "name", None)
    if name is None and isinstance(state, str) and state.startswith("SubmissionStatus."):
        name = state.removeprefix("SubmissionStatus.")
    return name


def submitted(results: dict | None) -> bool:
    """Whether the episode ended with a valid submission.

    False when the agent ran out of steps, which the harness still grades (a
    detection problem with no answer is scored "Invalid Format"), or when the
    problem failed before the loop finished.
    """
    return final_submission_state(results) == "VALID_SUBMISSION"


def termination_reason(error: str | None, results: dict | None) -> str:
    """Why an episode ended: valid_submission, step_limit, invalid_submission or error.

    The harness's loop stops on a valid submission, raises
    ValueError("Invalid submission!") on an invalid one, which skips grading,
    and otherwise runs until max_steps (orchestrator.py:160-173). Parse errors
    never end an episode: they use up a step and are counted by
    count_tool_call_issues. `error` is the runner's "<type>: <message>" for a
    failed attempt, so "error" also covers setup failures and model API errors.
    """
    if error is None:
        return "valid_submission" if submitted(results) else "step_limit"
    if error == INVALID_SUBMISSION_ERROR:
        return "invalid_submission"
    return "error"


# Parse failures and invalid actions are turns an agent spent without being able
# to act, which both lowers success rate and shrinks the number of actions in
# which a policy violation could occur -- worth recording per problem rather
# than only visible by reading a trajectory by hand.


def _exec_shell_arg_count(action_text: str) -> int | None:
    """Number of top-level arguments in an exec_shell(...) call in `action_text`.

    None if the action isn't a call to exec_shell at all (including malformed
    text with no code block, which the parser rejects for its own reasons).
    """
    match = _CODEBLOCK.search(action_text)
    if not match:
        return None
    code = match.group(1).strip()
    if not code.startswith("exec_shell("):
        return None
    try:
        call = ast.parse(code, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(call, ast.Call):
        return None
    return len(call.args) + len(call.keywords)


def count_tool_call_issues(history: list[dict]) -> dict:
    """Counts of parse errors, invalid actions and extra-argument exec_shell calls.

    The last one exists because a quoted timeout (`exec_shell("cmd",
    timeout="60")`) parses without error into a mangled command -- it never
    raises, so it wouldn't show up by counting error turns alone.
    """
    parse_errors = sum(
        1 for h in history if h.get("role") == "env" and h.get("content", "").startswith("Error parsing response:")
    )
    invalid_actions = sum(
        1 for h in history if h.get("role") == "env" and h.get("content", "").startswith("Invalid action:")
    )
    exec_shell_extra_args = sum(
        1
        for h in history
        if h.get("role") == "assistant" and (_exec_shell_arg_count(h.get("content", "")) or 0) > 1
    )
    return {
        "parse_errors": parse_errors,
        "invalid_actions": invalid_actions,
        "exec_shell_extra_args": exec_shell_extra_args,
    }
