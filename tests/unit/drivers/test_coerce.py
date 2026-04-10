# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for _coerce_driver."""

from __future__ import annotations

import pytest

from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Request, Response, Turn
from rampart.drivers import _coerce_driver
from rampart.drivers.static import StaticDriver


class TestCoerceString:
    """_coerce_driver accepts a str as a single-prompt driver."""

    @pytest.mark.asyncio
    async def test_str_produces_single_prompt_driver_async(self) -> None:
        driver = _coerce_driver("hello")

        d0 = await driver.next_prompt_async(history=[])
        assert d0 is not None
        assert d0.request.prompt == "hello"

        d1 = await driver.next_prompt_async(
            history=[
                Turn(request=Request(prompt="hello"), response=Response(text="ok")),
            ],
        )
        assert d1 is None


class TestCoerceList:
    """_coerce_driver accepts list[str] as a multi-prompt driver."""

    @pytest.mark.asyncio
    async def test_list_produces_multi_prompt_driver_async(self) -> None:
        driver = _coerce_driver(["a", "b"])

        d0 = await driver.next_prompt_async(history=[])
        assert d0 is not None
        assert d0.request.prompt == "a"


class TestCoercePassthrough:
    """_coerce_driver passes through an existing PromptDriver unchanged."""

    @pytest.mark.asyncio
    async def test_prompt_driver_passthrough_async(self) -> None:
        original = StaticDriver(prompts=["x"])
        result = _coerce_driver(original)
        assert result is original

    @pytest.mark.asyncio
    async def test_custom_driver_passthrough_async(self) -> None:
        class Custom:
            async def next_prompt_async(
                self,
                *,
                history: list[Turn],
            ) -> PromptDecision | None:
                return PromptDecision(request=Request(prompt="custom"))

        custom = Custom()
        result = _coerce_driver(custom)  # type: ignore[arg-type]
        assert result is custom
