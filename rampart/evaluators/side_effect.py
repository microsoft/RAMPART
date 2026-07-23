# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""SideEffectOccurred evaluator — detects observed side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rampart.core.evaluator import BaseEvaluator
from rampart.core.types import EvalContext, EvalOutcome, EvalResult, SideEffect

if TYPE_CHECKING:
    from collections.abc import Callable


class SideEffectOccurred(BaseEvaluator):
    """Detects whether a side effect of a given kind occurred.

    Args:
        kind (str): The side effect kind to look for (positional-only).
        **detail_predicates (dict[str, Any | Callable[[Any], bool]]):
            Detail field -> expected value or callable predicate.
    """

    def __init__(
        self,
        kind: str,
        /,
        **detail_predicates: Any | Callable[[Any], bool],  # noqa: ANN401
    ) -> None:
        """Initialize with side effect kind and optional predicates."""
        self._kind = kind
        self._predicates = detail_predicates

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Check all turns for a matching side effect.

        Returns:
            EvalResult: DETECTED (with the matching side-effect as
                evidence) if a side effect of the configured ``kind``
                satisfying all detail predicates is found in any turn;
                NOT_DETECTED otherwise.
        """
        for se in context.all_side_effects:
            if se.kind == self._kind and self._matches(se):
                return EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    evidence=[f"Side effect '{se.kind}': {se.details}"],
                    rationale=f"Side effect '{se.kind}' detected",
                )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale=f"Side effect '{self._kind}' not detected",
        )

    def _matches(self, side_effect: SideEffect) -> bool:
        """Check if a side effect matches all detail predicates.

        Returns:
            bool: True iff every detail predicate is satisfied (callable
                predicates must return True; value predicates must match
                by equality).
        """
        for key, predicate in self._predicates.items():
            value = side_effect.details.get(key)
            if callable(predicate):
                if not predicate(value):
                    return False
            elif value != predicate:
                return False
        return True
