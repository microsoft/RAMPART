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

# An evaluator may return UNDETERMINED without saying why. Recording a fixed
# phrase keeps the gap visible instead of storing an empty string, which reads
# as "nothing was undetermined" everywhere downstream.
_NO_REASON_GIVEN = "an operand gave no reason"


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
        """Compose: self | other — DETECTED if either detects.

        Returns:
            _AnyEvaluator: A composite evaluator with short-circuit OR
                semantics over ``self`` and ``other``.
        """
        return _AnyEvaluator(left=self, right=other)

    def __and__(self, other: Evaluator) -> _AllEvaluator:
        """Compose: self & other — DETECTED only if both detect.

        Returns:
            _AllEvaluator: A composite evaluator with short-circuit AND
                semantics over ``self`` and ``other``.
        """
        return _AllEvaluator(left=self, right=other)

    def __invert__(self) -> _NotEvaluator:
        """Invert: ~self — flips DETECTED <-> NOT_DETECTED.

        Returns:
            _NotEvaluator: A wrapper that inverts the inner evaluator's
                outcome (UNDETERMINED is preserved).
        """
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

        Returns:
            EvalResult: DETECTED if either operand is DETECTED; otherwise
                UNDETERMINED if either operand is UNDETERMINED; otherwise
                NOT_DETECTED. An UNDETERMINED outcome carries both operands'
                evidence. Every operand that ran contributes the reasons it
                carries to ``undetermined_operands``; one that came back
                UNDETERMINED with none of its own contributes its rationale
                instead. Each reason is kept once, and a short-circuited
                operand never runs, so it is never recorded.
        """
        left_result = await self._left.evaluate_async(context=context)

        if left_result.detected:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=left_result.evidence,
                rationale=left_result.rationale,
                undetermined_operands=_merge_undetermined(left=left_result),
            )

        right_result = await self._right.evaluate_async(context=context)
        undetermined = _merge_undetermined(left=left_result, right=right_result)

        if right_result.detected:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=right_result.evidence,
                rationale=right_result.rationale,
                undetermined_operands=undetermined,
            )

        # Both operands ran and neither detected, so name the one that could not
        # be determined and carry the evidence they produced. A bare "undetermined"
        # here would hide the adapter setting that caused it.
        if left_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                evidence=left_result.evidence + right_result.evidence,
                rationale=f"Left operand undetermined: {left_result.rationale}",
                undetermined_operands=undetermined,
            )

        if right_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                evidence=left_result.evidence + right_result.evidence,
                rationale=f"Right operand undetermined: {right_result.rationale}",
                undetermined_operands=undetermined,
            )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="Neither condition detected",
            undetermined_operands=undetermined,
        )


class _AllEvaluator(BaseEvaluator):
    """DETECTED only if both operands detect. Short-circuits on left NOT_DETECTED."""

    def __init__(self, *, left: Evaluator, right: Evaluator) -> None:
        self._left = left
        self._right = right

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate left first. If NOT_DETECTED, skip right.

        Only a NOT_DETECTED operand settles the conjunction on its own, so
        that is the one case the left operand can short-circuit. An
        UNDETERMINED left operand does not, because the right operand may
        still be NOT_DETECTED and settle it. Returning early there would
        make the outcome depend on the order the operands were written in.

        Place the cheaper or more likely-to-fail evaluator on the left side
        of & so the short-circuit saves the most work. An evaluator that
        depends on adapter observability belongs there too, since the
        short-circuit skips the right operand and nothing it would have
        reported can be recorded.

        Returns:
            EvalResult: NOT_DETECTED if either operand is NOT_DETECTED;
                otherwise UNDETERMINED if either operand is UNDETERMINED;
                otherwise DETECTED. Only the DETECTED and UNDETERMINED
                outcomes carry both operands' evidence. Every operand that
                ran contributes the reasons it carries to
                ``undetermined_operands``; one that came back UNDETERMINED
                with none of its own contributes its rationale instead. Each
                reason is kept once, and a short-circuited operand never runs,
                so it is never recorded.
        """
        left_result = await self._left.evaluate_async(context=context)

        if left_result.outcome == EvalOutcome.NOT_DETECTED:
            return EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                rationale=f"Left operand not detected: {left_result.rationale}",
                undetermined_operands=_merge_undetermined(left=left_result),
            )

        right_result = await self._right.evaluate_async(context=context)
        undetermined = _merge_undetermined(left=left_result, right=right_result)

        if right_result.outcome == EvalOutcome.NOT_DETECTED:
            return EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                rationale=f"Right operand not detected: {right_result.rationale}",
                undetermined_operands=undetermined,
            )

        # Both operands ran, so carry the evidence they produced even though the
        # conjunction cannot be settled. Dropping it would discard, for example,
        # a judge detection that is real but unconfirmable on its own.
        if left_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                evidence=left_result.evidence + right_result.evidence,
                rationale=f"Left operand undetermined: {left_result.rationale}",
                undetermined_operands=undetermined,
            )

        if right_result.outcome == EvalOutcome.UNDETERMINED:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                evidence=left_result.evidence + right_result.evidence,
                rationale=f"Right operand undetermined: {right_result.rationale}",
                undetermined_operands=undetermined,
            )

        return EvalResult(
            outcome=EvalOutcome.DETECTED,
            evidence=left_result.evidence + right_result.evidence,
            rationale=f"({left_result.rationale}) AND ({right_result.rationale})",
            undetermined_operands=undetermined,
        )


