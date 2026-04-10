# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""ReportSink protocol and TestRunReport.

The reporting layer consumes structured Result objects and emits
them to pluggable sinks. Terminal output is handled separately
by the pytest_terminal_summary hook.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from rampart.core.result import HarmCategory, Result, SafetyStatus


@dataclass(frozen=True, kw_only=True)
class PopulationSummary:
    """Aggregate statistics for a population of test runs."""

    total_runs: int
    safe_count: int
    unsafe_count: int
    undetermined_count: int
    error_count: int
    attack_success_rate: float
    safety_pass_rate: float

    @property
    def has_failures(self) -> bool:
        """True if any run was UNSAFE."""
        return self.unsafe_count > 0

    @property
    def is_clean_run(self) -> bool:
        """True if all runs were SAFE (no unsafe, undetermined, or errors)."""
        return (
            self.unsafe_count == 0
            and self.undetermined_count == 0
            and self.error_count == 0
        )


@dataclass(kw_only=True)
class TestRunReport:
    """Aggregated results from a complete test run.

    Built by the pytest plugin at session end from all collected
    Result objects and standard pytest outcomes.

    Args:
        results (list[Result]): All Result objects recorded during the run.
        total_runs (int): Total number of Result objects (one per execution run).
        passed (int): Number of runs that passed.
        failed (int): Number of runs that failed.
        undetermined (int): Number with undetermined outcomes.
        errors (int): Number with infrastructure errors.
        duration_seconds (float): Total run duration.
        metadata (dict[str, Any]): Run-level metadata (CI job ID, commit hash, etc.).
    """

    __test__ = False  # Prevent pytest from collecting this dataclass as a test.

    results: list[Result] = field(default_factory=list)
    total_runs: int = 0
    passed: int = 0
    failed: int = 0
    undetermined: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def by_harm_category(self) -> dict[str, list[Result]]:
        """Group results by harm category.

        HarmCategory is a StrEnum, so both built-in enum values and
        custom plain strings are native strings at runtime. The grouping
        key is always a plain string.

        Returns:
            dict[str, list[Result]]: Results grouped by harm category string.
        """
        grouped: dict[str, list[Result]] = {}
        for r in self.results:
            key = str(r.harm_category) if r.harm_category else "uncategorized"
            grouped.setdefault(key, []).append(r)
        return grouped

    def population_summary(
        self,
        *,
        harm_category: HarmCategory | str | None = None,
    ) -> PopulationSummary:
        """Compute aggregate statistics over collected Result objects.

        Each Result corresponds to one test execution — one run of one
        test body. For parametrized payload suites, each payload variant
        is one Result. For trial-marked tests, each trial clone is one
        Result; trial groups are aggregated separately by the plugin
        before this method is called.

        This method does not distinguish payloads from trial repetitions.
        Callers that need population-level statistics (distinct payloads,
        not repeated trials) should filter Results to non-trial items
        before calling, or use the plugin-managed trial-group aggregates.

        Args:
            harm_category (HarmCategory | str | None): Filter to a specific
                category. Accepts built-in HarmCategory values or plain
                strings for team-defined categories. None computes over
                all results.

        Returns:
            PopulationSummary: Statistics including total_runs, safe_count,
                unsafe_count, undetermined_count, error_count,
                attack_success_rate, and safety_pass_rate.
        """
        subset = self.results
        if harm_category is not None:
            subset = [r for r in self.results if r.harm_category == harm_category]

        total = len(subset)
        if total == 0:
            return PopulationSummary(
                total_runs=0,
                safe_count=0,
                unsafe_count=0,
                undetermined_count=0,
                error_count=0,
                attack_success_rate=0.0,
                safety_pass_rate=0.0,
            )

        safe = sum(1 for r in subset if r.status == SafetyStatus.SAFE)
        unsafe = sum(1 for r in subset if r.status == SafetyStatus.UNSAFE)
        undetermined = sum(1 for r in subset if r.status == SafetyStatus.UNDETERMINED)
        error_count = sum(1 for r in subset if r.status == SafetyStatus.ERROR)

        # ERROR results are excluded from attack success rate. A SharePoint
        # 503 is not a safety finding. Including errors in the denominator
        # dilutes the rate; including them in the numerator inflates it.
        diagnostic_total = total - error_count

        return PopulationSummary(
            total_runs=total,
            safe_count=safe,
            unsafe_count=unsafe,
            undetermined_count=undetermined,
            error_count=error_count,
            attack_success_rate=(
                unsafe / diagnostic_total if diagnostic_total > 0 else 0.0
            ),
            safety_pass_rate=(safe / diagnostic_total if diagnostic_total > 0 else 0.0),
        )


@runtime_checkable
class ReportSink(Protocol):
    """Receives test run reports and persists them to an external destination.

    Implementations handle serialization and delivery to their target
    (database, metrics pipeline, file store, etc.). Terminal output is
    not a ReportSink concern — it is owned by the pytest_terminal_summary
    hook in the plugin.
    """

    async def emit_async(self, *, report: TestRunReport) -> None:
        """Emit a complete test run report.

        Args:
            report (TestRunReport): The aggregated test run results.
        """
        ...
