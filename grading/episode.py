"""An episode as the grader sees it: the actions the harness ran, and what each one did.

Actions come from the harness's own ResponseParser, the code that decided what ran, so the grader
can't credit or blame something the harness never dispatched.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from aiopslab.orchestrator.parser import ResponseParser
from aiopslab.utils.status import ResponseParsingError

from grading.shell import Command, parse_line

# From third_party/aiopslab/aiopslab/service/metadata/*.json.
APP_NAMESPACES = {
    "HotelReservation": "test-hotel-reservation",
    "SocialNetwork": "test-social-network",
    "AstronomyShop": "astronomy-shop",
    "Flower": "flower",
}
TASK_KINDS = {"detection": "diagnosis", "localization": "diagnosis", "analysis": "diagnosis",
              "mitigation": "mitigation"}


@dataclass
class Action:
    """One parsed action and the environment's reply to it."""

    step: int
    api: str
    args: list
    thought: str
    reply: str
    outcome: str                                   # ran | shell error | blocked | api error | parse failure
    commands: list[Command] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return self.outcome == "ran"


@dataclass
class Episode:
    problem_id: str
    condition: str
    task: str                                      # diagnosis | mitigation
    namespace: str | None
    actions: list[Action]
    parse_failures: int
    termination_reason: str
    success: object
    path: str = ""


def classify(reply: str) -> str:
    if reply.startswith("Error parsing response") or "Format validation failure" in reply[:200]:
        return "parse failure"
    if reply.startswith("Error: Cannot use"):
        return "blocked"
    if reply.startswith("[ERROR] Docker command execution failed"):
        return "shell error"
    if reply.startswith("Error"):
        return "api error"
    return "ran"


def _task_and_namespace(problem_id: str, app_by_problem: dict[str, str]) -> tuple[str, str | None]:
    task = next((TASK_KINDS[t] for t in TASK_KINDS if f"-{t}-" in problem_id), "")
    return task, APP_NAMESPACES.get(app_by_problem.get(problem_id, ""))


def load(path: str | Path, app_by_problem: dict[str, str]) -> Episode:
    data = json.loads(Path(path).read_text())
    history = data.get("history") or []
    parser = ResponseParser()
    actions, parse_failures, step = [], 0, 0
    for i, message in enumerate(history):
        if message.get("role") != "assistant":
            continue
        reply = str(history[i + 1]["content"]) if i + 1 < len(history) else ""
        outcome = classify(reply)
        if outcome == "parse failure":
            parse_failures += 1
            continue
        step += 1
        try:
            parsed = parser.parse(message["content"])
        except (ResponseParsingError, ValueError):
            parse_failures += 1
            continue
        action = Action(step=step, api=parsed["api_name"], args=list(parsed["args"]),
                        thought=message["content"].split("```")[0].strip(), reply=reply, outcome=outcome)
        if action.api == "exec_shell" and action.args:
            action.commands = parse_line(str(action.args[0]))
        actions.append(action)
    task, namespace = _task_and_namespace(data["problem_id"], app_by_problem)
    results = (data.get("results") or {}).get("results") or {}
    return Episode(problem_id=data["problem_id"], condition=data.get("condition", ""), task=task,
                   namespace=namespace, actions=actions, parse_failures=parse_failures,
                   termination_reason=data.get("termination_reason", ""),
                   success=results.get("success", results.get("Localization Accuracy")), path=str(path))
