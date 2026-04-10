# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""ResponseContains evaluator — detects patterns in response text."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rampart.core.evaluator import BaseEvaluator
from rampart.core.types import EvalContext, EvalOutcome, EvalResult

if TYPE_CHECKING:
    from collections.abc import Callable


class ResponseContains(BaseEvaluator):
    """Detects whether response text contains a target pattern.

    Accepts a plain string (substring match), compiled regex, or
    callable predicate.

    Args:
        target (str | re.Pattern | Callable[[str], bool]):
            Pattern to find (positional-only).
        case_sensitive (bool): Whether substring match is case-sensitive.
    """

    def __init__(
        self,
        target: str | re.Pattern | Callable[[str], bool],
        /,
        *,
        case_sensitive: bool = False,
    ) -> None:
        """Initialize with target pattern and case sensitivity."""
        self._target = target
        self._case_sensitive = case_sensitive

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Check response text for the target pattern."""
        text = context.text

        if callable(self._target) and not isinstance(self._target, re.Pattern):
            found = self._target(text)
        elif isinstance(self._target, re.Pattern):
            found = bool(self._target.search(text))
        else:
            check_text = text if self._case_sensitive else text.lower()
            check_target = (
                self._target if self._case_sensitive else self._target.lower()
            )
            found = check_target in check_text

        if found:
            return EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=["Pattern found in response text"],
                rationale="Response contains target pattern",
            )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="Target pattern not found in response text",
        )
