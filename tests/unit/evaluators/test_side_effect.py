# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.side_effect — SideEffectOccurred evaluator."""

import pytest

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    Request,
    Response,
    SideEffect,
    Turn,
)
from rampart.evaluators import SideEffectOccurred


def _ctx_with_side_effects(*effects: SideEffect) -> EvalContext:
    """Build a single-turn EvalContext with the given side effects."""
    return EvalContext(
        turns=[
            Turn(
                request=Request(prompt="test"),
                response=Response(text="ok", side_effects=list(effects)),
            ),
        ],
    )


class TestSideEffectOccurredDetection:
    @pytest.mark.asyncio
    async def test_detects_by_kind(self) -> None:
        ctx = _ctx_with_side_effects(SideEffect(kind="http_request"))
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_not_detected_wrong_kind(self) -> None:
        ctx = _ctx_with_side_effects(SideEffect(kind="file_write"))
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_not_detected_no_effects(self) -> None:
        ctx = _ctx_with_side_effects()
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestSideEffectOccurredDetailPredicates:
    @pytest.mark.asyncio
    async def test_exact_detail_match(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://evil.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url="https://evil.com",
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_exact_detail_mismatch(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://safe.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url="https://evil.com",
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_predicate_detail_match(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://evil.com/data"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url=lambda u: "evil.com" in str(u),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_predicate_detail_mismatch(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://safe.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url=lambda u: "evil.com" in str(u),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED
