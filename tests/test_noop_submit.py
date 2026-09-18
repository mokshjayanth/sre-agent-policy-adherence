"""The no-fix baseline agent only ever submits."""

import asyncio

from aiopslab.orchestrator.parser import ResponseParser

from agents.noop_submit import NoopSubmitAgent


def test_noop_agent_submits_with_no_arguments_every_time():
    agent = NoopSubmitAgent()
    agent.init_context("PROBLEM", "INSTRUCTIONS", {})
    for _ in range(2):
        parsed = ResponseParser().parse(asyncio.run(agent.get_action("obs")))
        assert (parsed["api_name"], parsed["args"], parsed["kwargs"]) == ("submit", [], {})
