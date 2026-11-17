"""Exercise the installed graph API through its public Runner boundary."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from google.adk import Runner
from google.adk.agents.context import Context
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import START, BaseNode, Edge, Workflow


class First(BaseNode):
    async def _run_impl(
        self, *, ctx: Context, node_input: Any
    ) -> AsyncGenerator[Any, None]:
        ctx.state["temp:prepared"] = {"value": 21}
        ctx.route = "next"
        yield {"value": 21}


class Second(BaseNode):
    async def _run_impl(
        self, *, ctx: Context, node_input: Any
    ) -> AsyncGenerator[Any, None]:
        assert node_input == {"value": 21}
        assert ctx.state["temp:prepared"] == node_input
        yield {"answer": node_input["value"] * 2}


def test_workflow_runner_handoff() -> None:
    async def execute() -> list[object]:
        first, second = First(name="first"), Second(name="second")
        workflow = Workflow(
            name="smoke",
            edges=[(START, first), Edge(from_node=first, to_node=second, route="next")],
        )
        service = InMemorySessionService()
        session = await service.create_session(app_name="smoke", user_id="local")
        runner = Runner(app_name="smoke", node=workflow, session_service=service)
        try:
            return [
                event.output
                async for event in runner.run_async(
                    user_id="local", session_id=session.id, state_delta={"start": True}
                )
                if event.output is not None
            ]
        finally:
            await runner.close()

    assert asyncio.run(execute())[-1] == {"answer": 42}
