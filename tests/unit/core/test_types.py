# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.types — core data model."""

import dataclasses
from pathlib import Path

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

    def test_binary_format_requires_artifact(self):
        with pytest.raises(TypeError, match="requires an artifact"):
            Payload(content="img", format=PayloadFormat.IMAGE)

    def test_text_format_rejects_artifact(self, tmp_path: Path) -> None:
        artifact = tmp_path / "file.txt"
        artifact.write_text("x")
        with pytest.raises(TypeError, match="artifact must be None"):
            Payload(content="text", format=PayloadFormat.TEXT, artifact=artifact)

    def test_binary_format_with_missing_artifact(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.png"
        with pytest.raises(FileNotFoundError, match="does not exist"):
            Payload(content="img", format=PayloadFormat.IMAGE, artifact=missing)

    def test_binary_format_with_valid_artifact(self, tmp_path: Path) -> None:
        artifact = tmp_path / "test.png"
        artifact.write_bytes(b"\x89PNG")
        p = Payload(content="img", format=PayloadFormat.IMAGE, artifact=artifact)
        assert p.artifact == artifact

    def test_str_short_content(self):
        p = Payload(content="hello")
        assert str(p) == "hello"

    def test_str_long_content_truncated(self):
        long_text = "x" * 300
        p = Payload(content=long_text)
        result = str(p)
        assert len(result) == 203  # 200 chars + "..."
        assert result.endswith("...")


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
        assert t.eval_result is None

    def test_eval_result_round_trips(self):
        er = EvalResult(outcome=EvalOutcome.DETECTED, rationale="found it")
        t = Turn(
            request=Request(prompt="p"),
            response=Response(text="r"),
            eval_result=er,
        )
        assert t.eval_result is er
        assert t.eval_result is not None and t.eval_result.detected is True

    def test_frozen_prevents_mutation(self):
        t = Turn(request=Request(prompt="p"), response=Response(text="r"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            t.eval_result = EvalResult(outcome=EvalOutcome.DETECTED)  # type: ignore[misc]


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

    def test_is_text_true_for_text_formats(self):
        assert PayloadFormat.TEXT.is_text is True
        assert PayloadFormat.HTML.is_text is True
        assert PayloadFormat.MARKDOWN.is_text is True

    def test_is_text_false_for_binary_formats(self):
        assert PayloadFormat.IMAGE.is_text is False
        assert PayloadFormat.PDF.is_text is False
        assert PayloadFormat.DOCX.is_text is False
        assert PayloadFormat.XLSX.is_text is False
        assert PayloadFormat.AUDIO.is_text is False

    def test_is_binary_true_for_binary_formats(self):
        assert PayloadFormat.IMAGE.is_binary is True
        assert PayloadFormat.PDF.is_binary is True
        assert PayloadFormat.DOCX.is_binary is True

    def test_is_binary_false_for_text_formats(self):
        assert PayloadFormat.TEXT.is_binary is False
        assert PayloadFormat.HTML.is_binary is False
        assert PayloadFormat.MARKDOWN.is_binary is False

    def test_extension_text_formats(self):
        assert PayloadFormat.TEXT.extension == ".txt"
        assert PayloadFormat.HTML.extension == ".html"
        assert PayloadFormat.MARKDOWN.extension == ".md"

    def test_extension_binary_formats(self):
        assert PayloadFormat.IMAGE.extension == ".png"
        assert PayloadFormat.PDF.extension == ".pdf"
        assert PayloadFormat.DOCX.extension == ".docx"
        assert PayloadFormat.XLSX.extension == ".xlsx"
        assert PayloadFormat.AUDIO.extension == ".wav"
