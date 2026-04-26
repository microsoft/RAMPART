# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.injection — InjectionHandle, Surface, sleep_until_ready."""

import types
from typing import Self

import pytest

from rampart.core.injection import InjectionHandle, Surface, sleep_until_ready
from rampart.core.types import Payload


class TestInjectionHandleProtocol:
    def test_conforming_class_satisfies_protocol(self) -> None:
        class MyHandle:
            @property
            def payload_id(self) -> str | None:
                return "abc"

            @property
            def surface_name(self) -> str:
                return "SharePoint"

            async def wait_until_ready(self) -> None:
                pass

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

    def test_non_conforming_class_rejected(self) -> None:
        class NotHandle:
            pass

        assert not isinstance(NotHandle(), InjectionHandle)


class TestSurfaceProtocol:
    def test_conforming_class_satisfies_protocol(self) -> None:
        class MyHandle:
            @property
            def payload_id(self) -> str | None:
                return None

            @property
            def surface_name(self) -> str:
                return "test"

            async def wait_until_ready(self) -> None:
                pass

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


class TestSleepUntilReady:
    @pytest.mark.asyncio
    async def test_completes_without_error_async(self) -> None:
        await sleep_until_ready(0.0)
