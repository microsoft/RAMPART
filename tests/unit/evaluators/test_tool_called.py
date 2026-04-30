# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.tool_called — ToolCalled evaluator."""

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    Request,
    Response,
    ToolCall,
    Turn,
)
from rampart.evaluators import ToolCalled


def _ctx_with_tool_calls(*tool_calls: ToolCall) -> EvalContext:
    """Build an EvalContext with a single turn containing the given tool calls."""
    return EvalContext(
        turns=[
            Turn(
                request=Request(prompt="test"),
                response=Response(text="ok", tool_calls=list(tool_calls)),
            ),
        ],
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
    async def test_detects_by_name(self) -> None:
        ctx = _ctx_with_tool_calls(ToolCall(name="send_email"))
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_wrong_name(self) -> None:
        ctx = _ctx_with_tool_calls(ToolCall(name="read_file"))
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_not_detected_no_tool_calls(self) -> None:
        ctx = _ctx_with_tool_calls()
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledParameterMatching:
    async def test_exact_parameter_match(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "evil@evil.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled("send_email", to="evil@evil.com").evaluate_async(
            context=ctx,
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_exact_parameter_mismatch(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "friend@company.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled("send_email", to="evil@evil.com").evaluate_async(
            context=ctx,
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_predicate_parameter_match(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "evil@evil.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: "evil" in str(v),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_predicate_parameter_mismatch(self) -> None:
        tc = ToolCall(name="send_email", arguments={"to": "friend@company.com"})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: "evil" in str(v),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_missing_parameter_returns_none_to_predicate(self) -> None:
        tc = ToolCall(name="send_email", arguments={})
        ctx = _ctx_with_tool_calls(tc)
        result = await ToolCalled(
            "send_email",
            to=lambda v: v is not None,
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledMultiTurn:
    async def test_scans_across_turns(self) -> None:
        ctx = _multi_turn_ctx(
            [
                [],
                [ToolCall(name="send_email", arguments={"to": "evil@evil.com"})],
            ],
        )
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_across_turns(self) -> None:
        ctx = _multi_turn_ctx(
            [
                [ToolCall(name="read_file")],
                [ToolCall(name="query_db")],
            ],
        )
        result = await ToolCalled("send_email").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestToolCalledComposition:
    async def test_composable_with_or(self) -> None:
        tc = ToolCall(name="send_email")
        ctx = _ctx_with_tool_calls(tc)
        composed = ToolCalled("send_email") | ToolCalled("delete_file")
        result = await composed.evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED
