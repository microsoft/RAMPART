# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for runtime-checkable protocol compliance via structural subtyping.

Verifies that plain classes with the right methods satisfy isinstance checks
for Session, AgentAdapter, Surface, InjectionHandle, and PromptDriver — without
inheriting from the protocol.
"""

import types
from typing import Self

from rampart.core.adapter import AgentAdapter, Session
from rampart.core.injection import InjectionHandle, Surface
from rampart.core.manifest import AppManifest
from rampart.core.prompt_driver import PromptDecision, PromptDriver
from rampart.core.types import ObservabilityLevel, Payload, Request, Response, Turn


class TestSessionProtocol:
    def test_structural_subtyping(self) -> None:
        class MySession:
            async def send_async(self, request: Request) -> Response:
                return Response(text="ok")

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: types.TracebackType | None,
            ) -> None:
                pass

        assert isinstance(MySession(), Session)

    def test_send_async_accepts_request(self) -> None:
        """Verify the protocol requires a Request parameter."""

        class MySession:
            async def send_async(self, request: Request) -> Response:
                return Response(text="ok")

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: types.TracebackType | None,
            ) -> None:
                pass

        session = MySession()
        assert isinstance(session, Session)


class TestAgentAdapterProtocol:
    def test_structural_subtyping(self) -> None:
        class MyAdapter:
            async def create_session_async(self) -> Session: ...

            @property
            def manifest(self) -> AppManifest:
                return AppManifest(name="Test")

            @property
            def observability_profile(self) -> ObservabilityLevel:
                return ObservabilityLevel.TOOL_ONLY

        assert isinstance(MyAdapter(), AgentAdapter)


class TestInjectionHandleProtocol:
    def test_structural_subtyping(self) -> None:
        class MyHandle:
            @property
            def indexing_delay_seconds(self) -> float:
                return 5.0

            @property
            def payload_id(self) -> str | None:
                return "abc"

            @property
            def surface_name(self) -> str:
                return "SharePoint"

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: types.TracebackType | None,
            ) -> None:
                pass

        assert isinstance(MyHandle(), InjectionHandle)


class TestSurfaceProtocol:
    def test_structural_subtyping(self) -> None:
        class MyHandle:
            @property
            def indexing_delay_seconds(self) -> float:
                return 0.0

            @property
            def payload_id(self) -> str | None:
                return None

            @property
            def surface_name(self) -> str:
                return "test"

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc_val: BaseException | None,
                exc_tb: types.TracebackType | None,
            ) -> None:
                pass

        class MySurface:
            def inject(self, *, payload: Payload) -> MyHandle:
                return MyHandle()

        assert isinstance(MySurface(), Surface)


class TestPromptDriverProtocol:
    def test_structural_subtyping(self) -> None:
        class MyDriver:
            async def next_prompt_async(
                self,
                *,
                history: list[Turn],
            ) -> PromptDecision | None:
                return None

        assert isinstance(MyDriver(), PromptDriver)


class TestRequest:
    def test_construction_with_prompt(self) -> None:
        r = Request(prompt="hello")
        assert r.prompt == "hello"
        assert r.attachments == []

    def test_with_attachments_only(self) -> None:
        p = Payload(content="test")
        r = Request(attachments=[p])
        assert r.prompt is None
        assert r.attachments == [p]

    def test_empty_request_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="at least"):
            Request()
