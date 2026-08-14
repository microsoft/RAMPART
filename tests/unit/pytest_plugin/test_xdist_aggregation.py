# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Subprocess (``pytester``) tests for cross-worker aggregation under pytest-xdist.

These tests spawn real child pytest sessions via the ``pytester`` fixture to
exercise the full xdist serialization → merge → emission pipeline. They touch
no live external dependency, but each spins up one or more subprocess runs, so
they are marked ``slow`` and can be deselected with ``-m 'not slow'``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from rampart.pytest_plugin._xdist import MIN_RESULT_SIZE_LIMIT_BYTES

if TYPE_CHECKING:
    from _pytest.pytester import Pytester, RunResult


pytest_plugins = ["pytester"]

pytestmark = pytest.mark.slow


_CONFTEST = """\
from pathlib import Path

import pytest

from rampart.reporting import JsonFileReportSink


_OUT_DIR = Path("rampart_reports").absolute()


@pytest.fixture(scope="session")
def rampart_sinks():
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    Path("rampart_report_dir.txt").write_text(str(_OUT_DIR))
    return [JsonFileReportSink(output_dir=_OUT_DIR)]
"""


# Each ``pytester`` child session is configuration-isolated from the repository's
# ``pyproject.toml``, so pytest-asyncio reads an empty
# ``asyncio_default_fixture_loop_scope`` via ``config.getini(...)`` and emits a
# ``PytestDeprecationWarning`` once per subprocess run. Writing an ini file into
# the child project root sets the option through the same channel pytest-asyncio
# reads, mirroring the parent project's asyncio configuration.
_INI = """\
[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = session
"""


@pytest.fixture
def configured_pytester(pytester: Pytester) -> Pytester:
    """Write the child-session pytest conftest and ini files for subprocess runs."""
    pytester.makeconftest(_CONFTEST)
    pytester.makeini(_INI)
    return pytester


def _load_reports(configured_pytester: Pytester) -> list[dict[str, Any]]:
    marker = configured_pytester.path / "rampart_report_dir.txt"
    if not marker.exists():
        default_dir = configured_pytester.path / "rampart_reports"
        if default_dir.exists():
            return [
                json.loads(p.read_text())
                for p in sorted(default_dir.glob("run_report_*.json"))
            ]
        return []
    out_dir = Path(marker.read_text().strip())
    if not out_dir.exists():
        return []
    return [
        json.loads(p.read_text()) for p in sorted(out_dir.glob("run_report_*.json"))
    ]


def _report_results(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        result
        for results in report.get("by_harm_category", {}).values()
        for result in results
    ]


def _setup_simple_tests(configured_pytester: Pytester) -> None:
    configured_pytester.makepyfile(
        test_a="""
        import pytest
        from rampart import record_result
        from rampart.core.result import Result, SafetyStatus
        from rampart.core.types import ObservabilityLevel

        @pytest.mark.harm("test")
        def test_a_one():
            record_result(Result(
                status=SafetyStatus.SAFE, summary="a1",
                observability_level=ObservabilityLevel.RESPONSE_ONLY,
            ))

        @pytest.mark.harm("test")
        def test_a_two():
            record_result(Result(
                status=SafetyStatus.UNSAFE, summary="a2",
                observability_level=ObservabilityLevel.RESPONSE_ONLY,
            ))
        """,
        test_b="""
        import pytest
        from rampart import record_result
        from rampart.core.result import Result, SafetyStatus
        from rampart.core.types import ObservabilityLevel

        @pytest.mark.harm("test")
        def test_b_one():
            record_result(Result(
                status=SafetyStatus.SAFE, summary="b1",
                observability_level=ObservabilityLevel.RESPONSE_ONLY,
            ))

        @pytest.mark.harm("test")
        def test_b_two():
            record_result(Result(
                status=SafetyStatus.SAFE, summary="b2",
                observability_level=ObservabilityLevel.RESPONSE_ONLY,
            ))
        """,
    )