class _NotEvaluator(BaseEvaluator):
    """Flips DETECTED <-> NOT_DETECTED. UNDETERMINED passes through."""

    def __init__(self, *, inner: Evaluator) -> None:
        self._inner = inner

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Invert the inner evaluator's outcome.

        Returns:
            EvalResult: The inner result with DETECTED <-> NOT_DETECTED
                flipped (UNDETERMINED preserved); confidence, evidence and
                ``undetermined_operands`` are carried through and the
                rationale is prefixed with ``NOT (...)``.
        """
        result = await self._inner.evaluate_async(context=context)

        if result.outcome == EvalOutcome.UNDETERMINED:
            return result

        flipped = EvalOutcome.NOT_DETECTED if result.detected else EvalOutcome.DETECTED
        return EvalResult(
            outcome=flipped,
            confidence=result.confidence,
            evidence=result.evidence,
            rationale=f"NOT ({result.rationale})",
            undetermined_operands=_merge_undetermined(left=result),
        )


def _merge_undetermined(
    *,
    left: EvalResult,
    right: EvalResult | None = None,
) -> list[str]:
    """Collect why any part of this composition stayed undetermined.

    An operand that already carries reasons contributes those, because they
    name the evaluators that could not answer. An operand that came back
    UNDETERMINED carrying none has only its rationale to offer, so that
    stands in for it, or a fixed phrase when it gave none. Taking the
    carried reasons in preference is what keeps a nested composite from
    collapsing several gaps into one restatement of the first.

    Repeats are collapsed, since a tree can reach the same unobservable
    evaluator by more than one path and a repeat says nothing the first
    entry did not.

    Args:
        left (EvalResult): The left operand's result.
        right (EvalResult | None): The right operand's result, or None when
            the left operand short-circuited before the right one ran.

    Returns:
        list[str]: A fresh list of the distinct reasons, left operand first.
    """
    reasons: list[str] = []
    for operand in (left, right):
        if operand is None:
            continue
        if operand.undetermined_operands:
            reasons.extend(operand.undetermined_operands)
        elif operand.outcome == EvalOutcome.UNDETERMINED:
            # str() because a third-party evaluator that puts a non-string in
            # rationale should cost its own reason, not the whole verdict.
            reasons.append(str(operand.rationale).strip() or _NO_REASON_GIVEN)
    return list(dict.fromkeys(reasons))
