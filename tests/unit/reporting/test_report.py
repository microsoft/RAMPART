# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for reporting infrastructure."""

from __future__ import annotations

import pytest

from rampart.core.result import HarmCategory, Result, SafetyStatus
from rampart.reporting.sink import ReportSink, TestRunReport


class TestReportSinkProtocol:
    """ReportSink is runtime-checkable."""

    def test_structural_subtype_satisfies_protocol(self) -> None:
        class FakeSink:
            async def emit_async(self, *, report: TestRunReport) -> None:
                pass

        assert isinstance(FakeSink(), ReportSink)

    def test_non_conforming_class_rejected(self) -> None:
        class BadSink:
            pass

        assert not isinstance(BadSink(), ReportSink)


class TestByHarmCategory:
    """by_harm_category groups correctly and uses 'uncategorized' for None."""

    def test_groups_by_enum_category(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
                Result(
                    safe=False,
                    status=SafetyStatus.UNSAFE,
                    summary="bad",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok2",
                    harm_category=HarmCategory.JAILBREAK,
                ),
            ],
        )

        grouped = report.by_harm_category()
        assert len(grouped["data_exfiltration"]) == 2
        assert len(grouped["jailbreak"]) == 1

    def test_groups_by_plain_string_category(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category="custom_risk",
                ),
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok2",
                    harm_category="custom_risk",
                ),
            ],
        )

        grouped = report.by_harm_category()
        assert len(grouped["custom_risk"]) == 2

    def test_none_category_becomes_uncategorized(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category=None,
                ),
            ],
        )

        grouped = report.by_harm_category()
        assert "uncategorized" in grouped
        assert len(grouped["uncategorized"]) == 1

    def test_mixed_categories(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="a",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="b",
                    harm_category=None,
                ),
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="c",
                    harm_category="team_specific",
                ),
            ],
        )

        grouped = report.by_harm_category()
        assert set(grouped.keys()) == {
            "data_exfiltration",
            "uncategorized",
            "team_specific",
        }


class TestPopulationSummary:
    """Tests population_summary.

    population_summary should compute attack_success_rate and safety_pass_rate
    correctly.
    """

    def test_all_safe(self) -> None:
        report = TestRunReport(
            results=[
                Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
                Result(safe=True, status=SafetyStatus.SAFE, summary="ok2"),
            ],
        )

        stats = report.population_summary()
        assert stats.total_runs == 2
        assert stats.safe_count == 2
        assert stats.unsafe_count == 0
        assert stats.attack_success_rate == 0.0
        assert stats.safety_pass_rate == 1.0

    def test_mixed_results(self) -> None:
        report = TestRunReport(
            results=[
                Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
                Result(safe=False, status=SafetyStatus.UNSAFE, summary="bad"),
                Result(safe=False, status=SafetyStatus.UNDETERMINED, summary="?"),
            ],
        )

        stats = report.population_summary()
        assert stats.total_runs == 3
        assert stats.safe_count == 1
        assert stats.unsafe_count == 1
        assert stats.undetermined_count == 1
        assert stats.attack_success_rate == pytest.approx(1 / 3)
        assert stats.safety_pass_rate == pytest.approx(1 / 3)

    def test_empty_results(self) -> None:
        report = TestRunReport()

        stats = report.population_summary()
        assert stats.total_runs == 0
        assert stats.attack_success_rate == 0.0

    def test_error_excluded_from_attack_success_rate(self) -> None:
        report = TestRunReport(
            results=[
                Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
                Result(safe=False, status=SafetyStatus.UNSAFE, summary="bad"),
                Result(safe=False, status=SafetyStatus.ERROR, summary="infra"),
            ],
        )

        stats = report.population_summary()
        assert stats.total_runs == 3
        assert stats.error_count == 1
        assert stats.attack_success_rate == pytest.approx(1 / 2)
        assert stats.safety_pass_rate == pytest.approx(1 / 2)

    def test_all_errors(self) -> None:
        report = TestRunReport(
            results=[
                Result(safe=False, status=SafetyStatus.ERROR, summary="err1"),
                Result(safe=False, status=SafetyStatus.ERROR, summary="err2"),
            ],
        )

        stats = report.population_summary()
        assert stats.total_runs == 2
        assert stats.error_count == 2
        assert stats.attack_success_rate == 0.0
        assert stats.safety_pass_rate == 0.0

    def test_filter_by_harm_category(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
                Result(
                    safe=False,
                    status=SafetyStatus.UNSAFE,
                    summary="bad",
                    harm_category=HarmCategory.JAILBREAK,
                ),
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok2",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
            ],
        )

        stats = report.population_summary(harm_category=HarmCategory.DATA_EXFILTRATION)
        assert stats.total_runs == 2
        assert stats.safe_count == 2
        assert stats.unsafe_count == 0

    def test_filter_by_plain_string_category(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category="custom",
                ),
                Result(
                    safe=False,
                    status=SafetyStatus.UNSAFE,
                    summary="bad",
                    harm_category="other",
                ),
            ],
        )

        stats = report.population_summary(harm_category="custom")
        assert stats.total_runs == 1
        assert stats.safe_count == 1

    def test_filter_returns_empty_for_missing_category(self) -> None:
        report = TestRunReport(
            results=[
                Result(
                    safe=True,
                    status=SafetyStatus.SAFE,
                    summary="ok",
                    harm_category=HarmCategory.DATA_EXFILTRATION,
                ),
            ],
        )

        stats = report.population_summary(harm_category="nonexistent")
        assert stats.total_runs == 0
        assert stats.attack_success_rate == 0.0
