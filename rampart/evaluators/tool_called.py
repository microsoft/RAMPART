# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""ToolCalled evaluator — detects whether a specific tool was invoked."""

from __future__ import annotations

from typing import Any

from rampart.core.evaluator import BaseEvaluator
from rampart.core.types import EvalContext, EvalOutcome, EvalResult, ToolCall


class ToolCalled(BaseEvaluator):
    """Detects whether a tool was called, optionally matching parameters.

    Parameter predicates can be exact values or callables. Callables
    receive the parameter value and return True/False.

    This evaluator only detects conditions. It does not reason about
    observability gaps. That adjustment is owned by the execution
    strategy.

    Args:
        tool_name (str): The tool to look for (positional-only).
        **param_predicates (dict[str, Any]):
             Parameter name -> expected value or predicate.
    """

    def __init__(self, tool_name: str, /, **param_predicates: dict[str, Any]) -> None:
        """Initialize with tool name and optional parameter predicates."""
        self._tool_name = tool_name
        self._predicates = param_predicates

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Check all turns for a matching tool call."""
        for tc in context.all_tool_calls:
            if tc.name == self._tool_name and self._matches(tc):
                return EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    evidence=[f"{tc.name}({tc.arguments})"],
                    rationale=f"Tool '{tc.name}' called with matching parameters",
                )

        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale=f"Tool '{self._tool_name}' not called with matching parameters",
        )

    def _matches(self, tool_call: ToolCall) -> bool:
        """Check if a tool call matches all parameter predicates."""
        for param_name, predicate in self._predicates.items():
            value = tool_call.arguments.get(param_name)
            if callable(predicate):
                if not predicate(value):
                    return False
            elif value != predicate:
                return False
        return True
