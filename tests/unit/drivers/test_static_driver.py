# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for StaticDriver."""

from __future__ import annotations

from rampart.core.prompt_driver import PromptDriver
from rampart.core.types import Request, Response, Turn
from rampart.drivers.static import StaticDriver


def _turn(prompt: str) -> Turn:
    """Build a minimal Turn for history."""
    return Turn(request=Request(prompt=prompt), response=Response(text="ok"))


class TestStaticDriverSequence:
    """StaticDriver returns prompts in order based on history length."""

    async def test_returns_prompts_in_order_async(self) -> None:
        driver = StaticDriver(prompts=["first", "second", "third"])

        d0 = await driver.next_prompt_async(history=[])
        assert d0 is not None
        assert d0.request.prompt == "first"

        d1 = await driver.next_prompt_async(history=[_turn("first")])
        assert d1 is not None
        assert d1.request.prompt == "second"

        d2 = await driver.next_prompt_async(
            history=[_turn("first"), _turn("second")],
        )
        assert d2 is not None
        assert d2.request.prompt == "third"

    async def test_returns_none_when_exhausted_async(self) -> None:
        driver = StaticDriver(prompts=["only"])

        result = await driver.next_prompt_async(history=[_turn("only")])
        assert result is None

    async def test_reasoning_is_empty_async(self) -> None:
        driver = StaticDriver(prompts=["hello"])

        decision = await driver.next_prompt_async(history=[])
        assert decision is not None
        assert decision.reasoning == ""
        assert decision.request.prompt == "hello"


class TestStaticDriverStateless:
    """Same StaticDriver instance behaves correctly for different histories."""

    async def test_same_instance_different_histories_async(self) -> None:
        driver = StaticDriver(prompts=["a", "b", "c"])

        d_empty = await driver.next_prompt_async(history=[])
        assert d_empty is not None
        assert d_empty.request.prompt == "a"

        d_two = await driver.next_prompt_async(
            history=[_turn("a"), _turn("b")],
        )
        assert d_two is not None
        assert d_two.request.prompt == "c"

        d_empty_again = await driver.next_prompt_async(history=[])
        assert d_empty_again is not None
        assert d_empty_again.request.prompt == "a"


class TestStaticDriverProtocol:
    """StaticDriver satisfies the PromptDriver protocol."""

    def test_satisfies_prompt_driver(self) -> None:
        driver = StaticDriver(prompts=["x"])
        assert isinstance(driver, PromptDriver)
