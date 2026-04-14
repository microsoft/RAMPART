# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from rampart.core.injection import InjectionHandle


class _ConcreteHandle(InjectionHandle):
    """Minimal concrete handle that inherits the default wait_until_ready."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        readiness_timeout: float = 30.0,
    ) -> None:
        self._delay = delay
        self._readiness_timeout = readiness_timeout

    @property
    def indexing_delay_seconds(self) -> float:
        return self._delay

    @property
    def readiness_timeout_seconds(self) -> float:
        return self._readiness_timeout

    @property
    def payload_id(self) -> str | None:
        return "test-payload"

    @property
    def surface_name(self) -> str:
        return "TestSurface"

    async def __aenter__(self) -> _ConcreteHandle:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        pass


class TestWaitUntilReady:
    """Tests for InjectionHandle.wait_until_ready default and custom behaviour."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("delay", "readiness_timeout"),
        [
            (0.0, 1.0),
            (0.05, 5.0),
        ],
        ids=["zero-delay", "short-delay-within-timeout"],
    )
    async def test_default_completes_when_delay_within_timeout(
        self, delay: float, readiness_timeout: float
    ) -> None:
        """Default sleep-based wait completes when delay is within the timeout."""
        handle = _ConcreteHandle(delay=delay, readiness_timeout=readiness_timeout)

        await handle.wait_until_ready()

    @pytest.mark.asyncio
    async def test_custom_polling_implementation(self) -> None:
        """A handle can override wait_until_ready with custom polling logic."""
        poll_mock = AsyncMock(side_effect=[False, False, True])

        class _PollingHandle(_ConcreteHandle):
            async def wait_until_ready(self) -> None:
                async with asyncio.timeout(self.readiness_timeout_seconds):
                    while not await poll_mock():
                        await asyncio.sleep(0)

        handle = _PollingHandle(readiness_timeout=5.0)

        await handle.wait_until_ready()

        assert poll_mock.await_count == 3

    @pytest.mark.asyncio
    async def test_timeout_raises_when_delay_exceeds_limit(self) -> None:
        """Default implementation raises TimeoutError when delay exceeds timeout."""
        handle = _ConcreteHandle(delay=10.0, readiness_timeout=0.01)

        with pytest.raises(TimeoutError):
            await handle.wait_until_ready()
