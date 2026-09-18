"""Calls submit() at once and does nothing else: a no-fix baseline for mitigation problems.

A problem's success check is informative only if this agent fails it: mitigation
grading checks the cluster's end state, so a check that passes with no fix can't
tell a repaired service from an untouched one. Not an LLM and not a condition of
the study.

    python -m runner.run_batch --task mitigation --condition validation-noop \
        --agent noop-submit --max-steps 3
"""


class NoopSubmitAgent:
    @classmethod
    def describe(cls) -> dict:
        """What batch.json records about this agent."""
        return {"kind": "scripted, not an LLM", "sequence": ["submit()"]}

    def init_context(self, problem_desc: str, instructions: str, apis: dict):
        pass

    async def get_action(self, observation: str) -> str:
        return "Action:\n```\nsubmit()\n```"
