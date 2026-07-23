# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.adapter — Session and AgentAdapter protocols."""

import types
from typing import Self

from rampart.core.adapter import AgentAdapter, Session
from rampart.core.manifest import AppManifest
from rampart.core.types import ObservabilityLevel, Request, Response


class TestSessionProtocolCheck:
    def test_conforming_class_satisfies_protocol(self) -> None:
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

    def test_non_conforming_class_rejected(self) -> None:
        class NotSession:
            pass

        assert not isinstance(NotSession(), Session)


class TestAgentAdapterProtocolCheck:
    def test_conforming_class_satisfies_protocol(self) -> None:
        class MyAdapter:
            async def create_session_async(self) -> Session:
                raise NotImplementedError

            @property
            def manifest(self) -> AppManifest:
                return AppManifest(name="Test")

            @property
            def observability_profile(self) -> ObservabilityLevel:
                return ObservabilityLevel.RESPONSE_ONLY

        assert isinstance(MyAdapter(), AgentAdapter)

    def test_non_conforming_class_rejected(self) -> None:
        class NotAdapter:
            pass

        assert not isinstance(NotAdapter(), AgentAdapter)
