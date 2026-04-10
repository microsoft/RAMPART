# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.evaluator — Evaluator protocol, BaseEvaluator, composition."""

import pytest

from rampart.core.evaluator import BaseEvaluator, Evaluator
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    Request,
    Response,
    Turn,
)


class _StubEvaluator(BaseEvaluator):
    """Test helper that returns a fixed outcome."""

    def __init__(self, *, outcome: EvalOutcome, rationale: str = "stub") -> None:
        self._outcome = outcome
        self._rationale = rationale
        self.call_count = 0

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a fixed result and track call count."""
        self.call_count += 1
        return EvalResult(
            outcome=self._outcome,
            evidence=[f"stub:{self._outcome.value}"],
            rationale=self._rationale,
        )


def _ctx() -> EvalContext:
    """Build a minimal EvalContext for testing."""
    return EvalContext(
        turns=[Turn(request=Request(prompt="p"), response=Response(text="r"))],
    )


class TestEvaluatorProtocol:
    def test_is_runtime_checkable(self) -> None:
        class MyEvaluator:
            async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
                return EvalResult(outcome=EvalOutcome.DETECTED)

        assert isinstance(MyEvaluator(), Evaluator)

    def test_base_evaluator_satisfies_protocol(self) -> None:
        stub = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        assert isinstance(stub, Evaluator)


class TestOrComposition:
    @pytest.mark.asyncio
    async def test_left_detected_short_circuits(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert left.call_count == 1
        assert right.call_count == 0

    @pytest.mark.asyncio
    async def test_right_detected(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert left.call_count == 1
        assert right.call_count == 1

    @pytest.mark.asyncio
    async def test_neither_detected(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_undetermined_propagates(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED


class TestAndComposition:
    @pytest.mark.asyncio
    async def test_left_not_detected_short_circuits(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert left.call_count == 1
        assert right.call_count == 0

    @pytest.mark.asyncio
    async def test_left_undetermined_short_circuits(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert right.call_count == 0

    @pytest.mark.asyncio
    async def test_both_detected(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED, rationale="L")
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED, rationale="R")
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert len(result.evidence) == 2

    @pytest.mark.asyncio
    async def test_right_not_detected(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_right_undetermined(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED


class TestNotComposition:
    @pytest.mark.asyncio
    async def test_flips_detected_to_not_detected(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_flips_not_detected_to_detected(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.asyncio
    async def test_preserves_undetermined(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED

    @pytest.mark.asyncio
    async def test_preserves_confidence_and_evidence(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.evidence == ["stub:detected"]
        assert "NOT" in result.rationale


class TestCompositionChaining:
    @pytest.mark.asyncio
    async def test_or_and_not_chain(self) -> None:
        a = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        b = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        c = _StubEvaluator(outcome=EvalOutcome.DETECTED)

        composed = (a | b) & ~c

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    @pytest.mark.asyncio
    async def test_composed_evaluators_are_composable(self) -> None:
        a = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        b = _StubEvaluator(outcome=EvalOutcome.DETECTED)

        first = a | b
        second = ~first

        assert isinstance(first, BaseEvaluator)
        assert isinstance(second, BaseEvaluator)

        result = await second.evaluate_async(context=_ctx())
        assert result.outcome is EvalOutcome.NOT_DETECTED
