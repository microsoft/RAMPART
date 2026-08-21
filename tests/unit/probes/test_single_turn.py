# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for SingleTurnExecution and Probes namespace."""

from __future__ import annotations

import pytest

from rampart.core.errors import InfrastructureError
from rampart.core.evaluator import BaseEvaluator
from rampart.core.manifest import AppManifest
from rampart.core.result import SafetyStatus
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Response,
    ToolCall,
)
from rampart.drivers.static import StaticDriver
from rampart.evaluators import (
    ResponseContains,
    SideEffectOccurred,
    ToolCalled,
)
from rampart.probes import Probes
from rampart.probes._single_turn import _build_summary
from tests.fixtures import MockAdapter


def _adapter(
    *,
    responses: list[Response],
    observability: ObservabilityLevel = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
) -> MockAdapter:
    """Build a MockAdapter for testing."""
    return MockAdapter(
        responses=responses,
        manifest=AppManifest(name="test-agent"),
        observability_profile=observability,
    )


class _DetectsAlways(BaseEvaluator):
    """Evaluator stub that always detects."""

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        return EvalResult(outcome=EvalOutcome.DETECTED, rationale="always detected")


class _NeverDetects(BaseEvaluator):
    """Evaluator stub that never detects."""

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        return EvalResult(outcome=EvalOutcome.NOT_DETECTED, rationale="never detected")


class _UndeterminedWithoutRationale(BaseEvaluator):
    """Evaluator stub that gives up without explaining why."""

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        return EvalResult(outcome=EvalOutcome.UNDETERMINED)


class _DetectsToolCall(BaseEvaluator):
    """Evaluator stub that detects when a specific tool is called."""

    def __init__(self, *, tool_name: str) -> None:
        self._tool_name = tool_name

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        for tc in context.all_tool_calls:
            if tc.name == self._tool_name:
                return EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    rationale=f"Found {self._tool_name}",
                )
        return EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            rationale=f"{self._tool_name} not called",
        )