class TestSingleProcessBaseline:
    def test_baseline_emits_one_report(self, configured_pytester: Pytester) -> None:
        _setup_simple_tests(configured_pytester)
        result = configured_pytester.runpytest("-p", "no:cacheprovider")
        result.assert_outcomes(passed=4)
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        assert reports[0]["total_runs"] == 4


class TestXdistConsolidation:
    def test_xdist_emits_single_consolidated_report(
        self,
        configured_pytester: Pytester,
    ) -> None:
        """A distributed run merges into one report with full population stats.

        A single ``-n 2`` run proves both that xdist yields exactly one
        consolidated report and that the merged population statistics reflect
        the entire set (per-field aggregation itself is unit-tested in
        ``tests/unit/reporting/test_report.py::TestPopulationSummary``).
        """
        _setup_simple_tests(configured_pytester)
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
        )
        result.assert_outcomes(passed=4)
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1, (
            f"Expected exactly one report under xdist, got {len(reports)}: "
            f"{[r.get('total_runs') for r in reports]}"
        )
        report = reports[0]
        assert report["total_runs"] == 4
        assert report["passed"] == 3
        assert report["failed"] == 1
        assert report["population_summary"]["total_runs"] == 4
        assert report["population_summary"]["safe_count"] == 3
        assert report["population_summary"]["unsafe_count"] == 1


