# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.response_contains — ResponseContains evaluator."""

import re

import pytest

from rampart.core.types import EvalContext, EvalOutcome, Request, Response, Turn
from rampart.evaluators import ResponseContains


def _ctx(text: str) -> EvalContext:
    """Build a single-turn EvalContext with the given response text."""
    return EvalContext(
        turns=[Turn(request=Request(prompt="test"), response=Response(text=text))],
    )


class TestResponseContainsSubstring:
    @pytest.mark.asyncio
    async def test_case_insensitive_by_default(self) -> None:
        result = await ResponseContains("HELLO").evaluate_async(
            context=_ctx("hello world"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_case_sensitive_opt_in(self) -> None:
        result = await ResponseContains(
            "HELLO",
            case_sensitive=True,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_case_sensitive_match(self) -> None:
        result = await ResponseContains(
            "hello",
            case_sensitive=True,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_not_detected(self) -> None:
        result = await ResponseContains("evil").evaluate_async(context=_ctx("all good"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsRegex:
    @pytest.mark.asyncio
    async def test_regex_match(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(pattern).evaluate_async(
            context=_ctx("sent to evil@evil.com"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_regex_no_match(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(pattern).evaluate_async(
            context=_ctx("all good"),
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsCallable:
    @pytest.mark.asyncio
    async def test_callable_match(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
        ).evaluate_async(context=_ctx("the secret is here"))
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_callable_no_match(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
        ).evaluate_async(context=_ctx("nothing to see"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsComposition:
    @pytest.mark.asyncio
    async def test_composable_with_not(self) -> None:
        composed = ~ResponseContains("I cannot help")
        result = await composed.evaluate_async(context=_ctx("Sure, here you go"))
        assert result.outcome is EvalOutcome.DETECTED
