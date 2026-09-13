"""Deterministic scripted probe agent for the Day-1 scoring-surface audit.

Not an LLM. No AWS/Bedrock or other LLM credentials are available in this
environment (see CLAUDE.md), so this fixed, seedless action sequence stands
in for the real reference agent purely to exercise AIOpsLab end to end:
deploy -> inject fault -> observe -> submit -> evaluate -> recover. Its only
job is to answer the three scoring-surface audit questions from the Day 1
plan (tool-call recoverability, seed reproducibility, problem-ID/fault-type
mapping). It must not be mistaken for a policy-adherence baseline.

Running this file is a shortcut for a batch of one through agents/run_batch.py:

    python agents/run_batch.py --problems <id> --condition <label> \
        --agent scripted-probe --max-steps 5

third_party/aiopslab is vendored unmodified; this script lives outside it and
only imports from it.
"""

import argparse
import re
import sys


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


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Run the scripted probe on one problem as a batch of one.")
    p.add_argument("--problem-id", default="misconfig_app_hotel_res-detection-1")
    p.add_argument("--max-steps", type=int, default=5)
    p.add_argument("--condition", "--run-tag", dest="condition", default="scripted-probe",
                   help="batch label under runs/ (--run-tag is the old name)")
    args = p.parse_args()

    # Imported here, not at the top: run_batch loads this module by name to get the agent.
    from run_batch import main

    sys.exit(main([
        "--problems", args.problem_id,
        "--condition", args.condition,
        "--agent", "scripted-probe",
        "--max-steps", str(args.max_steps),
    ]))