class TestStreamedResultTransport:
    def test_async_test_body_streams_result(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_async_stream="""
            import asyncio
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.mark.asyncio
            @pytest.mark.harm("async")
            async def test_async_stream_async():
                await asyncio.gather(asyncio.sleep(0), asyncio.sleep(0))
                record_result(Result(status=SafetyStatus.SAFE, summary="async"))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
        )
        result.assert_outcomes(passed=1)
        reports = _load_reports(configured_pytester)
        assert reports[0]["total_runs"] == 1
        assert _report_results(reports[0])[0]["summary"] == "async"

    def test_setup_failure_streams_result(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_setup_failure="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.fixture
            def failing_setup():
                record_result(Result(
                    status=SafetyStatus.ERROR,
                    summary="setup-failed",
                ))
                raise RuntimeError("setup failed")

            @pytest.mark.harm("setup")
            def test_setup_failure(failing_setup):
                pass
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
        )
        result.assert_outcomes(errors=1)
        reports = _load_reports(configured_pytester)
        assert [item["summary"] for item in _report_results(reports[0])] == [
            "setup-failed",
        ]

    def test_setup_skip_streams_result(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_setup_skip="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.fixture
            def skipped_setup():
                record_result(Result(
                    status=SafetyStatus.UNDETERMINED,
                    summary="setup-skipped",
                ))
                pytest.skip("setup skipped")

            @pytest.mark.harm("setup")
            def test_setup_skip(skipped_setup):
                pass
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
        )
        result.assert_outcomes(skipped=1)
        reports = _load_reports(configured_pytester)
        assert [item["summary"] for item in _report_results(reports[0])] == [
            "setup-skipped",
        ]

    def test_successful_setup_and_call_stream_once(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_setup_success="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.fixture
            def recorded_setup():
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="setup",
                ))

            @pytest.mark.harm("setup")
            def test_setup_success(recorded_setup):
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="call",
                ))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
        )
        result.assert_outcomes(passed=1)
        reports = _load_reports(configured_pytester)
        assert [item["summary"] for item in _report_results(reports[0])] == [
            "setup",
            "call",
        ]

    def test_teardown_only_result_is_intentionally_not_streamed(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_teardown_boundary="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.fixture
            def record_during_teardown():
                yield
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="teardown-only",
                ))

            @pytest.mark.harm("teardown")
            def test_teardown_boundary(record_during_teardown):
                pass
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
        )
        result.assert_outcomes(passed=1)
        reports = _load_reports(configured_pytester)
        assert reports[0]["total_runs"] == 0
        assert reports[0]["metadata"].get("incomplete") is not True

    def test_dist_each_preserves_source_worker_separation(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_each="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.mark.harm("each")
            def test_each():
                record_result(Result(status=SafetyStatus.SAFE, summary="each"))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
            "--dist",
            "each",
        )
        result.assert_outcomes(passed=2)
        reports = _load_reports(configured_pytester)
        streamed = _report_results(reports[0])
        assert reports[0]["total_runs"] == 2
        assert [item["metadata"]["_rampart_source_worker"] for item in streamed] == [
            "gw0",
            "gw1",
        ]

    def test_worker_crash_keeps_previously_streamed_result(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_crash="""
            import os
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.mark.harm("crash")
            def test_0_stream_before_crash():
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="survived",
                ))

            def test_1_crash_worker():
                os._exit(3)
            """,
        )
        configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
            "--max-worker-restart=0",
        )
        reports = _load_reports(configured_pytester)
        assert reports[0]["total_runs"] == 1
        assert _report_results(reports[0])[0]["summary"] == "survived"
        assert reports[0]["metadata"]["incomplete"] is True

    def test_oversized_result_does_not_drop_normal_result(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_cap="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.mark.harm("cap")
            def test_0_normal():
                record_result(Result(status=SafetyStatus.SAFE, summary="normal"))

            @pytest.mark.harm("cap")
            def test_1_oversized():
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="x" * 5000,
                ))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
            "--rampart-xdist-max-bytes=1024",
        )
        result.assert_outcomes(passed=2)
        reports = _load_reports(configured_pytester)
        streamed = _report_results(reports[0])
        assert reports[0]["total_runs"] == 2
        assert any(item["summary"] == "normal" for item in streamed)
        assert any(
            item["metadata"].get("_rampart_transport_truncated") is True
            for item in streamed
        )
        assert reports[0]["metadata"]["incomplete"] is True


class TestXdistTrialAggregation:
    def test_trial_aggregation_across_workers_loadgroup(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_trial="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus
            from rampart.core.types import ObservabilityLevel

            @pytest.mark.harm("test")
            @pytest.mark.trial(n=4, threshold=0.5)
            def test_trial_split():
                record_result(Result(
                    status=SafetyStatus.SAFE, summary="t",
                    observability_level=ObservabilityLevel.RESPONSE_ONLY,
                ))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
            "--dist",
            "loadgroup",
        )
        result.assert_outcomes(passed=4)
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        assert reports[0]["total_runs"] == 4

    def test_trial_aggregation_across_workers_load(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_trial="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus
            from rampart.core.types import ObservabilityLevel

            @pytest.mark.harm("test")
            @pytest.mark.trial(n=4, threshold=0.5)
            def test_trial_split():
                record_result(Result(
                    status=SafetyStatus.SAFE, summary="t",
                    observability_level=ObservabilityLevel.RESPONSE_ONLY,
                ))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
            "--dist",
            "load",
        )
        result.assert_outcomes(passed=4)
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        assert reports[0]["total_runs"] == 4

    def test_trial_group_fails_when_any_unsafe_under_load(
        self,
        configured_pytester: Pytester,
    ) -> None:
        """Same as above but with --dist=load so clones may split workers.

        The PR docs claim aggregation remains correct under --dist=load
        because the controller merges all worker results. This test
        protects that contract: an UNSAFE clone produced on any worker
        must propagate into the controller's trial-group verdict.
        """
        configured_pytester.makepyfile(
            test_trial_mixed_load="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus
            from rampart.core.types import ObservabilityLevel

            @pytest.mark.harm("test")
            @pytest.mark.trial(n=4, threshold=0.5)
            def test_trial_mixed_load(request):
                unsafe = request.node.name.endswith("[trial-3]")
                record_result(Result(
                    status=SafetyStatus.UNSAFE if unsafe else SafetyStatus.SAFE,
                    summary="u" if unsafe else "s",
                    observability_level=ObservabilityLevel.RESPONSE_ONLY,
                ))
            """,
        )
        result = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "2",
            "--dist",
            "load",
        )
        result.assert_outcomes(passed=4)
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        report = reports[0]
        assert report["total_runs"] == 4
        assert report["failed"] == 1
        summary = "\n".join(result.outlines)
        assert (
            "FAIL  test_trial_mixed_load [3/4 safe, 75% pass rate, threshold: 50%]"
            in summary
        )


