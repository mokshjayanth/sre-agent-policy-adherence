"""Deterministic scripted probe agent for the Day-1 scoring-surface audit.

Not an LLM. Written before any LLM credentials were set up, this fixed,
seedless action sequence stands in for a real agent purely to exercise
AIOpsLab end to end: deploy -> inject fault -> observe -> submit -> evaluate ->
recover. It must not be mistaken for a policy-adherence baseline.

Run it through the batch runner:

    python -m runner.run_batch --problems <id> --condition smoke-scripted \
        --agent scripted-probe --max-steps 5
"""

import re


class ScriptedProbeAgent:
    """Fixed action sequence, no randomness: get_logs -> get_metrics -> submit."""

    def __init__(self, submit_value: str = "Yes"):
        self.step = 0
        self.namespace = None
        self.faulty_service = None
        self.submit_value = submit_value

    @classmethod
    def describe(cls) -> dict:
        """What batch.json records about this agent."""
        return {
            "kind": "scripted, not an LLM",
            "sequence": ['get_logs(<namespace>, "geo")', "get_metrics(<namespace>, 5)", 'submit("Yes")'],
        }

    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        self.problem_desc = problem_desc
        self.apis = apis
        ns_match = re.search(r"Namespace:\s*([\w-]+)", problem_desc)
        self.namespace = ns_match.group(1) if ns_match else "test-hotel-reservation"
        # Not derivable from problem_desc in general; overridden by caller for
        # problems where the faulty service is known ahead of time.
        self.faulty_service = "geo"

    async def get_action(self, observation: str) -> str:
        self.step += 1
        if self.step == 1:
            return f'Action:\n```\nget_logs("{self.namespace}", "{self.faulty_service}")\n```'
        if self.step == 2:
            return f'Action:\n```\nget_metrics("{self.namespace}", 5)\n```'
        return f'Action:\n```\nsubmit("{self.submit_value}")\n```'
