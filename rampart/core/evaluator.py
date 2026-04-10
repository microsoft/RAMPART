# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Evaluator protocol, BaseEvaluator ABC, and composition operators.

The evaluator system is the framework's primary analytical capability.
Evaluators detect conditions in an EvalContext. They are polarity-free —
they answer "did X happen?", not "is X good or bad?"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from rampart.core.types import EvalContext, EvalOutcome, EvalResult


@runtime_checkable
class Evaluator(Protocol):
    """Detects a condition in an EvalContext.

    Evaluators are polarity-free. They answer "did X happen?" — not
    "is X good or bad?" The Attacks/Probes factories handle the
    good/bad judgment.

    All evaluators are async. Even evaluators with synchronous logic
    must be async to compose correctly with LLM-based evaluators via
    & and | operators. A sync evaluator composed with an async
    LLM judge via | would silently return a coroutine object instead
    of an EvalResult — this design prevents that structurally.
    """

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate the context and return a detection signal.

        Args:
            context (EvalContext): The interaction data to evaluate.

        Returns:
            EvalResult: What the evaluator detected.
        """
        ...


class BaseEvaluator(ABC):
    """Base class for evaluator implementations.

    Provides composition operators (|, &, ~) and common behavior.
    Subclass this for concrete evaluators. Implement evaluate_async.
    """

    @abstractmethod
    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate the context. Subclasses implement this."""
        ...

    def __or__(self, other: Evaluator) -> _AnyEvaluator:
        """Compose: self | other — DETECTED if either detects."""
        return _AnyEvaluator(left=self, right=other)

    def __and__(self, other: Evaluator) -> _AllEvaluator:
        """Compose: self & other — DETECTED only if both detect."""
        return _AllEvaluator(left=self, right=other)

    def __invert__(self) -> _NotEvaluator:
        """Invert: ~self — flips DETECTED <-> NOT_DETECTED."""
        return _NotEvaluator(inner=self)


class _AnyEvaluator(BaseEvaluator):
    """DETECTED if either operand detects. Short-circuits on left DETECTED."""

    def __init__(self, *, left: Evaluator, right: Evaluator) -> None:
        self._left = left
        self._right = right

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate left first. If DETECTED, skip right entirely.

        Short-circuiting avoids unnecessary work when the left operand
        is a cheap deterministic evaluator and the right is an expensive
        LLM judge. Place the cheaper evaluator on the left side of |.
        """
        left_result = await self._left.evaluate_async(context=context)

        if left_result.detected:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=left_result.evidence,
                rationale=left_result.rationale,
            )

        right_result = await self._right.evaluate_async(context=context)

        if right_result.detected:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=right_result.evidence,
                rationale=right_result.rationale,
            )

        if EvalOutcome.UNDETERMINED in (left_result.outcome, right_result.outcome):
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale="One or both operands undetermined",
            )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="Neither condition detected",
        )


class _AllEvaluator(BaseEvaluator):
    """DETECTED only if both operands detect. Short-circuits on left non-DETECTED."""

    def __init__(self, *, left: Evaluator, right: Evaluator) -> None:
        self._left = left
        self._right = right

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate left first. If NOT_DETECTED or UNDETERMINED, skip right.

        Short-circuiting avoids unnecessary work when the left operand
        can rule out the conjunction cheaply. Place the cheaper or more
        likely-to-fail evaluator on the left side of &.
        """
        left_result = await self._left.evaluate_async(context=context)

        if left_result.outcome == EvalOutcome.NOT_DETECTED:
            return EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                rationale=f"Left operand not detected: {left_result.rationale}",
            )

        if left_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale=f"Left operand undetermined: {left_result.rationale}",
            )

        right_result = await self._right.evaluate_async(context=context)

        if right_result.detected:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=left_result.evidence + right_result.evidence,
                rationale=f"({left_result.rationale}) AND ({right_result.rationale})",
            )

        if right_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale=f"Right operand undetermined: {right_result.rationale}",
            )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="Not both conditions detected",
        )


class _NotEvaluator(BaseEvaluator):
    """Flips DETECTED <-> NOT_DETECTED. UNDETERMINED passes through."""

    def __init__(self, *, inner: Evaluator) -> None:
        self._inner = inner

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Invert the inner evaluator's outcome."""
        result = await self._inner.evaluate_async(context=context)

        if result.outcome == EvalOutcome.UNDETERMINED:
            return result

        flipped = EvalOutcome.NOT_DETECTED if result.detected else EvalOutcome.DETECTED
        return EvalResult(
            outcome=flipped,
            confidence=result.confidence,
            evidence=result.evidence,
            rationale=f"NOT ({result.rationale})",
        )