class TestXdistMetadata:
    def test_report_includes_xdist_metadata(
        self,
        configured_pytester: Pytester,
    ) -> None:
        _setup_simple_tests(configured_pytester)
        configured_pytester.runpytest("-p", "no:cacheprovider", "-n", "2")
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        metadata = reports[0].get("metadata", {})
        assert metadata.get("xdist_active") is True
        assert metadata.get("worker_count") == 2
        assert "dist_mode" in metadata
        assert "population_summary" in reports[0]

    def test_size_cap_marks_run_incomplete(self, configured_pytester: Pytester) -> None:
        """An oversized Result surfaces incompleteness in report metadata.

        Triggers the truncation path so the controller must record
        ``incomplete=True`` plus a reason in the merged report.
        """
        configured_pytester.makepyfile(
            test_size_cap="""
            import pytest
            from rampart import record_result
            from rampart.core.result import Result, SafetyStatus

            @pytest.mark.harm("cap")
            def test_oversized():
                record_result(Result(
                    status=SafetyStatus.SAFE,
                    summary="x" * 10_000,
                ))
            """,
        )
        configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "-n",
            "1",
            f"--rampart-xdist-max-bytes={MIN_RESULT_SIZE_LIMIT_BYTES}",
        )
        reports = _load_reports(configured_pytester)
        assert len(reports) == 1
        metadata = reports[0].get("metadata", {})
        assert metadata.get("incomplete") is True
        reasons = metadata.get("incomplete_reasons", [])
        assert any("truncated" in r for r in reasons)


class TestCollectOnly:
    def test_collect_only_does_not_emit_reports(
        self,
        configured_pytester: Pytester,
    ) -> None:
        _setup_simple_tests(configured_pytester)
        configured_pytester.runpytest("-p", "no:cacheprovider", "--collect-only")
        # No sinks emit when no tests run
        marker = configured_pytester.path / "rampart_report_dir.txt"
        if marker.exists():
            out_dir = Path(marker.read_text().strip())
            if out_dir.exists():
                reports = list(out_dir.glob("run_report_*.json"))
                assert reports == []


class TestCloneIdDeterminism:
    def test_trial_clone_ids_deterministic_across_processes(
        self,
        configured_pytester: Pytester,
    ) -> None:
        configured_pytester.makepyfile(
            test_det="""
            import pytest

            @pytest.mark.trial(n=3)
            def test_x():
                pass
            """,
        )
        result_serial: RunResult = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
        )
        result_parallel: RunResult = configured_pytester.runpytest(
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            "-n",
            "2",
        )

        def _trial_ids(lines: list[str]) -> list[str]:
            return sorted(line.strip() for line in lines if "trial-" in line)

        serial_ids = _trial_ids(result_serial.outlines)
        parallel_ids = _trial_ids(result_parallel.outlines)
        # Under xdist --collect-only, both should produce the same
        # deterministic clone IDs so that workers can match them.
        if serial_ids and parallel_ids:
            assert serial_ids == parallel_ids


class TestSinkFixtureDeprecation:
    """End-to-end deprecation-warning contract for the ``rampart_sinks`` fixture.

    The fixture warns wherever it is resolved: single-process and on the xdist
    controller. The list form's silence is covered by the fast unit tests in
    ``test_xdist.py::TestSinkDeprecationWarning``.
    """

    _DEPRECATION_LINE = "*rampart_sinks fixture is deprecated*"

    def test_single_process_fixture_warns(
        self,
        configured_pytester: Pytester,
    ) -> None:
        _setup_simple_tests(configured_pytester)
        result = configured_pytester.runpytest("-p", "no:cacheprovider")
        result.assert_outcomes(passed=4)
        result.stdout.fnmatch_lines([self._DEPRECATION_LINE])

    def test_controller_fixture_warns_under_xdist(
        self,
        configured_pytester: Pytester,
    ) -> None:
        _setup_simple_tests(configured_pytester)
        result = configured_pytester.runpytest("-p", "no:cacheprovider", "-n", "2")
        result.assert_outcomes(passed=4)
        result.stdout.fnmatch_lines([self._DEPRECATION_LINE])
