# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.tool_called — ToolCalled evaluator."""

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    ObservabilityLevel,
    Request,
    Response,
    ToolCall,
    Turn,
)
from rampart.evaluators import ToolCalled


def _ctx_with_tool_calls(
    *tool_calls: ToolCall,
    observability: ObservabilityLevel = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
) -> EvalContext:
    """Build an EvalContext with a single turn containing the given tool calls."""
    return EvalContext(
        turns=[
            Turn(
                request=Request(prompt="test"),
                response=Response(text="ok", tool_calls=list(tool_calls)),
            ),
        ],
        observability_level=observability,
    )


def _multi_turn_ctx(turns_tool_calls: list[list[ToolCall]]) -> EvalContext:
    """Build an EvalContext with multiple turns, each with its own tool calls."""
    return EvalContext(
        turns=[
            Turn(
                request=Request(prompt=f"turn-{i}"),
                response=Response(text="ok", tool_calls=tcs),
                turn_number=i,
            )
            for i, tcs in enumerate(turns_tool_calls)
        ],
    )


class TestToolCalledDetection:
    async def test_detects_by_name_async(self) -> None:
        ctx = _ctx_with_tool_calls(ToolCall(name="send_email"))
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_wrong_name_async(self) -> None:
        ctx = _ctx_with_tool_calls(ToolCall(name="read_file"))
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_not_detected_no_tool_calls_async(self) -> None:
        ctx = _ctx_with_tool_calls()
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledParameterMatching:
    async def test_exact_parameter_match_async(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "evil@evil.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled("send_email", to="evil@evil.com").evaluate_async(
            context=ctx,
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_exact_parameter_mismatch_async(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "friend@company.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled("send_email", to="evil@evil.com").evaluate_async(
            context=ctx,
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_predicate_parameter_match_async(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "evil@evil.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: "evil" in str(v),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_predicate_parameter_mismatch_async(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "friend@company.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: "evil" in str(v),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_missing_parameter_returns_none_to_predicate_async(self) -> None:
        tc = ToolCall(name="send_email", arguments={})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: v is not None,
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledMultiTurn:
    async def test_scans_across_turns_async(self) -> None:
        ctx = _multi_turn_ctx(
            [
                [],
                [ToolCall(name="send_email", arguments={"to": "evil@evil.com"})],
            ],
        )
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_across_turns_async(self) -> None:
        ctx = _multi_turn_ctx(
            [
                [ToolCall(name="read_file")],
                [ToolCall(name="query_db")],
            ],
        )
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledObservability:
    """A missing tool call is only evidence when the adapter reports tool calls."""

    async def test_undetermined_when_tool_calls_not_reported(self) -> None:
        ctx = _ctx_with_tool_calls(observability=ObservabilityLevel.RESPONSE_ONLY)
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_undetermined_rationale_names_the_level_and_tool(self) -> None:
        ctx = _ctx_with_tool_calls(observability=ObservabilityLevel.RESPONSE_ONLY)
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert "response_only" in result.rationale
        assert "send_email" in result.rationale

    async def test_not_detected_when_tool_calls_are_reported(self) -> None:
        ctx = _ctx_with_tool_calls(observability=ObservabilityLevel.TOOL_ONLY)
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_reported_tool_call_still_detected_below_declared_level(self) -> None:
        ctx = _ctx_with_tool_calls(
            ToolCall(name="send_email"),
            observability=ObservabilityLevel.RESPONSE_ONLY,
        )
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED


class TestToolCalledComposition:
    async def test_composable_with_or_async(self) -> None:
        tc = ToolCall(name="send_email")
        ctx = _ctx_with_tool_calls(tc)
        composed = ToolCalled("send_email") | ToolCalled("delete_file")
        result = await composed.evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_undetermined_propagates_through_or(self) -> None:
        ctx = _ctx_with_tool_calls(observability=ObservabilityLevel.RESPONSE_ONLY)
        composed = ToolCalled("send_email") | ToolCalled("delete_file")
        result = await composed.evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.UNDETERMINED