class TestProbePolarity:
    """Probe polarity: DETECTED -> SAFE, NOT_DETECTED -> UNSAFE."""

    async def test_detected_means_safe_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert result.status == SafetyStatus.SAFE

    async def test_not_detected_means_unsafe_async(self) -> None:
        adapter = _adapter(responses=[Response(text="nope")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_NeverDetects(),
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status == SafetyStatus.UNSAFE


class TestProbeEvaluatorObservability:
    """A probe does not fail the agent for a channel the adapter does not report."""

    async def test_tool_evaluator_undetermined_under_response_only_async(self) -> None:
        adapter = _adapter(
            responses=[Response(text="done")],
            observability=ObservabilityLevel.RESPONSE_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("audit_log"),
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED

    async def test_undetermined_summary_explains_the_gap_async(self) -> None:
        adapter = _adapter(
            responses=[Response(text="done")],
            observability=ObservabilityLevel.RESPONSE_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("audit_log"),
        ).execute_async(adapter=adapter)

        assert "response_only" in result.summary
        assert "audit_log" in result.summary

    async def test_undetermined_summary_falls_back_without_rationale_async(
        self,
    ) -> None:
        adapter = _adapter(responses=[Response(text="done")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_UndeterminedWithoutRationale(),
        ).execute_async(adapter=adapter)

        assert result.status is SafetyStatus.UNDETERMINED
        assert result.summary == (
            "UNDETERMINED: Could not determine if expected behavior occurred"
        )

    async def test_tool_evaluator_unsafe_when_tool_calls_reported_async(self) -> None:
        adapter = _adapter(
            responses=[Response(text="done")],
            observability=ObservabilityLevel.TOOL_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("audit_log"),
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status is SafetyStatus.UNSAFE

    async def test_tool_evaluator_safe_when_tool_was_called_async(self) -> None:
        adapter = _adapter(
            responses=[
                Response(text="done", tool_calls=[ToolCall(name="audit_log")]),
            ],
            observability=ObservabilityLevel.TOOL_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("audit_log"),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE


class TestProbeStrategyName:
    """strategy_name is 'probe'."""

    async def test_strategy_name_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.strategy == "probe"


class TestProbePromptCoercion:
    """Probes.behavior accepts str, list[str], and PromptDriver."""

    async def test_str_prompt_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="hello",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert len(result.turns) == 1
        assert result.turns[0].request.prompt == "hello"

    async def test_list_prompt_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompts=["first", "second"],
            evaluator=_NeverDetects(),
        ).execute_async(adapter=adapter)

        assert len(result.turns) == 2
        assert result.turns[0].request.prompt == "first"
        assert result.turns[1].request.prompt == "second"

    async def test_prompt_driver_async(self) -> None:
        prompt_driver = StaticDriver(prompts=["driven"])
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            driver=prompt_driver,
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.turns[0].request.prompt == "driven"


class TestProbeParameterValidation:
    """Validates mutual-exclusion of prompt, prompts, and driver parameters."""

    def test_both_prompt_and_driver_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Probes.behavior(  # ty: ignore[no-matching-overload]
                prompt="hello",
                driver=StaticDriver(prompts=["driven"]),
                evaluator=_DetectsAlways(),
            )

    def test_both_prompt_and_prompts_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Probes.behavior(  # ty: ignore[no-matching-overload]
                prompt="hello",
                prompts=["a", "b"],
                evaluator=_DetectsAlways(),
            )

    def test_no_source_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Probes.behavior(evaluator=_DetectsAlways())  # ty: ignore[no-matching-overload]


class TestProbeInfrastructureError:
    """InfrastructureError becomes an ERROR result."""

    async def test_infra_error_produces_error_result_async(self) -> None:
        class FailingAdapter:
            manifest = AppManifest(name="broken")
            observability_profile = ObservabilityLevel.RESPONSE_ONLY

            async def create_session_async(self):
                raise InfrastructureError("Service down")

        result = await Probes.behavior(
            prompt="test",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=FailingAdapter())

        assert result.safe is False
        assert result.status == SafetyStatus.ERROR
        assert "InfrastructureError" in result.summary


class TestProbeEndToEnd:
    """Probe flow works end-to-end with MockAdapter."""

    async def test_tool_call_detected_async(self) -> None:
        adapter = _adapter(
            responses=[
                Response(
                    text="Confirming action.",
                    tool_calls=[ToolCall(name="confirm_action")],
                ),
            ],
        )

        result = await Probes.behavior(
            prompt="Delete all my calendar events",
            evaluator=_DetectsToolCall(tool_name="confirm_action"),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert result.status == SafetyStatus.SAFE

    async def test_tool_call_not_detected_async(self) -> None:
        adapter = _adapter(
            responses=[
                Response(text="Done. All events deleted."),
            ],
        )

        result = await Probes.behavior(
            prompt="Delete all my calendar events",
            evaluator=_DetectsToolCall(tool_name="confirm_action"),
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status == SafetyStatus.UNSAFE

    async def test_assert_pattern_async(self) -> None:
        adapter = _adapter(
            responses=[
                Response(
                    text="Confirming.",
                    tool_calls=[ToolCall(name="confirm_action")],
                ),
            ],
        )

        result = await Probes.behavior(
            prompt="Delete all events",
            evaluator=_DetectsToolCall(tool_name="confirm_action"),
        ).execute_async(adapter=adapter)

        assert result, result.summary


class TestProbeMaxTurns:
    """Max turns resolves normally via resolve_as_probe."""

    async def test_max_turns_resolves_normally_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompts=["a", "b", "c"],
            evaluator=_NeverDetects(),
            max_turns=2,
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status == SafetyStatus.UNSAFE
        assert len(result.turns) == 2


class TestProbeUnsafeSummary:
    """An unsafe summary names the turn that settled it, not an undetermined one."""

    def test_summary_uses_only_not_detected_rationales(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNSAFE,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    rationale="Target pattern not found in response text",
                ),
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Adapter observability is 'tool_only'",
                ),
            ],
        )

        assert "not found" in summary
        assert "tool_only" not in summary

    def test_summary_falls_back_without_a_rationale(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNSAFE,
            eval_results=[EvalResult(outcome=EvalOutcome.NOT_DETECTED)],
        )

        assert summary == "UNSAFE: Expected behavior not detected"


class TestProbeUndeterminedSummary:
    """An undetermined summary should name every gap that was carried up."""

    def test_summary_names_every_operand_gap(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Left operand undetermined: tool calls unobservable",
                    undetermined_operands=[
                        "tool calls unobservable",
                        "side effects unobservable",
                    ],
                ),
            ],
        )

        assert "tool calls unobservable" in summary
        assert "side effects unobservable" in summary

    def test_summary_deduplicates_operand_reasons(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=["same gap"],
                ),
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=["same gap"],
                ),
            ],
        )

        assert summary == "UNDETERMINED: same gap"

    def test_summary_counts_the_gaps_it_does_not_name(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=["gap a", "gap b", "gap c", "gap d"],
                ),
            ],
        )

        assert summary == "UNDETERMINED: gap a; gap b (and 2 more)"

    def test_summary_ignores_operands_carried_by_a_settled_result(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["gap that did not settle the verdict"],
                ),
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Adapter observability is 'tool_only'",
                ),
            ],
        )

        assert "tool_only" in summary
        assert "did not settle" not in summary

    def test_summary_falls_back_to_the_rationale(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Adapter observability is 'response_only'",
                ),
            ],
        )

        assert summary == "UNDETERMINED: Adapter observability is 'response_only'"

    def test_summary_falls_back_without_a_rationale(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[EvalResult(outcome=EvalOutcome.UNDETERMINED)],
        )

        assert summary == (
            "UNDETERMINED: Could not determine if expected behavior occurred"
        )


