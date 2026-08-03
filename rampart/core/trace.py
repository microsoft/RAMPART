# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared linear trace execution and terminal evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from rampart.core.types import (
    EvalContext,
    EvalResult,
    EvaluationRole,
    ObservabilityLevel,
    TerminationReason,
    Turn,
)

if TYPE_CHECKING:
    from rampart.core.adapter import Session
    from rampart.core.evaluator import Evaluator
    from rampart.core.manifest import AppManifest
    from rampart.core.prompt_driver import PromptDriver


@dataclass(frozen=True, kw_only=True, eq=False)
class EvaluationRecord:
    """One online evaluation and the exact context it judged.

    Args:
        evaluator: Evaluator object that produced the result. Identity is the
            reuse boundary.
        context: Exact raw-trace context passed to the evaluator.
        result: Evaluation returned for that context.
    """

    evaluator: Evaluator
    context: EvalContext
    result: EvalResult


@dataclass(kw_only=True)
class TraceRun:
    """A completed linear trace and its latest online evaluation.

    ``turns`` is the driver/report view and may carry online evidence.
    ``raw_turns`` is the evaluator view and never carries framework-produced
    evaluation annotations.

    Args:
        termination_reason: Why the trace stopped producing turns.
        observability_level: What the adapter can observe.
        manifest: Agent capabilities used to create evaluator contexts.
        turns: Annotated history passed to prompt drivers and results.
        raw_turns: Annotation-free history passed to evaluators.
        latest_online_evaluation: Most recent stop-condition evaluation.
    """

    termination_reason: TerminationReason
    observability_level: ObservabilityLevel
    manifest: AppManifest | None = None
    turns: list[Turn] = field(default_factory=list[Turn])
    raw_turns: list[Turn] = field(default_factory=list[Turn])
    latest_online_evaluation: EvaluationRecord | None = None


def _evaluation_context(
    *,
    raw_turns: list[Turn],
    observability_level: ObservabilityLevel,
    manifest: AppManifest | None,
) -> EvalContext:
    """Build an evaluator context from a snapshot of the raw trace.

    Returns:
        EvalContext: Context holding a shallow snapshot of raw turns.
    """
    return EvalContext(
        turns=list(raw_turns),
        observability_level=observability_level,
        manifest=manifest,
    )


async def run_trace_async(
    *,
    session: Session,
    driver: PromptDriver,
    max_turns: int,
    observability_level: ObservabilityLevel,
    stop_when: Evaluator | None = None,
    manifest: AppManifest | None = None,
) -> TraceRun:
    """Drive a linear conversation with optional online stopping.

    The runner does not own session lifetime or exception conversion. Callers
    keep the session context active around this function, and exceptions from
    the driver, session, or evaluator propagate unchanged.

    Args:
        session: Active agent session.
        driver: Prompt source for the conversation.
        max_turns: Maximum number of requests sent to the agent.
        observability_level: What the adapter can observe.
        stop_when: Optional evaluator checked after every response. A detected
            outcome terminates the trace.
        manifest: Agent capabilities exposed to evaluators.

    Returns:
        TraceRun: Completed turns, termination reason, and online evidence.

    Raises:
        ValueError: If ``max_turns`` is negative.
    """
    if max_turns < 0:
        msg = "max_turns must be non-negative."
        raise ValueError(msg)

    run = TraceRun(
        termination_reason=TerminationReason.MAX_TURNS,
        observability_level=observability_level,
        manifest=manifest,
    )

    for turn_index in range(max_turns):
        decision = await driver.next_prompt_async(history=list(run.turns))
        if decision is None:
            run.termination_reason = TerminationReason.DRIVER_EXHAUSTED
            return run

        response = await session.send_async(decision.request)
        raw_turn = Turn(
            request=decision.request,
            response=response,
            turn_number=turn_index,
            driver_reasoning=decision.reasoning,
        )
        run.raw_turns.append(raw_turn)

        if stop_when is None:
            run.turns.append(raw_turn)
            continue

        context = _evaluation_context(
            raw_turns=run.raw_turns,
            observability_level=observability_level,
            manifest=manifest,
        )
        evaluation = await stop_when.evaluate_async(context=context)
        run.latest_online_evaluation = EvaluationRecord(
            evaluator=stop_when,
            context=context,
            result=evaluation,
        )
        run.turns.append(
            replace(
                raw_turn,
                eval_result=evaluation,
                eval_role=EvaluationRole.STOP_CONDITION,
            ),
        )
        if evaluation.detected:
            run.termination_reason = TerminationReason.STOP_CONDITION
            return run

    return run


async def evaluate_terminal_async(
    *,
    evaluator: Evaluator,
    run: TraceRun,
) -> EvalResult | None:
    """Evaluate the terminal raw trace, reusing an identical online judgment.

    Args:
        evaluator: Evaluator responsible for the final verdict.
        run: Completed trace from :func:`run_trace_async`.

    Returns:
        EvalResult | None: Final evaluation, or None when no turns exist.

    Call this before leaving any active session or injection context required
    by the evaluator. Requests, responses, and their nested values are treated
    as immutable after the runner appends them.
    """
    if not run.raw_turns:
        return None

    record = run.latest_online_evaluation
    if (
        record is not None
        and record.evaluator is evaluator
        and len(record.context.turns) == len(run.raw_turns)
        and all(
            evaluated is terminal
            for evaluated, terminal in zip(
                record.context.turns,
                run.raw_turns,
                strict=True,
            )
        )
    ):
        return replace(record.result, evidence=list(record.result.evidence))

    context = _evaluation_context(
        raw_turns=run.raw_turns,
        observability_level=run.observability_level,
        manifest=run.manifest,
    )
    return await evaluator.evaluate_async(context=context)
