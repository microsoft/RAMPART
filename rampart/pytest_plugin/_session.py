# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Session-scoped state for the RAMPART pytest plugin.

Accumulates Result objects, computes trial group aggregates, and
builds the final TestRunReport.

Note: The architecture places RampartSession in plugin.py. This
implementation extracts it to a dedicated module for file size
management. This is a documented deviation from the architecture.
"""

from __future__ import annotations

import copy
import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rampart.core.result import Result, SafetyStatus
from rampart.reporting.sink import ReportSink, TestRunReport

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest

    from rampart.pytest_plugin._collection import ResultCollector

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TrialGroupResult:
    """Aggregate statistics for a trial group."""

    total: int
    safe: int
    unsafe: int
    errors: int
    no_result: int
    threshold: float
    pass_rate: float
    passed: bool

    @property
    def verdict(self) -> str:
        """Human-readable verdict: PASSED or FAILED."""
        return "PASSED" if self.passed else "FAILED"

    @property
    def terminal_label(self) -> str:
        """Short label for terminal output: PASS or FAIL."""
        return "PASS" if self.passed else "FAIL"

    @property
    def detail(self) -> str:
        """Summary detail string for terminal output (e.g. '8/10 safe, 2 no-result')."""
        parts = [f"{self.safe}/{self.total} safe"]
        if self.no_result > 0:
            parts.append(f"{self.no_result} no-result")
        return ", ".join(parts)

    @property
    def has_unsafe(self) -> bool:
        """True if any trial produced an UNSAFE result."""
        return self.unsafe > 0


class RampartSession:
    """Session-scoped state for the RAMPART plugin.

    Accumulates Result objects from all tests, stores trial group
    aggregates, tracks session duration, and builds the final
    TestRunReport. Holds configured sinks for report emission.

    Args:
        sinks (list[ReportSink]): Report sinks to emit to at session
            end. Defaults to an empty list (terminal-only output).
    """

    def __init__(self, *, sinks: list[ReportSink] | None = None) -> None:
        self._results: list[Result] = []
        self._results_by_nodeid: dict[str, list[Result]] = {}
        self._trial_groups: dict[str, TrialGroupResult] = {}
        self._sinks: list[ReportSink] = sinks or []
        self._duration_seconds: float = 0.0
        self._cached_report: TestRunReport | None = None

    @property
    def sinks(self) -> list[ReportSink]:
        """Configured report sinks."""
        return list(self._sinks)

    def add_sinks(self, *, sinks: list[ReportSink]) -> None:
        """Register additional sinks for report emission.

        Called by the fixture-based bootstrap to add team-provided
        sinks.

        Args:
            sinks (list[ReportSink]): Sinks to append.

        Raises:
            TypeError: If any item does not satisfy ReportSink.
        """
        for sink in sinks:
            if not isinstance(sink, ReportSink):  # pyright: ignore[reportUnnecessaryIsInstance]
                msg = (
                    f"Expected ReportSink, got {type(sink).__name__}. "
                    "Sinks must implement: "
                    "async def emit_async(*, report: TestRunReport) -> None"
                )
                raise TypeError(
                    msg,
                )
            self._sinks.append(sink)

    def set_duration(self, *, duration_seconds: float) -> None:
        """Set the total session duration.

        Called by the plugin at session finish with the elapsed time
        since pytest_configure.

        Args:
            duration_seconds (float): Total wall-clock seconds.
        """
        self._duration_seconds = duration_seconds

    def absorb(self, *, node: pytest.Item, collector: ResultCollector) -> None:
        """Absorb results from a completed test's collector.

        Tags each result with the short test name (extracted from
        the node ID) and the harm category from ``@pytest.mark.harm``
        so the terminal summary can group and display results.

        Results are shallow-copied before tagging to avoid mutating
        objects the test body may still reference.

        Args:
            node (pytest.Item): The test item that just completed.
            collector (ResultCollector): The test's result collector.
        """
        test_name = node.nodeid.split("::")[-1] if "::" in node.nodeid else node.nodeid
        harm_marker = node.get_closest_marker("harm")
        harm_category = (
            harm_marker.args[0] if harm_marker and harm_marker.args else None
        )

        collected = collector.results
        tagged: list[Result] = []
        for original_result in collected:
            # Shallow copy is sufficient because we reconstruct all
            # mutable fields we modify (currently metadata and harm_category).
            result = copy.copy(original_result)
            result.metadata = {**result.metadata, "test_name": test_name}
            if harm_category is not None and result.harm_category is None:
                result.harm_category = harm_category
            tagged.append(result)
        self._results.extend(tagged)
        self._results_by_nodeid[node.nodeid] = tagged
        self._cached_report = None

    def record_trial_group(
        self,
        *,
        base_nodeid: str,
        trial_items: Sequence[pytest.Item],
        threshold: float,
    ) -> None:
        """Record aggregate statistics for a trial group.

        Semantics:
        - Any UNSAFE result across all trials -> group FAILS
        - threshold is the minimum pass rate (SAFE / total).
          e.g. 0.8 means at least 80% of runs must be SAFE.
        - ERROR results count against the pass rate (they're not SAFE).
        - Items with zero results (skipped or crashed before producing
          a Result) are tracked as ``no_result`` and count against
          the pass rate.

        Args:
            base_nodeid (str): The original test's node ID.
            trial_items (Sequence[pytest.Item]): All trial clone items.
            threshold (float): Minimum pass rate required.
        """
        if not trial_items:
            return

        total = len(trial_items)
        unsafe_count = 0
        error_count = 0
        safe_count = 0
        no_result_count = 0

        for item in trial_items:
            node_results = self._results_by_nodeid.get(item.nodeid, [])
            if not node_results:
                no_result_count += 1
                continue
            has_unsafe = any(r.status == SafetyStatus.UNSAFE for r in node_results)
            has_error = any(r.status == SafetyStatus.ERROR for r in node_results)
            has_safe = any(r.status == SafetyStatus.SAFE for r in node_results)
            if has_unsafe:
                unsafe_count += 1
            elif has_error:
                error_count += 1
            elif has_safe:
                safe_count += 1

        pass_rate = safe_count / total if total > 0 else 0.0
        passed = unsafe_count == 0 and pass_rate >= threshold

        self._trial_groups[base_nodeid] = TrialGroupResult(
            total=total,
            safe=safe_count,
            unsafe=unsafe_count,
            errors=error_count,
            no_result=no_result_count,
            threshold=threshold,
            pass_rate=pass_rate,
            passed=passed,
        )

    @property
    def has_results(self) -> bool:
        """True if any results have been collected."""
        return bool(self._results)

    @property
    def trial_groups(self) -> dict[str, TrialGroupResult]:
        """Trial group aggregates, keyed by base node ID."""
        return dict(self._trial_groups)

    def build_report(self) -> TestRunReport:
        """Build a TestRunReport from all collected results.

        The report is cached and reused on subsequent calls. The
        cache is invalidated when new results are absorbed.

        Returns:
            TestRunReport: Aggregated test run results.
        """
        if self._cached_report is not None:
            return self._cached_report
        counts = Counter(r.status for r in self._results)
        self._cached_report = TestRunReport(
            results=list(self._results),
            total_runs=len(self._results),
            passed=counts[SafetyStatus.SAFE],
            failed=counts[SafetyStatus.UNSAFE],
            undetermined=counts[SafetyStatus.UNDETERMINED],
            errors=counts[SafetyStatus.ERROR],
            duration_seconds=self._duration_seconds,
        )
        return self._cached_report
