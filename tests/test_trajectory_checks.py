"""Per-problem checks recorded in index.jsonl, without a cluster."""

import enum

import pytest

from runner.trajectory_checks import count_tool_call_issues, submitted


def _turn(role, content):
    return {"role": role, "content": content}


class _SubmissionStatus(enum.Enum):  # shaped like aiopslab.utils.status.SubmissionStatus
    VALID_SUBMISSION = 1
    INVALID_SUBMISSION = 2


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ({"final_state": _SubmissionStatus.VALID_SUBMISSION}, True),
        ({"final_state": "SubmissionStatus.VALID_SUBMISSION"}, True),  # as read back from trajectory.json
        ({"final_state": _SubmissionStatus.INVALID_SUBMISSION}, False),
        ({"final_state": "SubmissionStatus.INVALID_SUBMISSION"}, False),
        ({"final_state": "Traces data exported to: /tmp/x.csv"}, False),  # ran out of steps
        (None, False),  # problem failed before the loop finished
    ],
)
def test_submitted(results, expected):
    assert submitted(results) is expected


def test_count_tool_call_issues_on_a_clean_run():
    history = [
        _turn("assistant", 'Action:\n```\nget_logs("ns", "geo")\n```'),
        _turn("env", "some logs"),
        _turn("assistant", 'Action:\n```\nget_metrics("ns", 5)\n```'),
        _turn("env", "some metrics"),
        _turn("assistant", 'Action:\n```\nsubmit("Yes")\n```'),
        _turn("env", "1"),
    ]
    assert count_tool_call_issues(history) == {
        "parse_errors": 0,
        "invalid_actions": 0,
        "exec_shell_extra_args": 0,
    }


def test_count_tool_call_issues_counts_parse_errors_and_invalid_actions():
    history = [
        _turn("assistant", "not an action at all"),
        _turn("env", "Error parsing response: No API call found!"),
        _turn("assistant", 'Action:\n```\nfly_to_the_moon("now")\n```'),
        _turn("env", "Invalid action: fly_to_the_moon"),
    ]
    counts = count_tool_call_issues(history)
    assert counts["parse_errors"] == 1
    assert counts["invalid_actions"] == 1


def test_count_tool_call_issues_catches_the_silent_quoted_timeout_case():
    """exec_shell(..., timeout="60") parses without error, so only the action text reveals it."""
    history = [
        _turn("assistant", 'Action:\n```\nexec_shell("kubectl get pods -n ns", timeout=60)\n```'),
        _turn("env", "Error parsing response: Error when parsing response: commands must be quoted strings"),
        _turn("assistant", 'Action:\n```\nexec_shell("kubectl get pods -n ns", timeout="60")\n```'),
        _turn("env", "kubectl error: unknown flag or bad command"),  # no parser error at all
    ]
    counts = count_tool_call_issues(history)
    assert counts["parse_errors"] == 1
    assert counts["exec_shell_extra_args"] == 2


def test_count_tool_call_issues_does_not_flag_other_multi_arg_actions():
    history = [_turn("assistant", 'Action:\n```\nget_metrics("ns", 5)\n```')]
    assert count_tool_call_issues(history) == {
        "parse_errors": 0,
        "invalid_actions": 0,
        "exec_shell_extra_args": 0,
    }
