# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""SingleTurnExecution — behavioral probe execution strategy.

Sends prompts via a PromptDriver, evaluates the completed trace once, and
resolves using probe semantics (DETECTED → SAFE, NOT_DETECTED → UNSAFE).
No injection phase — just session creation, prompt driving, optional online
stopping, terminal evaluation, and cleanup. Inherits BaseExecution lifecycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rampart.common.text import safe_str, safe_str_list
from rampart.core.execution import (
    BaseExecution,
    ExecutionEventHandler,
)
from rampart.core.result import (
    Result,
    SafetyStatus,
    _explain_undetermined,
    _summarize_undetermined_operands,
    resolve_probe_verdict,
)
from rampart.core.trace import evaluate_terminal_async, run_trace_async
from rampart.core.types import TerminationReason

if TYPE_CHECKING:
    from rampart.core.adapter import AgentAdapter
    from rampart.core.evaluator import Evaluator
    from rampart.core.prompt_driver import PromptDriver
    from rampart.core.types import EvalResult

logger = logging.getLogger(__name__)


class SingleTurnExecution(BaseExecution):
    """Execute a behavioral probe over a completed trace.

    Inherits BaseExecution. No injection phase — just session
    creation, prompt driving, evaluation, and cleanup. The lifecycle
    skeleton (including InfrastructureError handling) is owned by
    BaseExecution.

    Args:
        driver (PromptDriver): How to drive the conversation.
        evaluator (Evaluator): What behavior to check for.
        stop_when (Evaluator | None): Optional online condition that stops the
            trace when detected. Defaults to None.
        max_turns (int): Maximum prompt-response exchanges. Reaching the
            limit resolves the trace normally. Defaults to 25.
        event_handlers (list[ExecutionEventHandler] | None): Additional
            handlers beyond the framework defaults.
    """

    def __init__(
        self,
        *,
        driver: PromptDriver,
        evaluator: Evaluator,
        stop_when: Evaluator | None = None,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> None:
        super().__init__(event_handlers=event_handlers)
        self._driver = driver
        self._evaluator = evaluator
        self._stop_when = stop_when
        self._max_turns = max_turns

    @property
    def strategy_name(self) -> str:
        """Identifies this as a probe execution in results and reports."""
        return "probe"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Send prompts, evaluate responses, return Result with probe semantics.

        Args:
            adapter (AgentAdapter): The agent adapter.

        Returns:
            Result: Safety verdict with full conversation evidence.
        """
        async with await adapter.create_session_async() as session:
            run = await run_trace_async(
                session=session,
                driver=self._driver,
                max_turns=self._max_turns,
                observability_level=adapter.observability_profile,
                stop_when=self._stop_when,
                manifest=adapter.manifest,
            )
            evaluation = await evaluate_terminal_async(
                evaluator=self._evaluator,
                run=run,
            )

        status = resolve_probe_verdict(evaluation=evaluation)

        return Result(
            status=status,
            summary=_build_summary(
                status=status,
                evaluation=evaluation,
                termination_reason=run.termination_reason,
            ),
            evaluation=evaluation,
            turns=run.turns,
            termination_reason=run.termination_reason,
            strategy=self.strategy_name,
            observability_level=adapter.observability_profile,
        )


def _build_summary(
    *,
    status: SafetyStatus,
    evaluation: EvalResult | None,
    termination_reason: TerminationReason,
) -> str:
    """Build a human-readable one-line summary.

    Args:
        status (SafetyStatus): The resolved safety status.
        evaluation (EvalResult | None): The terminal evaluator output.
        termination_reason (TerminationReason): Why the trace ended.

    Returns:
        str: A summary string for the Result.
    """
    eval_results = [evaluation] if evaluation is not None else []
    budget_suffix = (
        " (turn budget exhausted)"
        if termination_reason is TerminationReason.MAX_TURNS
        else ""
    )
    if status is SafetyStatus.SAFE:
        evidence = (
            safe_str_list(value=evaluation.evidence) if evaluation is not None else []
        )
        detail = "; ".join(evidence[:3])
        if not detail and evaluation is not None:
            detail = safe_str(value=evaluation.rationale).strip()
        suffix = f": {detail}" if detail else ""
        gap_suffix = _summarize_undetermined_operands(
            eval_results=eval_results,
        )
        return f"Expected behavior detected{suffix}{gap_suffix}{budget_suffix}"
    if status is SafetyStatus.UNSAFE:
        detail = safe_str(value=evaluation.rationale).strip() if evaluation else ""
        return f"UNSAFE: {detail or 'Expected behavior not detected'}{budget_suffix}"
    if status is SafetyStatus.UNDETERMINED:
        detail = _explain_undetermined(
            eval_results=eval_results,
            fallback="Could not determine if expected behavior occurred",
        )
        return f"UNDETERMINED: {detail}{budget_suffix}"

    detail = safe_str(value=evaluation.rationale).strip() if evaluation else ""
    if detail:
        error_detail = f"{detail}{budget_suffix}"
    elif termination_reason is TerminationReason.DRIVER_EXHAUSTED:
        error_detail = "Driver produced no turns"
    elif termination_reason is TerminationReason.MAX_TURNS:
        error_detail = "Turn budget exhausted before the agent was exercised"
    else:
        error_detail = "Probe produced no evaluable trace"
    return f"ERROR: {error_detail}"
