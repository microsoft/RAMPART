# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for coerce_driver."""

from __future__ import annotations

from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Request, Response, Turn
from rampart.drivers._utils import coerce_driver
from rampart.drivers.static import StaticDriver


class TestCoerceString:
    """coerce_driver accepts a str as a single-prompt driver."""

    async def test_str_produces_single_prompt_driver_async(self) -> None:
        driver = coerce_driver("hello")

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
    """coerce_driver accepts list[str] as a multi-prompt driver."""

    async def test_list_produces_multi_prompt_driver_async(self) -> None:
        driver = coerce_driver(["a", "b"])

        d0 = await driver.next_prompt_async(history=[])
        assert d0 is not None
        assert d0.request.prompt == "a"


class TestCoercePassthrough:
    """coerce_driver passes through an existing PromptDriver unchanged."""

    async def test_prompt_driver_passthrough_async(self) -> None:
        original = StaticDriver(prompts=["x"])
        result = coerce_driver(original)
        assert result is original

    async def test_custom_driver_passthrough_async(self) -> None:
        class Custom:
            async def next_prompt_async(
                self,
                *,
                history: list[Turn],
            ) -> PromptDecision | None:
                return PromptDecision(request=Request(prompt="custom"))

        custom = Custom()
        result = coerce_driver(custom)
        assert result is custom
