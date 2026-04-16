# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.injection."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self
from unittest.mock import AsyncMock

import pytest

from rampart.core.injection import InjectionHandleMixin

if TYPE_CHECKING:
    import types


class _ConcreteHandle(InjectionHandleMixin):
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

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        pass


class TestWaitUntilReady:
    """Tests for InjectionHandleMixin.wait_until_ready default and custom behaviour."""

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
        self,
        delay: float,
        readiness_timeout: float,
    ) -> None:
        """Default sleep-based wait completes when delay is within the timeout."""
        handle = _ConcreteHandle(delay=delay, readiness_timeout=readiness_timeout)

        await handle.wait_until_ready()

    @pytest.mark.asyncio
    async def test_custom_polling_implementation(self) -> None:
        """A handle can override wait_until_ready with custom polling logic."""
        _expected_poll_calls = 3
        poll_mock = AsyncMock(side_effect=[False, False, True])
        ready_event = asyncio.Event()

        class _PollingHandle(_ConcreteHandle):
            async def wait_until_ready(self) -> None:
                async with asyncio.timeout(self.readiness_timeout_seconds):
                    while not await poll_mock():
                        ready_event.clear()
                        await ready_event.wait()

        handle = _PollingHandle(readiness_timeout=5.0)

        async def _signal_ready() -> None:
            for _ in range(_expected_poll_calls - 1):
                await asyncio.sleep(0)
                ready_event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(handle.wait_until_ready())
            tg.create_task(_signal_ready())

        assert poll_mock.await_count == _expected_poll_calls

    @pytest.mark.asyncio
    async def test_timeout_raises_when_delay_exceeds_limit(self) -> None:
        """Default implementation raises TimeoutError when delay exceeds timeout."""
        handle = _ConcreteHandle(delay=10.0, readiness_timeout=0.01)

        with pytest.raises(TimeoutError):
            await handle.wait_until_ready()
