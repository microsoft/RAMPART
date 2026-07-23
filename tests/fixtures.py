# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Mock fixtures for testing adapters and evaluators.

Provides MockSession and MockAdapter as minimal deterministic test
doubles aligned with the Session and AgentAdapter protocol contracts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, cast

from rampart.core.types import ObservabilityLevel, Request, Response

if TYPE_CHECKING:
    import types

    from rampart.core.manifest import AppManifest


class MockSession:
    """Mock session that returns preconfigured responses.

    For testing evaluators and adapter logic without a live agent.

    Args:
        responses (list[Response]): Responses to return in order. Cycles if exhausted.
    """

    def __init__(self, *, responses: list[Response]) -> None:
        if not responses:
            raise ValueError("MockSession requires at least one response.")
        self._responses = responses
        self._index = 0

    async def send_async(self, request: Request) -> Response:
        """Return the next preconfigured response.

        Args:
            request (Request): The request (ignored by mock).

        Returns:
            Response: The next preconfigured response, cycling if exhausted.
        """
        response = self._responses[self._index % len(self._responses)]
        self._index += 1
        return response

    async def __aenter__(self) -> Self:
        """No-op for mock sessions."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """No-op for mock sessions."""


class MockAdapter:
    """Mock adapter with configurable per-session response sequences.

    Accepts either a flat list of responses (all sessions return the
    same sequence) or a list of lists (each session gets its own
    sequence). The second form is essential for persistence testing,
    where session 1 must return attack-compromised responses and
    session 2 must return clean responses.

    Args:
        responses (list[Response] | list[list[Response]]): Response
            sequences. A flat list gives every session the same
            responses. A nested list gives each successive
            create_session_async call its own sequence. When the
            nested list is exhausted, subsequent sessions cycle
            back to the last entry.
        manifest (AppManifest): The agent manifest.
        observability_profile (ObservabilityLevel): What the mock
            adapter observes.

    Raises:
        ValueError: If responses is empty.
    """

    def __init__(
        self,
        *,
        responses: list[Response] | list[list[Response]],
        manifest: AppManifest,
        observability_profile: ObservabilityLevel = (
            ObservabilityLevel.TOOL_AND_SIDE_EFFECTS
        ),
    ) -> None:
        if not responses:
            raise ValueError("MockAdapter requires at least one response sequence.")

        if all(isinstance(r, list) for r in responses) and all(
            isinstance(r, Response)
            for sublist in cast("list[list[Any]]", responses)
            for r in sublist
        ):
            self._session_responses = cast("list[list[Response]]", responses)
        else:
            self._session_responses = [cast("list[Response]", responses)]
        self._manifest_value = manifest
        self._observability_profile_value = observability_profile
        self._session_index = 0

    async def create_session_async(self) -> MockSession:
        """Create a mock session with the next response sequence.

        Each call advances to the next entry in the session responses
        list. When the list is exhausted, cycles back to the last entry.

        Returns:
            MockSession: A new session with preconfigured responses.
        """
        idx = min(self._session_index, len(self._session_responses) - 1)
        session = MockSession(responses=self._session_responses[idx])
        self._session_index += 1
        return session

    @property
    def manifest(self) -> AppManifest:
        """Configured manifest."""
        return self._manifest_value

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """Configured observability level."""
        return self._observability_profile_value
