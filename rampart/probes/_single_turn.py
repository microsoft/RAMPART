# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""SingleTurnExecution — probe execution strategy.

Sends prompts via a PromptDriver, evaluates responses, and resolves
using probe semantics (DETECTED → SAFE, NOT_DETECTED → UNSAFE).
No injection phase — just session creation, prompt driving, evaluation,
and cleanup. Inherits BaseExecution lifecycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rampart.core.execution import (
    BaseExecution,
    ExecutionEventHandler,
    evaluate_turn_async,
)
from rampart.core.result import Result, SafetyStatus, resolve_as_probe

if TYPE_CHECKING:
    from rampart.core.adapter import AgentAdapter
    from rampart.core.evaluator import Evaluator
    from rampart.core.prompt_driver import PromptDriver
    from rampart.core.types import EvalResult, Turn

logger = logging.getLogger(__name__)


class SingleTurnExecution(BaseExecution):
    """Executes a probe: send prompts, evaluate, resolve as probe.

    Inherits BaseExecution. No injection phase — just session
    creation, prompt driving, evaluation, and cleanup. The lifecycle
    skeleton (including InfrastructureError handling) is owned by
    BaseExecution.

    Args:
        driver (PromptDriver): How to drive the conversation.
        evaluator (Evaluator): What behavior to check for.
        max_turns (int): Maximum prompt-response exchanges before
            returning ERROR. Defaults to 25.
        event_handlers (list[ExecutionEventHandler] | None): Additional
            handlers beyond the framework defaults.
    """

    def __init__(
        self,
        *,
        driver: PromptDriver,
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> None:
        super().__init__(event_handlers=event_handlers)
        self._driver = driver
        self._evaluator = evaluator
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
        turns: list[Turn] = []

        async with await adapter.create_session_async() as session:
            for turn_index in range(self._max_turns):
                decision = await self._driver.next_prompt_async(history=turns)
                if decision is None:
                    break

                response = await session.send_async(decision.request)
                turn = await evaluate_turn_async(
                    evaluator=self._evaluator,
                    history=turns,
                    request=decision.request,
                    response=response,
                    turn_number=turn_index,
                    driver_reasoning=decision.reasoning,
                    manifest=adapter.manifest,
                )
                turns.append(turn)

                if turn.eval_result and turn.eval_result.detected:
                    break

        eval_results = [t.eval_result for t in turns if t.eval_result is not None]
        safe, status = resolve_as_probe(eval_results=eval_results)

        return Result(
            safe=safe,
            status=status,
            summary=_build_summary(status=status, eval_results=eval_results),
            turns=turns,
            strategy="probe",
            observability_level=adapter.observability_profile,
        )


def _build_summary(
    *,
    status: SafetyStatus,
    eval_results: list[EvalResult],
) -> str:
    """Build a human-readable one-line summary.

    Args:
        status (SafetyStatus): The resolved safety status.
        eval_results (list[EvalResult]): The evaluator outputs.

    Returns:
        str: A summary string for the Result.
    """
    if status == SafetyStatus.SAFE:
        return "Expected behavior detected"
    if status == SafetyStatus.UNSAFE:
        rationales = [er.rationale for er in eval_results if er.rationale]
        detail = rationales[-1] if rationales else "Expected behavior not detected"
        return f"UNSAFE: {detail}"
    if status == SafetyStatus.UNDETERMINED:
        return "UNDETERMINED: Could not determine if expected behavior occurred"
    return (
        f"ERROR: {eval_results[-1].rationale if eval_results else 'No evaluation data'}"
    )
