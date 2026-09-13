"""Agent implementations.

Each agent exposes `init_context(problem_desc, instructions, apis)` and
`async get_action(observation) -> str`. The runner loads agents by name from
`runner.run_batch.AGENTS`; agents never import the runner.
"""
