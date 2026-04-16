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
from rampart.probes import Probes
from tests.fixtures import MockAdapter


def _adapter(*, responses: list[Response]) -> MockAdapter:
    """Build a MockAdapter for testing."""
    return MockAdapter(
        responses=responses,
        manifest=AppManifest(name="test-agent"),
    )


class _DetectsAlways(BaseEvaluator):
    """Evaluator stub that always detects."""

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        return EvalResult(outcome=EvalOutcome.DETECTED, rationale="always detected")


class _NeverDetects(BaseEvaluator):
    """Evaluator stub that never detects."""

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        return EvalResult(outcome=EvalOutcome.NOT_DETECTED, rationale="never detected")


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

    @pytest.mark.asyncio
    async def test_detected_means_safe_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert result.status == SafetyStatus.SAFE

    @pytest.mark.asyncio
    async def test_not_detected_means_unsafe_async(self) -> None:
        adapter = _adapter(responses=[Response(text="nope")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_NeverDetects(),
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status == SafetyStatus.UNSAFE


class TestProbeStrategyName:
    """strategy_name is 'probe'."""

    @pytest.mark.asyncio
    async def test_strategy_name_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="test",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.strategy == "probe"


class TestProbePromptCoercion:
    """Probes.behavior accepts str, list[str], and PromptDriver."""

    @pytest.mark.asyncio
    async def test_str_prompt_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompt="hello",
            evaluator=_DetectsAlways(),
        ).execute_async(adapter=adapter)

        assert result.safe is True
        assert len(result.turns) == 1
        assert result.turns[0].request.prompt == "hello"

    @pytest.mark.asyncio
    async def test_list_prompt_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompts=["first", "second"],
            evaluator=_NeverDetects(),
        ).execute_async(adapter=adapter)

        assert len(result.turns) == 2
        assert result.turns[0].request.prompt == "first"
        assert result.turns[1].request.prompt == "second"

    @pytest.mark.asyncio
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
            Probes.behavior(
                prompt="hello",
                driver=StaticDriver(prompts=["driven"]),
                evaluator=_DetectsAlways(),
            )

    def test_both_prompt_and_prompts_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Probes.behavior(
                prompt="hello",
                prompts=["a", "b"],
                evaluator=_DetectsAlways(),
            )

    def test_no_source_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            Probes.behavior(evaluator=_DetectsAlways())


class TestProbeInfrastructureError:
    """InfrastructureError becomes an ERROR result."""

    @pytest.mark.asyncio
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
        assert "Infrastructure error" in result.summary


class TestProbeEndToEnd:
    """Probe flow works end-to-end with MockAdapter."""

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
    """Max turns produces ERROR status."""

    @pytest.mark.asyncio
    async def test_max_turns_error_async(self) -> None:
        adapter = _adapter(responses=[Response(text="ok")])

        result = await Probes.behavior(
            prompts=["a", "b", "c"],
            evaluator=_NeverDetects(),
            max_turns=2,
        ).execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status == SafetyStatus.ERROR
        assert "Max turns" in result.summary
