# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for JsonFileReportSink serialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rampart.core.result import HarmCategory, Result, SafetyStatus
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)
from rampart.reporting.json_file import JsonFileReportSink
from rampart.reporting.sink import TestRunReport


def _result_with_turns(
    *,
    response_metadata: dict[str, Any] | None = None,
    result_metadata: dict[str, Any] | None = None,
) -> Result:
    """Build a Result carrying turns with optional response metadata."""
    response = Response(
        text="answer",
        metadata=response_metadata or {},
    )
    turn = Turn(
        request=Request(prompt="hello"),
        response=response,
        turn_number=0,
    )
    return Result(
        safe=True,
        status=SafetyStatus.SAFE,
        summary="ok",
        turns=[turn],
        harm_category=HarmCategory.PROMPT_INJECTION,
        metadata=result_metadata or {},
    )


class TestSerializeResult:
    """_serialize_result includes metadata and turns."""

    def test_result_metadata_appears_in_output(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns(
            result_metadata={"conversation_id": "abc-123"},
        )

        data = sink._serialize_result(result)

        assert data["metadata"] == {"conversation_id": "abc-123"}

    def test_turn_response_metadata_appears_in_turns(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns(
            response_metadata={"thread_id": "t-456"},
        )

        data = sink._serialize_result(result)

        assert len(data["turns"]) == 1
        assert data["turns"][0]["response_metadata"] == {"thread_id": "t-456"}

    def test_turns_include_prompt_and_response_text(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns()

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert turn_data["prompt"] == "hello"
        assert turn_data["response_text"] == "answer"
        assert turn_data["turn_number"] == 0

    def test_turns_include_tool_calls_when_present(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        response = Response(
            text="done",
            tool_calls=[
                ToolCall(name="record_memory", arguments={"value": "user@example.com"}),
            ],
        )
        turn = Turn(request=Request(prompt="hi"), response=response, turn_number=0)
        result = Result(
            safe=False,
            status=SafetyStatus.UNSAFE,
            summary="memory poisoned",
            turns=[turn],
            harm_category=HarmCategory.MEMORY_POISONING,
        )

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert "tool_calls" in turn_data
        assert len(turn_data["tool_calls"]) == 1
        assert turn_data["tool_calls"][0]["name"] == "record_memory"
        assert turn_data["tool_calls"][0]["arguments"] == {"value": "user@example.com"}
        assert turn_data["tool_calls"][0]["result"] is None

    def test_turns_omit_tool_calls_when_empty(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns()

        data = sink._serialize_result(result)

        assert "tool_calls" not in data["turns"][0]

    def test_turns_include_side_effects_when_present(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        response = Response(
            text="done",
            side_effects=[
                SideEffect(kind="http_request", details={"url": "https://evil.com"}),
            ],
        )
        turn = Turn(request=Request(prompt="hi"), response=response, turn_number=0)
        result = Result(
            safe=False,
            status=SafetyStatus.UNSAFE,
            summary="exfiltration",
            turns=[turn],
            harm_category=HarmCategory.PROMPT_INJECTION,
        )

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert "side_effects" in turn_data
        assert turn_data["side_effects"][0]["kind"] == "http_request"

    def test_turns_include_eval_result_when_present(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        turn = Turn(
            request=Request(prompt="hi"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(
                outcome=EvalOutcome.DETECTED,
                confidence=0.95,
                rationale="found secret",
            ),
        )
        result = Result(
            safe=False,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert turn_data["eval_outcome"] == "detected"
        assert turn_data["eval_confidence"] == 0.95
        assert turn_data["eval_rationale"] == "found secret"

    def test_turns_omit_eval_result_when_none(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns()

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert "eval_outcome" not in turn_data

    def test_turns_include_driver_reasoning_when_present(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        turn = Turn(
            request=Request(prompt="hi"),
            response=Response(text="done"),
            turn_number=0,
            driver_reasoning="Trying a different angle",
        )
        result = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="ok",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        assert data["turns"][0]["driver_reasoning"] == "Trying a different angle"

    def test_turns_omit_driver_reasoning_when_empty(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns()

        data = sink._serialize_result(result)

        assert "driver_reasoning" not in data["turns"][0]


class TestEmitAsync:
    """emit_async writes a valid JSON file."""

    @pytest.mark.asyncio
    async def test_emitted_file_contains_metadata(self, tmp_path: Path) -> None:
        sink = JsonFileReportSink(output_dir=tmp_path)
        result = _result_with_turns(
            result_metadata={"conversation_id": "xyz"},
            response_metadata={"page_url": "https://example.com/chat"},
        )
        report = TestRunReport(results=[result])

        await sink.emit_async(report=report)

        files = list(tmp_path.glob("run_report_*.json"))
        assert len(files) == 1

        content = json.loads(files[0].read_text())
        category_results = content["by_harm_category"]["prompt_injection"]
        assert category_results[0]["metadata"] == {"conversation_id": "xyz"}
        assert category_results[0]["turns"][0]["response_metadata"] == {
            "page_url": "https://example.com/chat",
        }
