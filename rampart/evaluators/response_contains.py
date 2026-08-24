# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""ResponseContains evaluator — detects patterns in response text."""

from __future__ import annotations

import re
import warnings
from enum import Enum
from typing import TYPE_CHECKING

from rampart.core.evaluator import BaseEvaluator
from rampart.core.types import EvalContext, EvalOutcome, EvalResult

if TYPE_CHECKING:
    from collections.abc import Callable


class ResponseScope(Enum):
    """Which responses in the transcript the evaluator inspects.

    Scope applies only to turns already present in ``EvalContext``. It does
    not control how many turns an execution produces or whether execution
    stops early.

    Attributes:
        ANY_TURN: Detect when at least one response matches.
        ALL_TURNS: Detect only when every response matches.
        CURRENT_TURN: Inspect only the most recent response.
    """

    ANY_TURN = "any_turn"
    ALL_TURNS = "all_turns"
    CURRENT_TURN = "current_turn"


_UNSPECIFIED_SCOPE_WARNING = (
    "ResponseContains evaluated a multi-turn transcript without an explicit "
    "ResponseScope and inspected only the current response. Choose ANY_TURN, "
    "ALL_TURNS, or CURRENT_TURN to make the intended quantifier explicit."
)


class ResponseContains(BaseEvaluator):
    """Detects whether response text contains a target pattern.

    Accepts a plain string (substring match), compiled regex, or
    callable predicate.

    Args:
        target (str | re.Pattern | Callable[[str], bool]):
            Pattern to find (positional-only).
        case_sensitive (bool): Whether substring match is case-sensitive.
        scope (ResponseScope | None): Which responses to inspect. None preserves
            current-turn behavior and warns for multi-turn contexts.
    """

    def __init__(
        self,
        target: str | re.Pattern[str] | Callable[[str], bool],
        /,
        *,
        case_sensitive: bool = False,
        scope: ResponseScope | None = None,
    ) -> None:
        """Initialize with target pattern, case sensitivity, and scope."""
        self._target = target
        self._case_sensitive = case_sensitive
        self._scope = scope

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Check response text for the target pattern within the scope.

        Returns:
            EvalResult: DETECTED when the configured scope is satisfied;
                NOT_DETECTED otherwise.

        Raises:
            ValueError: If the evaluation context has no turns.
        """
        if not context.turns:
            msg = "No turns in context."
            raise ValueError(msg)

        scope = self._resolve_scope(context=context)
        if scope is ResponseScope.CURRENT_TURN:
            return self._evaluate_current_turn(context=context)
        return self._evaluate_quantified(context=context, scope=scope)

    def _evaluate_quantified(
        self,
        *,
        context: EvalContext,
        scope: ResponseScope,
    ) -> EvalResult:
        """Apply an ANY_TURN or ALL_TURNS quantifier to response matches.

        Returns:
            EvalResult: The quantified detection result.
        """
        matches = [self._matches(turn.response.text) for turn in context.turns]
        if scope is ResponseScope.ANY_TURN:
            return self._evaluate_any_turn(context=context, matches=matches)
        return self._evaluate_all_turns(context=context, matches=matches)

    @staticmethod
    def _evaluate_any_turn(
        *,
        context: EvalContext,
        matches: list[bool],
    ) -> EvalResult:
        """Resolve existential matching across response turns.

        Returns:
            EvalResult: DETECTED when any response matches.
        """
        if any(matches):
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=[
                    ResponseContains._turns_label(
                        context=context,
                        matches=matches,
                        wanted=True,
                        prefix="Pattern found on turn(s)",
                    ),
                ],
                rationale="At least one response contains the target pattern",
            )
        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="No response contains the target pattern",
        )

    @staticmethod
    def _evaluate_all_turns(
        *,
        context: EvalContext,
        matches: list[bool],
    ) -> EvalResult:
        """Resolve universal matching across response turns.

        Returns:
            EvalResult: DETECTED when every response matches.
        """
        if all(matches):
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=[
                    ResponseContains._turns_label(
                        context=context,
                        matches=matches,
                        wanted=True,
                        prefix="Pattern found on turn(s)",
                    ),
                ],
                rationale="Every response contains the target pattern",
            )
        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            evidence=[
                ResponseContains._turns_label(
                    context=context,
                    matches=matches,
                    wanted=False,
                    prefix="Pattern missing on turn(s)",
                ),
            ],
            rationale="Not every response contains the target pattern",
        )

    @staticmethod
    def _turns_label(
        *,
        context: EvalContext,
        matches: list[bool],
        wanted: bool,
        prefix: str,
    ) -> str:
        """Format matching or missing turn numbers for evidence.

        Returns:
            str: Evidence label containing the selected turn numbers.
        """
        turn_numbers = [
            str(turn.turn_number)
            for turn, matched in zip(context.turns, matches, strict=True)
            if matched is wanted
        ]
        return f"{prefix}: {', '.join(turn_numbers)}"

    def _resolve_scope(self, *, context: EvalContext) -> ResponseScope:
        """Resolve the scope and warn about ambiguous multi-turn evaluation.

        Returns:
            ResponseScope: The configured scope, or CURRENT_TURN when omitted.
        """
        if self._scope is not None:
            return self._scope
        if len(context.turns) > 1:
            warnings.warn(_UNSPECIFIED_SCOPE_WARNING, FutureWarning, stacklevel=3)
        return ResponseScope.CURRENT_TURN

    def _evaluate_current_turn(self, *, context: EvalContext) -> EvalResult:
        """Evaluate only the most recent response.

        Returns:
            EvalResult: The current-turn detection result.
        """
        if self._matches(context.text):
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=["Pattern found in response text"],
                rationale="Response contains target pattern",
            )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="Target pattern not found in response text",
        )

    def _matches(self, text: str) -> bool:
        """Return whether one response matches the configured target."""
        if isinstance(self._target, re.Pattern):
            return bool(self._target.search(text))
        if isinstance(self._target, str):
            check_text = text if self._case_sensitive else text.lower()
            check_target = (
                self._target if self._case_sensitive else self._target.lower()
            )
            return check_target in check_text
        return self._target(text)
