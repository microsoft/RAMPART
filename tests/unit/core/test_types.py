# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.types — core data model."""

import pytest

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)


class TestPayload:
    def test_construction_with_defaults(self):
        p = Payload(content="test payload")
        assert p.content == "test payload"
        assert len(p.id) == 12
        assert p.format is PayloadFormat.TEXT
        assert p.metadata == {}

    def test_explicit_id(self):
        p = Payload(content="x", id="my-id")
        assert p.id == "my-id"

    def test_unique_ids(self):
        p1 = Payload(content="a")
        p2 = Payload(content="b")
        assert p1.id != p2.id


class TestToolCall:
    def test_construction_with_defaults(self):
        tc = ToolCall(name="send_email")
        assert tc.name == "send_email"
        assert tc.arguments == {}
        assert tc.result is None
        assert tc.timestamp is None

    def test_with_arguments(self):
        tc = ToolCall(name="send_email", arguments={"to": "evil@evil.com"})
        assert tc.arguments["to"] == "evil@evil.com"


class TestSideEffect:
    def test_construction_with_defaults(self):
        se = SideEffect(kind="http_request")
        assert se.kind == "http_request"
        assert se.details == {}


class TestResponse:
    def test_construction_with_defaults(self):
        r = Response(text="Hello")
        assert r.text == "Hello"
        assert r.tool_calls == []
        assert r.side_effects == []
        assert r.metadata == {}


class TestTurn:
    def test_construction_with_defaults(self):
        r = Response(text="response")
        t = Turn(request=Request(prompt="hello"), response=r)
        assert t.request.prompt == "hello"
        assert t.turn_number == 0
        assert t.request.attachments == []
        assert t.timestamp is None
        assert t.driver_reasoning == ""


class TestEvalResult:
    def test_detected_property_true(self):
        er = EvalResult(outcome=EvalOutcome.DETECTED)
        assert er.detected is True

    def test_detected_property_false_not_detected(self):
        er = EvalResult(outcome=EvalOutcome.NOT_DETECTED)
        assert er.detected is False

    def test_detected_property_false_undetermined(self):
        er = EvalResult(outcome=EvalOutcome.UNDETERMINED)
        assert er.detected is False

    def test_defaults(self):
        er = EvalResult(outcome=EvalOutcome.DETECTED)
        assert er.confidence == 1.0
        assert er.evidence == []
        assert er.rationale == ""


class TestEvalContext:
    def _make_turn(
        self,
        prompt: str = "p",
        text: str = "r",
        tool_calls: list[ToolCall] | None = None,
        side_effects: list[SideEffect] | None = None,
    ) -> Turn:
        return Turn(
            request=Request(prompt=prompt),
            response=Response(
                text=text,
                tool_calls=tool_calls or [],
                side_effects=side_effects or [],
            ),
        )

    def test_current_turn_raises_on_empty(self):
        ctx = EvalContext(turns=[])
        with pytest.raises(ValueError, match="No turns"):
            _ = ctx.current_turn

    def test_current_turn_returns_last(self):
        t1 = self._make_turn(prompt="first")
        t2 = self._make_turn(prompt="second")
        ctx = EvalContext(turns=[t1, t2])
        assert ctx.current_turn is t2

    def test_text_returns_current_turn_response_text(self):
        ctx = EvalContext(turns=[self._make_turn(text="hello world")])
        assert ctx.text == "hello world"

    def test_all_tool_calls_spans_turns(self):
        tc1 = ToolCall(name="tool_a")
        tc2 = ToolCall(name="tool_b")
        tc3 = ToolCall(name="tool_c")
        t1 = self._make_turn(tool_calls=[tc1, tc2])
        t2 = self._make_turn(tool_calls=[tc3])
        ctx = EvalContext(turns=[t1, t2])
        assert ctx.all_tool_calls == [tc1, tc2, tc3]

    def test_all_tool_calls_empty(self):
        ctx = EvalContext(turns=[self._make_turn()])
        assert ctx.all_tool_calls == []

    def test_all_side_effects_spans_turns(self):
        se1 = SideEffect(kind="http")
        se2 = SideEffect(kind="file")
        t1 = self._make_turn(side_effects=[se1])
        t2 = self._make_turn(side_effects=[se2])
        ctx = EvalContext(turns=[t1, t2])
        assert ctx.all_side_effects == [se1, se2]

    def test_from_response(self):
        r = Response(
            text="answer",
            tool_calls=[ToolCall(name="calc")],
        )
        ctx = EvalContext.from_response(response=r, prompt="question")
        assert len(ctx.turns) == 1
        assert ctx.turns[0].request.prompt == "question"
        assert ctx.turns[0].response is r
        assert ctx.text == "answer"
        assert len(ctx.all_tool_calls) == 1

    def test_from_response_defaults(self):
        r = Response(text="hi")
        ctx = EvalContext.from_response(response=r)
        assert ctx.turns[0].request.prompt == ""
        assert ctx.manifest is None


class TestObservabilityLevel:
    def test_values(self):
        assert ObservabilityLevel.TOOL_AND_SIDE_EFFECTS.value == "tool_and_side_effects"
        assert ObservabilityLevel.TOOL_ONLY.value == "tool_only"
        assert ObservabilityLevel.RESPONSE_ONLY.value == "response_only"


class TestPayloadFormat:
    def test_values(self):
        assert PayloadFormat.TEXT.value == "text"
        assert PayloadFormat.HTML.value == "html"
        assert PayloadFormat.MARKDOWN.value == "markdown"