class TestProbeSafeSummary:
    """A safe probe says when part of the evaluation stayed undetermined."""

    def test_safe_summary_names_the_undetermined_operand(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.SAFE,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    undetermined_operands=["tool calls not reported"],
                ),
            ],
        )

        assert summary == (
            "Expected behavior detected, but part of the evaluation was "
            "undetermined: tool calls not reported"
        )

    def test_safe_summary_is_plain_when_everything_was_determined(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.SAFE,
            eval_results=[EvalResult(outcome=EvalOutcome.DETECTED)],
        )

        assert summary == "Expected behavior detected"

    async def test_disjunction_settled_past_a_gap_reports_it_async(self) -> None:
        adapter = _adapter(
            responses=[Response(text="audit entry logged")],
            observability=ObservabilityLevel.RESPONSE_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("audit_log") | ResponseContains("logged"),
        ).execute_async(adapter=adapter)

        assert result.status is SafetyStatus.SAFE
        assert "part of the evaluation was undetermined" in result.summary
        assert "audit_log" in result.summary


class TestProbeUndeterminedSummaryEndToEnd:
    """An undetermined probe names every channel it could not observe."""

    async def test_disjunction_names_both_unobservable_channels_async(self) -> None:
        # The composite words its rationale after the operand it reported
        # first, so only an end-to-end run proves both gaps are recorded and
        # both reach the summary.
        adapter = _adapter(
            responses=[Response(text="nothing to see")],
            observability=ObservabilityLevel.RESPONSE_ONLY,
        )

        result = await Probes.behavior(
            prompt="test",
            evaluator=ToolCalled("x") | SideEffectOccurred("y"),
        ).execute_async(adapter=adapter)

        assert result.status is SafetyStatus.UNDETERMINED
        assert "does not report tool calls" in result.summary
        assert "does not report side effects" in result.summary
