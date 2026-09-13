"""Deterministic scripted probe agent for the Day-1 scoring-surface audit.

Not an LLM. No AWS/Bedrock or other LLM credentials are available in this
environment (see CLAUDE.md), so this fixed, seedless action sequence stands
in for the real reference agent purely to exercise AIOpsLab end to end:
deploy -> inject fault -> observe -> submit -> evaluate -> recover. Its only
job is to answer the three scoring-surface audit questions from the Day 1
plan (tool-call recoverability, seed reproducibility, problem-ID/fault-type
mapping). It must not be mistaken for a policy-adherence baseline.

third_party/aiopslab is vendored unmodified; this script lives outside it and
only imports from it.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AIOPSLAB_ROOT = REPO_ROOT / "third_party" / "aiopslab"
sys.path.insert(0, str(AIOPSLAB_ROOT))

from aiopslab.orchestrator import Orchestrator  # noqa: E402

from run_manifest import collect_static_manifest, collect_cluster_images  # noqa: E402
from pin_otel_chart import apply_pin as apply_otel_chart_pin  # noqa: E402

apply_otel_chart_pin()


class ScriptedProbeAgent:
    """Fixed action sequence, no randomness: get_logs -> get_metrics -> submit."""

    def __init__(self, submit_value: str = "Yes"):
        self.step = 0
        self.namespace = None
        self.faulty_service = None
        self.submit_value = submit_value

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


async def run(problem_id: str, max_steps: int, run_tag: str) -> dict:
    manifest = collect_static_manifest()

    orch = Orchestrator()
    agent = ScriptedProbeAgent()
    orch.register_agent(agent, name="scripted-probe")

    problem_desc, instructions, apis = orch.init_problem(problem_id)
    agent.init_context(problem_desc, instructions, apis)

    # Deploy + fault injection + workload start have all happened by the time
    # init_problem() returns, so the pods exist here. Capture image digests
    # across every namespace now: the app's pods are gone after teardown, and
    # the wrk2 Job in `default` is re-pulled on every run.
    manifest["pod_images"] = collect_cluster_images(manifest["cluster"]["kube_context"])

    results = await orch.start_problem(max_steps=max_steps)

    out_dir = REPO_ROOT / "runs" / run_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "problem_id": problem_id,
        "session_id": str(orch.session.session_id),
        "agent_name": orch.agent_name,
        "solution": orch.session.solution,
        "results": results,
        "history": [item.model_dump() for item in orch.session.history],
    }
    (out_dir / "trajectory.json").write_text(json.dumps(record, indent=2, default=str))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(json.dumps(record, indent=2, default=str))
    return record


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--problem-id", default="misconfig_app_hotel_res-detection-1")
    p.add_argument("--max-steps", type=int, default=5)
    p.add_argument("--run-tag", required=True)
    args = p.parse_args()
    asyncio.run(run(args.problem_id, args.max_steps, args.run_tag))
