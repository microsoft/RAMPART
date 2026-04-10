# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Session and AgentAdapter protocols.

These are the two protocols that product teams implement to connect
their agent to the RAMPART framework.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    import types

    from rampart.core.manifest import AppManifest
    from rampart.core.types import ObservabilityLevel, Request, Response


@runtime_checkable
class Session(Protocol):
    """A bounded unit of interaction with the agent.

    Sessions are async context managers. Entering returns the session
    ready for use; exiting guarantees cleanup of any resources the
    adapter holds (API clients, browser contexts, temporary state).

    Fresh state = fresh session. Create a new one via the adapter.
    """

    async def send_async(self, request: Request) -> Response:
        """Send a request to the agent and return its response.

        The adapter is responsible for populating Response.tool_calls
        and Response.side_effects with whatever it can observe. Empty
        lists are valid — they mean "no observations," not "nothing
        happened." The evaluator system distinguishes between these.

        Args:
            request (Request): The prompt and/or attachments to send.

        Returns:
            Response: The agent's response with all observable data.
        """
        ...

    async def __aenter__(self) -> Self:
        """Enter the session context. Returns self."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Clean up session resources. Must be idempotent."""
        ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Factory for sessions and source of agent metadata.

    Teams implement this to describe their agent and create
    interaction sessions. The manifest declares what the agent
    can do; sessions let the framework interact with it.
    """

    async def create_session_async(self) -> Session:
        """Create a fresh interaction session.

        Each session is independent — no shared conversation state.
        Creating a new session is how the framework achieves
        conversation reset for persistence testing.

        Returns:
            Session: A new session ready for interaction.
        """
        ...

    @property
    def manifest(self) -> AppManifest:
        """The agent's declared capabilities.

        Returns:
            AppManifest: The agent's capability declaration.
        """
        ...

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """Declares what this adapter can reliably observe.

        Used by evaluators to distinguish "nothing happened" from
        "I can't see what happened."

        Returns:
            ObservabilityLevel: What the adapter can observe.
        """
        ...
