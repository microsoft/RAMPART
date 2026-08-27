# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for JsonFileReportSink serialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from rampart.core.result import HarmCategory, Result, SafetyStatus
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
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
        observability_level=ObservabilityLevel.RESPONSE_ONLY,
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

    def test_result_reports_the_observability_level(self) -> None:
        # Not the value _result_with_turns defaults to, so a hardcoded
        # literal in the sink cannot satisfy this.
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        result = _result_with_turns()
        result.observability_level = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS

        data = sink._serialize_result(result)

        assert data["observability_level"] == "tool_and_side_effects"

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
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
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
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
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
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert turn_data["eval_outcome"] == "detected"
        assert turn_data["eval_confidence"] == pytest.approx(0.95)
        assert turn_data["eval_rationale"] == "found secret"

    def test_turns_report_a_non_finite_confidence_as_null(self) -> None:
        # Parity with the xdist path: a NaN confidence must serialize to null
        # here too, so neither report shows a fabricated number.
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        turn = Turn(
            request=Request(prompt="hi"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(
                outcome=EvalOutcome.DETECTED,
                confidence=float("nan"),
                rationale="found secret",
            ),
        )
        result = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        assert data["turns"][0]["eval_confidence"] is None

    def test_turns_include_undetermined_operands_when_present(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        turn = Turn(
            request=Request(prompt="hi"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                undetermined_operands=["side effects not reported"],
            ),
        )
        result = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        turn_data = data["turns"][0]
        assert turn_data["eval_undetermined_operands"] == [
            "side effects not reported",
        ]

    def test_a_hostile_operand_value_does_not_lose_the_report(self) -> None:
        class Boom:
            def __bool__(self) -> bool:
                raise RuntimeError("boom")

            def __iter__(self) -> object:
                raise RuntimeError("boom")

        sink = JsonFileReportSink(output_dir=Path("out"))
        turn = Turn(
            request=Request(prompt="go"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(
                outcome=EvalOutcome.DETECTED,
                undetermined_operands=Boom(),  # ty: ignore[invalid-argument-type]
            ),
        )
        result = Result(
            status=SafetyStatus.UNSAFE,
            summary="real detection",
            turns=[turn],
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        data = sink._serialize_result(result)

        assert data["summary"] == "real detection"
        assert "eval_undetermined_operands" not in data["turns"][0]

    def test_a_hostile_rationale_does_not_lose_the_report(self) -> None:
        class Boom:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        sink = JsonFileReportSink(output_dir=Path("out"))
        turn = Turn(
            request=Request(prompt="go"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(
                outcome=EvalOutcome.DETECTED,
                rationale=Boom(),  # ty: ignore[invalid-argument-type]
            ),
        )
        result = Result(
            status=SafetyStatus.UNSAFE,
            summary="real detection",
            turns=[turn],
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )

        data = sink._serialize_result(result)

        assert data["summary"] == "real detection"
        assert data["turns"][0]["eval_rationale"] == "<unprintable value>"

    def test_turns_omit_undetermined_operands_when_empty(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        turn = Turn(
            request=Request(prompt="hi"),
            response=Response(text="done"),
            turn_number=0,
            eval_result=EvalResult(outcome=EvalOutcome.NOT_DETECTED),
        )
        result = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
            turns=[turn],
        )

        data = sink._serialize_result(result)

        assert "eval_undetermined_operands" not in data["turns"][0]

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
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
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

    async def test_emitted_file_contains_metadata_async(self, tmp_path: Path) -> None:
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

    async def test_same_timestamp_preserves_every_report_async(
        self,
        tmp_path: Path,
    ) -> None:
        sink = JsonFileReportSink(output_dir=tmp_path)
        fixed = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        with patch("rampart.reporting.json_file.datetime") as clock:
            clock.now.return_value = fixed
            for run in range(3):
                await sink.emit_async(report=TestRunReport(metadata={"run": run}))

        files = {path.name: path for path in tmp_path.glob("run_report_*.json")}
        assert set(files) == {
            "run_report_2026-08-27T12-00-00.json",
            "run_report_2026-08-27T12-00-00_1.json",
            "run_report_2026-08-27T12-00-00_2.json",
        }
        for run, suffix in enumerate(("", "_1", "_2")):
            path = files[f"run_report_2026-08-27T12-00-00{suffix}.json"]
            assert json.loads(path.read_text(encoding="utf-8"))["metadata"] == {
                "run": run,
            }

    async def test_existing_report_is_not_replaced_async(self, tmp_path: Path) -> None:
        original = tmp_path / "run_report_2026-08-27T12-00-00.json"
        original.write_text("keep me", encoding="utf-8")
        sink = JsonFileReportSink(output_dir=tmp_path)
        fixed = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        with patch("rampart.reporting.json_file.datetime") as clock:
            clock.now.return_value = fixed
            await sink.emit_async(report=TestRunReport(metadata={"run": "new"}))

        assert original.read_text(encoding="utf-8") == "keep me"
        collision = tmp_path / "run_report_2026-08-27T12-00-00_1.json"
        assert json.loads(collision.read_text(encoding="utf-8"))["metadata"] == {
            "run": "new",
        }

    async def test_raises_after_all_suffixes_are_taken_async(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        stem = "run_report_2026-08-27T12-00-00"
        (tmp_path / f"{stem}.json").write_text("first", encoding="utf-8")
        (tmp_path / f"{stem}_1.json").write_text("second", encoding="utf-8")
        monkeypatch.setattr(JsonFileReportSink, "_MAX_FILENAME_ATTEMPTS", 2)
        sink = JsonFileReportSink(output_dir=tmp_path)
        fixed = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)

        with patch("rampart.reporting.json_file.datetime") as clock:
            clock.now.return_value = fixed
            with pytest.raises(FileExistsError, match="Unable to reserve"):
                await sink.emit_async(report=TestRunReport())


class TestReportMetadata:
    """Run-level TestRunReport.metadata is projected into the JSON output."""

    def test_report_metadata_appears_in_serialized_output(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        report = TestRunReport(
            metadata={
                "xdist_active": True,
                "worker_count": 4,
                "dist_mode": "loadgroup",
            },
        )

        data = sink._serialize_report(report)

        assert data["metadata"] == {
            "xdist_active": True,
            "worker_count": 4,
            "dist_mode": "loadgroup",
        }

    def test_incomplete_run_metadata_appears_in_serialized_output(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        report = TestRunReport(
            metadata={
                "incomplete": True,
                "incomplete_reasons": ["worker gw1 payload truncated (size cap)"],
            },
        )

        data = sink._serialize_report(report)

        assert data["metadata"]["incomplete"] is True
        assert data["metadata"]["incomplete_reasons"] == [
            "worker gw1 payload truncated (size cap)",
        ]

    def test_empty_metadata_serializes_as_empty_dict(self) -> None:
        sink = JsonFileReportSink(output_dir=Path("/tmp"))
        report = TestRunReport()

        data = sink._serialize_report(report)

        assert data["metadata"] == {}
