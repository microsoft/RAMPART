# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Session-scoped state for the RAMPART pytest plugin.

Accumulates Result objects, computes trial group aggregates, and
builds the final TestRunReport.
"""

from __future__ import annotations

import copy
import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rampart.core.result import Result, SafetyStatus
from rampart.reporting.sink import ReportSink, TestRunReport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import pytest

    from rampart.pytest_plugin._collection import ResultCollector

logger = logging.getLogger(__name__)


def _result_sort_key(result: Result) -> tuple[str, int, str]:
    """Return a total-ordering key for a result.

    Orders by full node ID, then the result's index within its test,
    then the originating xdist worker. The worker tie-breaker keeps the
    order total when the same node ID arrives from multiple workers
    (e.g. ``--dist=each``); it is absent — and therefore constant —
    outside xdist, so single-process ordering is unchanged.
    """
    metadata = result.metadata
    nodeid = str(metadata.get("nodeid", metadata.get("test_name", "")))
    raw_index = metadata.get("result_index", 0)
    index = raw_index if isinstance(raw_index, int) else 0
    source_worker = str(metadata.get("source_worker", ""))
    return (nodeid, index, source_worker)


@dataclass(frozen=True, kw_only=True)
class TrialSpec:
    """Trial-clone metadata captured at collection time.

    Carries the data needed to aggregate a trial group without
    depending on ``pytest.Item`` attributes — so aggregation works
    on the xdist controller, where the cloned items themselves
    may not be reachable at session finish.

    Attributes:
        base_nodeid (str): The original test's pytest node ID.
        threshold (float): Minimum pass rate required for the group.
    """

    base_nodeid: str
    threshold: float


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
        self._trial_specs: dict[str, TrialSpec] = {}
        self._sinks: list[ReportSink] = sinks or []
        self._duration_seconds: float = 0.0
        self._cached_report: TestRunReport | None = None
        self._emitted: bool = False
        self._incomplete: bool = False
        self._incomplete_reasons: list[str] = []
        self._report_metadata: dict[str, object] = {}

    @property
    def sinks(self) -> list[ReportSink]:
        """Configured report sinks."""
        return list(self._sinks)

    @property
    def results_by_nodeid(self) -> dict[str, list[Result]]:
        """Read-only view of results grouped by pytest node ID."""
        return {
            nodeid: list(results) for nodeid, results in self._results_by_nodeid.items()
        }

    @property
    def is_emitted(self) -> bool:
        """True once report emission has been attempted (idempotency guard)."""
        return self._emitted

    @property
    def is_incomplete(self) -> bool:
        """True if any worker failed to deliver complete results."""
        return self._incomplete

    @property
    def incomplete_reasons(self) -> list[str]:
        """The recorded reasons the run is incomplete (empty if complete)."""
        return list(self._incomplete_reasons)

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
            if not isinstance(sink, ReportSink):
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

        Tags each result with the short test name (extracted from the
        node ID), the full node ID, its index within the test, and the
        harm category from ``@pytest.mark.harm``. The nodeid and index
        give a total, deterministic ordering for the terminal summary and
        report regardless of xdist worker completion order.

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
        for result_index, original_result in enumerate(collected):
            # Shallow copy is sufficient because we reconstruct all
            # mutable fields we modify (currently metadata and harm_category).
            result = copy.copy(original_result)
            result.metadata = {
                **result.metadata,
                "test_name": test_name,
                "nodeid": node.nodeid,
                "result_index": result_index,
            }
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
        clone_nodeids: Sequence[str],
        threshold: float,
    ) -> None:
        """Record aggregate statistics for a trial group.

        Semantics:
        - Any UNSAFE result across all trials -> group FAILS
        - threshold is the minimum pass rate (SAFE / total).
          e.g. 0.8 means at least 80% of runs must be SAFE.
        - ERROR results count against the pass rate (they're not SAFE).
        - Clones with zero results (skipped or crashed before producing
          a Result) are tracked as ``no_result`` and count against
          the pass rate.

        Args:
            base_nodeid (str): The original test's node ID.
            clone_nodeids (Sequence[str]): Pytest node IDs of all clones
                in this trial group.
            threshold (float): Minimum pass rate required.
        """
        if not clone_nodeids:
            return

        total = len(clone_nodeids)
        unsafe_count = 0
        error_count = 0
        safe_count = 0
        no_result_count = 0

        for nodeid in clone_nodeids:
            node_results = self._results_by_nodeid.get(nodeid, [])
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

    def register_trial_spec(
        self,
        *,
        clone_nodeid: str,
        base_nodeid: str,
        threshold: float,
    ) -> None:
        """Record trial metadata for a cloned item at collection time.

        Called from ``pytest_collection_modifyitems`` whenever a
        ``@pytest.mark.trial`` test is expanded into clones. Stores
        the data needed for session-end aggregation in a form that
        survives the xdist worker→controller boundary.

        Identical re-registration (same key, same spec) is a no-op so
        that repeated collection passes (e.g., in workers and the
        controller) converge safely.

        Args:
            clone_nodeid (str): Node ID of the cloned item.
            base_nodeid (str): Node ID of the original (uncloned) item.
            threshold (float): Pass-rate threshold from the trial marker.
        """
        self._trial_specs[clone_nodeid] = TrialSpec(
            base_nodeid=base_nodeid,
            threshold=threshold,
        )

    def merge_trial_specs(
        self,
        *,
        trial_specs: Mapping[str, TrialSpec],
    ) -> None:
        """Merge trial specs received from an xdist worker payload.

        Idempotent: re-merging identical specs is a no-op. Spec values
        from workers should match the controller's own collection
        because the same plugin code runs in every process; we merge
        defensively so the controller can aggregate correctly even
        when its own collection state is unavailable.

        Args:
            trial_specs (Mapping[str, TrialSpec]): Specs keyed by
                clone node ID.
        """
        for clone_nodeid, spec in trial_specs.items():
            self._trial_specs.setdefault(clone_nodeid, spec)

    @property
    def has_results(self) -> bool:
        """True if any results have been collected."""
        return bool(self._results)

    @property
    def trial_groups(self) -> dict[str, TrialGroupResult]:
        """Trial group aggregates, keyed by base node ID."""
        return dict(self._trial_groups)

    @property
    def trial_specs(self) -> dict[str, TrialSpec]:
        """Read-only view of registered trial specs, keyed by clone node ID."""
        return dict(self._trial_specs)

    def merge_worker_results(
        self,
        *,
        results_by_nodeid: dict[str, list[Result]],
    ) -> None:
        """Merge an xdist worker's results into this session.

        Extends both the flat ``_results`` list and the
        ``_results_by_nodeid`` mapping. Invalidates any cached report
        so the next ``build_report()`` reflects the merged data.

        Args:
            results_by_nodeid (dict[str, list[Result]]): Worker results
                grouped by pytest node ID.
        """
        for nodeid, results in results_by_nodeid.items():
            self._results.extend(results)
            self._results_by_nodeid.setdefault(nodeid, []).extend(results)
        self._cached_report = None

    def mark_emitted(self) -> None:
        """Mark the session as having attempted report emission."""
        self._emitted = True

    def mark_incomplete(self, *, reason: str) -> None:
        """Record that a worker failed to deliver complete results.

        Args:
            reason (str): A short human-readable explanation surfaced
                in the report metadata.
        """
        self._incomplete = True
        self._incomplete_reasons.append(reason)
        self._cached_report = None

    def set_report_metadata(self, *, metadata: dict[str, object]) -> None:
        """Attach run-level metadata that will appear on ``TestRunReport``.

        Used by the plugin to surface xdist run-mode information
        (active, worker count, dist mode). Subsequent calls merge into
        existing metadata.

        Args:
            metadata (dict[str, object]): Key/value pairs to attach.
        """
        self._report_metadata.update(metadata)
        self._cached_report = None

    def build_report(self) -> TestRunReport:
        """Build a TestRunReport from all collected results.

        The report is cached and reused on subsequent calls. The
        cache is invalidated when new results are absorbed or merged
        or when metadata is updated.

        Results are sorted by ``(nodeid, result_index, source_worker)``
        for a total, deterministic ordering across xdist worker
        completion orders. ``nodeid`` falls back to ``test_name`` and
        ``source_worker`` is absent (constant) outside xdist, so
        single-process ordering is unaffected.

        Returns:
            TestRunReport: Aggregated test run results.
        """
        if self._cached_report is not None:
            return self._cached_report
        sorted_results = sorted(self._results, key=_result_sort_key)
        counts = Counter(r.status for r in sorted_results)
        metadata: dict[str, Any] = dict(self._report_metadata)
        if self._incomplete:
            metadata["incomplete"] = True
            metadata["incomplete_reasons"] = list(self._incomplete_reasons)
        self._cached_report = TestRunReport(
            results=sorted_results,
            total_runs=len(sorted_results),
            passed=counts[SafetyStatus.SAFE],
            failed=counts[SafetyStatus.UNSAFE],
            undetermined=counts[SafetyStatus.UNDETERMINED],
            errors=counts[SafetyStatus.ERROR],
            duration_seconds=self._duration_seconds,
            metadata=metadata,
        )
        return self._cached_report
