# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the shared linear trace runner."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rampart.core.evaluator import Evaluator
from rampart.core.manifest import AppManifest
from rampart.core.prompt_driver import PromptDecision
from rampart.core.trace import evaluate_terminal_async, run_trace_async
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    EvaluationRole,
    ObservabilityLevel,
    Request,
    Response,
    TerminationReason,
    Turn,
)
from rampart.drivers.static import StaticDriver
from tests.fixtures import MockSession


def _session(*responses: str) -> MockSession:
    """Build a session returning the supplied response texts."""
    return MockSession(responses=[Response(text=text) for text in responses])


def _evaluator(*outcomes: EvalOutcome) -> AsyncMock:
    """Build an evaluator mock returning outcomes in order."""
    evaluator = AsyncMock(spec=Evaluator)
    evaluator.evaluate_async.side_effect = [
        EvalResult(outcome=outcome, rationale=f"call {index}")
        for index, outcome in enumerate(outcomes)
    ]
    return evaluator


class TestRunTraceAsync:
    async def test_driver_exhaustion_returns_raw_turns_async(self) -> None:
        run = await run_trace_async(
            session=_session("r1", "r2"),
            driver=StaticDriver(prompts=["p1", "p2"]),
            max_turns=3,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        assert run.termination_reason is TerminationReason.DRIVER_EXHAUSTED
        assert [turn.response.text for turn in run.turns] == ["r1", "r2"]
        assert run.turns == run.raw_turns
        assert run.latest_online_evaluation is None

    async def test_turn_budget_is_a_normal_termination_async(self) -> None:
        run = await run_trace_async(
            session=_session("r1", "r2", "r3"),
            driver=StaticDriver(prompts=["p1", "p2", "p3"]),
            max_turns=2,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        assert run.termination_reason is TerminationReason.MAX_TURNS
        assert len(run.turns) == 2

    async def test_zero_budget_does_not_call_driver_async(self) -> None:
        driver = AsyncMock()

        run = await run_trace_async(
            session=_session("unused"),
            driver=driver,
            max_turns=0,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        assert run.termination_reason is TerminationReason.MAX_TURNS
        assert run.turns == []
        driver.next_prompt_async.assert_not_awaited()

    async def test_stop_condition_annotates_only_public_history_async(self) -> None:
        evaluator = _evaluator(EvalOutcome.NOT_DETECTED, EvalOutcome.DETECTED)
        manifest = AppManifest(name="agent")

        run = await run_trace_async(
            session=_session("r1", "r2", "r3"),
            driver=StaticDriver(prompts=["p1", "p2", "p3"]),
            max_turns=3,
            observability_level=ObservabilityLevel.TOOL_ONLY,
            stop_when=evaluator,
            manifest=manifest,
        )

        assert run.termination_reason is TerminationReason.STOP_CONDITION
        assert len(run.turns) == 2
        assert all(
            turn.eval_role is EvaluationRole.STOP_CONDITION for turn in run.turns
        )
        assert all(turn.eval_result is not None for turn in run.turns)
        assert all(turn.eval_result is None for turn in run.raw_turns)
        contexts = [
            call.kwargs["context"] for call in evaluator.evaluate_async.await_args_list
        ]
        assert [len(context.turns) for context in contexts] == [1, 2]
        assert all(
            turn.eval_result is None for context in contexts for turn in context.turns
        )
        assert all(
            context.observability_level is ObservabilityLevel.TOOL_ONLY
            for context in contexts
        )
        assert contexts[-1].manifest is manifest

    async def test_driver_cannot_mutate_owned_history_list_async(self) -> None:
        class MutatingDriver:
            def __init__(self) -> None:
                self.calls = 0

            async def next_prompt_async(
                self,
                *,
                history: list[Turn],
            ) -> PromptDecision | None:
                history.append(
                    Turn(
                        request=Request(prompt="injected"),
                        response=Response(text="injected"),
                    ),
                )
                if self.calls:
                    return None
                self.calls += 1
                return PromptDecision(request=Request(prompt="p"))

        run = await run_trace_async(
            session=_session("r"),
            driver=MutatingDriver(),
            max_turns=2,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        assert len(run.turns) == 1
        assert run.turns[0].request.prompt == "p"

    async def test_evaluator_exception_propagates_async(self) -> None:
        evaluator = AsyncMock(spec=Evaluator)
        evaluator.evaluate_async.side_effect = RuntimeError("judge failed")

        with pytest.raises(RuntimeError, match="judge failed"):
            await run_trace_async(
                session=_session("r"),
                driver=StaticDriver(prompts=["p"]),
                max_turns=1,
                observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
                stop_when=evaluator,
            )


class TestEvaluateTerminalAsync:
    async def test_empty_trace_skips_evaluator_async(self) -> None:
        evaluator = _evaluator(EvalOutcome.DETECTED)
        run = await run_trace_async(
            session=_session("unused"),
            driver=StaticDriver(prompts=[]),
            max_turns=1,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        result = await evaluate_terminal_async(evaluator=evaluator, run=run)

        assert result is None
        assert run.termination_reason is TerminationReason.DRIVER_EXHAUSTED
        evaluator.evaluate_async.assert_not_awaited()

    @pytest.mark.parametrize(
        "outcomes",
        [
            (EvalOutcome.DETECTED,),
            (EvalOutcome.NOT_DETECTED,),
        ],
    )
    async def test_reuses_identical_latest_online_evaluation_async(
        self,
        outcomes: tuple[EvalOutcome, ...],
    ) -> None:
        evaluator = _evaluator(*outcomes)
        run = await run_trace_async(
            session=_session("r"),
            driver=StaticDriver(prompts=["p"]),
            max_turns=1,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
            stop_when=evaluator,
        )
        online_result = run.latest_online_evaluation
        assert online_result is not None

        result = await evaluate_terminal_async(evaluator=evaluator, run=run)

        assert result == online_result.result
        assert result is not online_result.result
        assert result.evidence is not online_result.result.evidence
        assert evaluator.evaluate_async.await_count == 1

    async def test_non_firing_stop_reuses_terminal_prefix_without_extra_call_async(
        self,
    ) -> None:
        evaluator = _evaluator(
            EvalOutcome.NOT_DETECTED,
            EvalOutcome.NOT_DETECTED,
            EvalOutcome.NOT_DETECTED,
        )
        run = await run_trace_async(
            session=_session("r1", "r2", "r3"),
            driver=StaticDriver(prompts=["p1", "p2", "p3"]),
            max_turns=3,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
            stop_when=evaluator,
        )

        result = await evaluate_terminal_async(evaluator=evaluator, run=run)

        assert result is not None and result.outcome is EvalOutcome.NOT_DETECTED
        assert evaluator.evaluate_async.await_count == 3

    async def test_distinct_evaluator_runs_once_on_terminal_trace_async(self) -> None:
        stop = _evaluator(EvalOutcome.NOT_DETECTED)
        verdict = _evaluator(EvalOutcome.DETECTED)
        manifest = AppManifest(name="agent")
        run = await run_trace_async(
            session=_session("r"),
            driver=StaticDriver(prompts=["p"]),
            max_turns=1,
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            stop_when=stop,
            manifest=manifest,
        )

        result = await evaluate_terminal_async(
            evaluator=verdict,
            run=run,
        )

        assert result is not None and result.outcome is EvalOutcome.DETECTED
        verdict.evaluate_async.assert_awaited_once()
        context = verdict.evaluate_async.await_args.kwargs["context"]
        assert context.turns == run.raw_turns
        assert context.observability_level is ObservabilityLevel.RESPONSE_ONLY
        assert all(turn.eval_result is None for turn in context.turns)

    async def test_post_run_trace_mutation_prevents_reuse_async(self) -> None:
        evaluator = _evaluator(EvalOutcome.NOT_DETECTED, EvalOutcome.DETECTED)
        run = await run_trace_async(
            session=_session("r", "later"),
            driver=StaticDriver(prompts=["p"]),
            max_turns=1,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
            stop_when=evaluator,
        )
        run.raw_turns.append(
            Turn(
                request=Request(prompt="later"),
                response=Response(text="later"),
                turn_number=1,
            ),
        )

        result = await evaluate_terminal_async(evaluator=evaluator, run=run)

        assert result is not None and result.outcome is EvalOutcome.DETECTED
        assert evaluator.evaluate_async.await_count == 2

    async def test_undetermined_stop_does_not_terminate_async(self) -> None:
        evaluator = _evaluator(
            EvalOutcome.UNDETERMINED,
            EvalOutcome.NOT_DETECTED,
        )
        run = await run_trace_async(
            session=_session("r1", "r2"),
            driver=StaticDriver(prompts=["p1", "p2"]),
            max_turns=2,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
            stop_when=evaluator,
        )

        assert run.termination_reason is TerminationReason.MAX_TURNS
        assert len(run.turns) == 2
        assert run.turns[0].eval_role is EvaluationRole.STOP_CONDITION


async def test_negative_turn_budget_raises_async() -> None:
    """Negative budgets are rejected rather than treated as zero."""
    with pytest.raises(ValueError, match="non-negative"):
        await run_trace_async(
            session=_session("unused"),
            driver=StaticDriver(prompts=[]),
            max_turns=-1,
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )
