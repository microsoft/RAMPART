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

    Side effects are only visible when the adapter reports them. If the
    adapter cannot, this evaluator returns UNDETERMINED instead of
    NOT_DETECTED, because "the side effect did not happen" and "we could
    not see the side effects" are different answers and only the first
    one says anything about the agent.

    Args:
        kind (str): The side effect kind to look for (positional-only).
        **detail_predicates (dict[str, Any | Callable[[Any], bool]]):
            Detail field -> expected value or callable predicate.
    """

    _detected_absorbing = True

    def __init__(
        self,
        kind: str,
        /,
        **detail_predicates: Any | Callable[[Any], bool],  # ruff: ignore[any-type]
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
                UNDETERMINED if no match was found and the adapter does
                not report side effects; NOT_DETECTED otherwise.
        """
        for se in context.all_side_effects:
            if se.kind == self._kind and self._matches(se):
                return EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    evidence=[f"Side effect '{se.kind}': {se.details}"],
                    rationale=f"Side effect '{se.kind}' detected",
                )

        # Checked after the scan, so a side effect the adapter did report still
        # counts, even at a level that says it cannot report them.
        if not context.observability_level.observes_side_effects:
            return EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale=(
                    "Adapter observability is "
                    f"'{context.observability_level.value}', which does not "
                    f"report side effects, so whether '{self._kind}' occurred "
                    f"cannot be determined"
                ),
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
