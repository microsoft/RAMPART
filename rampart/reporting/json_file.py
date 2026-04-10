# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""JSON file report sink.

Writes test run reports to timestamped JSON files under a
configurable output directory. Ships with the framework as a
built-in ``ReportSink`` for teams that want local file output
without building a custom sink.

Teams wire it up in their conftest::

    @pytest.fixture(scope="session")
    def rampart_sinks():
        return [JsonFileReportSink(output_dir=Path(".report"))]
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from rampart.core.result import Result
    from rampart.core.types import Turn
    from rampart.reporting.sink import TestRunReport


class JsonFileReportSink:
    """Writes the test run report to a JSON file.

    Each run produces a timestamped file:
    ``<output_dir>/run_report_2026-03-19T21-30-00.json``

    Args:
        output_dir (Path): Directory to write report files into.
            Created automatically if it does not exist.
    """

    def __init__(self, *, output_dir: Path) -> None:
        """Initialize with an output directory for report files."""
        self._output_dir = output_dir

    async def emit_async(self, *, report: TestRunReport) -> None:
        """Serialize the report to a JSON file.

        Args:
            report (TestRunReport): The aggregated test run results.
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
        filepath = self._output_dir / f"run_report_{timestamp}.json"

        data = self._serialize_report(report)
        filepath.write_text(json.dumps(data, indent=2, default=str))

    def _serialize_report(self, report: TestRunReport) -> dict[str, Any]:
        """Convert a TestRunReport to a JSON-serializable dict.

        Args:
            report (TestRunReport): The report to serialize.

        Returns:
            dict[str, Any]: JSON-serializable representation.
        """
        return {
            "total_runs": report.total_runs,
            "passed": report.passed,
            "failed": report.failed,
            "undetermined": report.undetermined,
            "errors": report.errors,
            "duration_seconds": report.duration_seconds,
            "population_summary": dataclasses.asdict(report.population_summary()),
            "by_harm_category": {
                category: [self._serialize_result(r) for r in results]
                for category, results in report.by_harm_category().items()
            },
        }

    def _serialize_result(self, result: Result) -> dict[str, Any]:
        """Convert a single Result to a JSON-serializable dict.

        Args:
            result (Result): The result to serialize.

        Returns:
            dict[str, Any]: JSON-serializable representation.
        """
        return {
            "safe": result.safe,
            "status": result.status.value,
            "summary": result.summary,
            "harm_category": str(result.harm_category)
            if result.harm_category
            else None,
            "strategy": result.strategy,
            "duration_seconds": result.duration_seconds,
            "metadata": result.metadata,
            "turns": [self._serialize_turn(t) for t in result.turns],
        }

    def _serialize_turn(self, turn: Turn) -> dict[str, Any]:
        """Convert a single Turn to a JSON-serializable dict.

        Args:
            turn (Turn): The turn to serialize.

        Returns:
            dict[str, Any]: JSON-serializable representation.
        """
        data: dict[str, Any] = {
            "turn_number": turn.turn_number,
            "prompt": turn.request.prompt,
            "response_text": turn.response.text,
            "response_metadata": turn.response.metadata,
        }
        if turn.response.tool_calls:
            data["tool_calls"] = [
                {
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "result": tc.result,
                }
                for tc in turn.response.tool_calls
            ]
        if turn.response.side_effects:
            data["side_effects"] = [
                {"kind": se.kind, "details": se.details}
                for se in turn.response.side_effects
            ]
        return data
