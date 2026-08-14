# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the RAMPART pytest plugin hooks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from rampart.core.result import Result, SafetyStatus
from rampart.core.types import ObservabilityLevel
from rampart.pytest_plugin._collection import (
    ResultCollectionHandler,
    ResultCollector,
    _active_collector,
    activate_collector,
    deactivate_collector,
)
from rampart.pytest_plugin._session import RampartSession
from rampart.pytest_plugin._xdist import REPORT_RESULTS_ATTR, serialize_report_data
from rampart.pytest_plugin.plugin import (
    _call_results_key,
    _emit_sinks,
    _enforce_incomplete_exit_status,
    _evaluate_gates,
    _has_sink_hook_impl,
    _rampart_key,
    _received_result_counts_key,
    _resolve_hook_sinks,
    _resolve_trial_n,
    _sanitize_for_terminal,
    _streamed_result_count_key,
    _write_result_line,
    _write_trial_group_lines,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_logreport,
    pytest_runtest_makereport,
    pytest_sessionfinish,
    pytest_terminal_summary,
    pytest_unconfigure,
)
from rampart.reporting.sink import ReportSink

if TYPE_CHECKING:
    from _pytest.terminal import TerminalReporter


class _StashStub:
    """Minimal pytest.Stash test double backed by a dict."""

    def __init__(self) -> None:
        self._data: dict[Any, Any] = {}

    def __setitem__(self, key: Any, value: Any) -> None:
        self._data[key] = value

    def __getitem__(self, key: Any) -> Any:
        return self._data[key]

    def __contains__(self, key: Any) -> bool:
        return key in self._data

    def __delitem__(self, key: Any) -> None:
        del self._data[key]

    def get(self, key: Any, default: Any = None) -> Any:
        """Return value for key, or default."""
        return self._data.get(key, default)

    def pop(self, key: Any, *args: Any) -> Any:
        """Remove and return value for key."""
        return self._data.pop(key, *args)


class _ConfigStub:
    """Minimal pytest.Config test double with stash support."""

    def __init__(self) -> None:
        self._ini_lines: list[tuple[str, str]] = []
        self.stash = _StashStub()

    def addinivalue_line(self, name: str, line: str) -> None:
        """Record marker registrations."""
        self._ini_lines.append((name, line))


class TestDefaultHandlerFactory:
    """Handler factory is set during configure and cleared on unconfigure."""

    def test_configure_sets_factory(self) -> None:
        config: Any = _ConfigStub()
        pytest_configure(config)
        try:
            from rampart.core.execution import _default_handler_factory

            handlers = _default_handler_factory()
            assert len(handlers) == 1
            assert isinstance(handlers[0], ResultCollectionHandler)
        finally:
            pytest_unconfigure(config)

    def test_unconfigure_clears_factory(self) -> None:
        config: Any = _ConfigStub()
        pytest_configure(config)
        pytest_unconfigure(config)

        from rampart.core.execution import _default_handler_factory

        assert _default_handler_factory() == []

    def test_configure_creates_session_in_stash(self) -> None:
        config: Any = _ConfigStub()
        pytest_configure(config)
        try:
            from rampart.pytest_plugin.plugin import _rampart_key

            assert isinstance(config.stash.get(_rampart_key), RampartSession)
        finally:
            pytest_unconfigure(config)

    def test_unconfigure_removes_session_from_stash(self) -> None:
        config: Any = _ConfigStub()
        pytest_configure(config)
        pytest_unconfigure(config)

        from rampart.pytest_plugin.plugin import _rampart_key

        assert config.stash.get(_rampart_key) is None


class TestRampartSession:
    """RampartSession accumulates results and builds reports."""

    def test_absorb_accumulates_results(self) -> None:
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test_file.py::test_absorb"

        session.absorb(node=node, collector=collector)

        assert session.has_results
        report = session.build_report()
        assert report.total_runs == 1
        assert report.passed == 1

    def test_absorb_uses_parameterized_item_display_name(self) -> None:
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test_file.py::test_absorb[raw-id]"
        node.name = "test_absorb[display-id]"

        session.absorb(node=node, collector=collector)

        result = session.build_report().results[0]
        assert result.metadata["_pytest_test_name"] == "test_absorb[display-id]"

    def test_has_results_false_when_empty(self) -> None:
        session = RampartSession()
        assert not session.has_results

    def test_build_report_counts(self) -> None:
        session = RampartSession()

        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="s"),
        )
        collector.record(
            result=Result(status=SafetyStatus.UNSAFE, summary="u"),
        )
        collector.record(
            result=Result(status=SafetyStatus.ERROR, summary="e"),
        )
        node = MagicMock()
        node.nodeid = "test_file.py::test_counts"

        session.absorb(node=node, collector=collector)
        report = session.build_report()

        assert report.total_runs == 3
        assert report.passed == 1
        assert report.failed == 1
        assert report.errors == 1

    def test_record_trial_group(self) -> None:
        session = RampartSession()

        items: list[Any] = [MagicMock() for _ in range(5)]
        statuses = [
            SafetyStatus.UNSAFE,
            SafetyStatus.SAFE,
            SafetyStatus.UNSAFE,
            SafetyStatus.ERROR,
            SafetyStatus.SAFE,
        ]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_example[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    status=statuses[idx],
                    summary=f"trial-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_example",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.3,
        )

        groups = session.trial_groups
        assert "test_example" in groups
        group = groups["test_example"]
        assert group.total == 5
        assert group.safe == 2
        assert group.unsafe == 2
        assert group.errors == 1
        assert group.threshold == pytest.approx(0.3)
        assert group.pass_rate == pytest.approx(0.4)
        assert not group.passed  # UNSAFE present → always fails

    def test_record_trial_group_all_errors(self) -> None:
        session = RampartSession()

        items: list[Any] = [MagicMock() for _ in range(3)]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_err[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    status=SafetyStatus.ERROR,
                    summary=f"err-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_err",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.0,
        )

        group = session.trial_groups["test_err"]
        assert group.errors == 3
        assert group.unsafe == 0
        assert group.pass_rate == pytest.approx(0.0)
        assert group.passed  # threshold=0.0 means any pass rate is acceptable

    def test_record_trial_group_fails_below_threshold(self) -> None:
        session = RampartSession()

        items: list[Any] = [MagicMock() for _ in range(4)]
        statuses = [
            SafetyStatus.SAFE,
            SafetyStatus.SAFE,
            SafetyStatus.UNDETERMINED,
            SafetyStatus.UNDETERMINED,
        ]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_thresh[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    status=statuses[idx],
                    summary=f"trial-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_thresh",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.75,
        )

        group = session.trial_groups["test_thresh"]
        assert group.unsafe == 0
        assert group.safe == 2
        assert group.pass_rate == pytest.approx(0.5)
        assert not group.passed  # no UNSAFE, but pass rate below threshold

    def test_record_trial_group_passes_when_all_safe(self) -> None:
        session = RampartSession()

        items: list[Any] = [MagicMock() for _ in range(3)]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_all_safe[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    status=SafetyStatus.SAFE,
                    summary=f"trial-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_all_safe",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.5,
        )

        group = session.trial_groups["test_all_safe"]
        assert group.unsafe == 0
        assert group.safe == 3
        assert group.pass_rate == pytest.approx(1.0)
        assert group.passed  # all SAFE and at/above threshold

    def test_record_trial_group_empty_items_noop(self) -> None:
        session = RampartSession()
        session.record_trial_group(
            base_nodeid="test_empty",
            clone_nodeids=[],
            threshold=0.0,
        )
        assert "test_empty" not in session.trial_groups


def _make_trial_item(
    *,
    n: int = 3,
    threshold: float = 0.0,
    nodeid: str = "test_file.py::test_example",
    name: str = "test_example",
) -> MagicMock:
    """Build a mock pytest.Item with a trial marker."""
    marker = pytest.mark.trial(n=n, threshold=threshold).mark
    item = MagicMock()
    item.get_closest_marker.return_value = marker
    item.nodeid = nodeid
    item.name = name
    item.originalname = name
    item.parent = MagicMock()
    item.function = lambda: None
    return item


def _make_plain_item(
    *,
    nodeid: str = "test_file.py::test_plain",
    name: str = "test_plain",
) -> MagicMock:
    """Build a mock pytest.Item without a trial marker."""
    item = MagicMock()
    item.get_closest_marker.return_value = None
    item.nodeid = nodeid
    item.originalname = name
    return item


class TestTrialCloning:
    """Trial cloning produces n items with distinct [trial-N] node ids."""

    def test_trial_cloning_produces_n_items(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        item = _make_trial_item(n=3)
        clone_instances = [MagicMock() for _ in range(3)]
        for clone in clone_instances:
            clone.iter_markers.return_value = []
        mock_from_parent = MagicMock(side_effect=clone_instances)
        # type(item).from_parent is used in plugin, so patch it on the mock's type
        type(item).from_parent = mock_from_parent

        items: list[Any] = [item]
        config = MagicMock()
        pytest_collection_modifyitems(
            config=cast("pytest.Config", config),
            items=items,
        )

        assert len(items) == 3
        calls = mock_from_parent.call_args_list
        for i, call in enumerate(calls):
            assert call.kwargs["name"] == f"test_example[trial-{i}]"

    def test_trial_n_zero_raises_usage_error(self) -> None:
        item = _make_trial_item(n=0)
        items: list[Any] = [item]
        config = MagicMock()

        with pytest.raises(pytest.UsageError, match="must be >= 1"):
            pytest_collection_modifyitems(
                config=cast("pytest.Config", config),
                items=items,
            )

    def test_non_trial_items_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        plain = _make_plain_item()
        trial = _make_trial_item(n=2)
        clone_instances = [MagicMock() for _ in range(2)]
        for clone in clone_instances:
            clone.iter_markers.return_value = []
        type(trial).from_parent = MagicMock(side_effect=clone_instances)

        items: list[Any] = [plain, trial]
        config = MagicMock()
        pytest_collection_modifyitems(
            config=cast("pytest.Config", config),
            items=items,
        )

        assert items[0] is plain
        assert len(items) == 3

    def test_trial_item_with_no_parent_raises(self) -> None:
        item = _make_trial_item(n=2)
        item.parent = None

        items: list[Any] = [item]
        config = MagicMock()

        with pytest.raises(pytest.UsageError, match="no parent"):
            pytest_collection_modifyitems(
                config=cast("pytest.Config", config),
                items=items,
            )


class TestResolveTrialN:
    """_resolve_trial_n extracts n from positional and keyword args."""

    def test_keyword_n(self) -> None:
        marker = pytest.mark.trial(n=7).mark
        assert _resolve_trial_n(marker) == 7

    def test_positional_n(self) -> None:
        marker = pytest.mark.trial(5).mark
        assert _resolve_trial_n(marker) == 5

    def test_keyword_takes_precedence(self) -> None:
        marker = pytest.mark.trial(3, n=10).mark
        assert _resolve_trial_n(marker) == 10

    def test_defaults_to_one(self) -> None:
        marker = pytest.mark.trial(threshold=0.5).mark
        assert _resolve_trial_n(marker) == 1

    def test_string_n_raises_usage_error(self) -> None:
        """Non-integer n raises UsageError instead of a confusing TypeError."""
        marker = pytest.mark.trial(n="five").mark
        with pytest.raises(pytest.UsageError, match="must be an integer"):
            _resolve_trial_n(marker)

    def test_positional_string_raises_usage_error(self) -> None:
        """Non-integer positional arg raises UsageError."""
        marker = pytest.mark.trial("hello").mark
        with pytest.raises(pytest.UsageError, match="must be an integer"):
            _resolve_trial_n(marker)

    def test_float_n_raises_usage_error(self) -> None:
        """Float n raises UsageError."""
        marker = pytest.mark.trial(n=3.5).mark
        with pytest.raises(pytest.UsageError, match="must be an integer"):
            _resolve_trial_n(marker)

    def test_bool_n_raises_usage_error(self) -> None:
        """Bool n raises UsageError (bool is subclass of int)."""
        marker = pytest.mark.trial(n=True).mark
        with pytest.raises(pytest.UsageError, match="must be an integer"):
            _resolve_trial_n(marker)

    def test_bool_false_raises_usage_error(self) -> None:
        """False also rejected despite bool being int subclass."""
        marker = pytest.mark.trial(n=False).mark
        with pytest.raises(pytest.UsageError, match="must be an integer"):
            _resolve_trial_n(marker)


class TestSanitizeForTerminal:
    """ANSI escape sequences are stripped from terminal output."""

    def test_strips_color_codes(self) -> None:
        text = "\x1b[31mRED TEXT\x1b[0m"
        assert _sanitize_for_terminal(text) == "RED TEXT"

    def test_strips_cursor_movement(self) -> None:
        text = "\x1b[2Ahidden"
        assert _sanitize_for_terminal(text) == "hidden"

    def test_passthrough_clean_text(self) -> None:
        text = "normal summary line"
        assert _sanitize_for_terminal(text) == "normal summary line"

    def test_strips_clear_screen(self) -> None:
        text = "\x1b[2J\x1b[Hinjected"
        assert _sanitize_for_terminal(text) == "injected"

    def test_strips_osc_hyperlink(self) -> None:
        text = "\x1b]8;;http://evil\x07link\x1b]8;;\x07"
        assert _sanitize_for_terminal(text) == "link"


class TestWriteResultLine:
    """_write_result_line writes formatted status, summary, and observability level."""

    def test_safe_result_includes_observability(self) -> None:
        reporter = MagicMock()
        result = Result(
            status=SafetyStatus.SAFE,
            summary="ok",
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
        )
        _write_result_line(
            terminalreporter=cast("TerminalReporter", reporter),
            result=result,
        )
        reporter.write_line.assert_called_once_with("  PASS  ok (response_only)")

    def test_unsafe_result_includes_observability(self) -> None:
        reporter = MagicMock()
        result = Result(
            status=SafetyStatus.UNSAFE,
            summary="bad",
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )
        _write_result_line(
            terminalreporter=cast("TerminalReporter", reporter),
            result=result,
        )
        reporter.write_line.assert_called_once_with(
            "  FAIL  bad (tool_and_side_effects)",
        )

    def test_with_test_name(self) -> None:
        reporter = MagicMock()
        result = Result(
            status=SafetyStatus.SAFE,
            summary="SAFE",
            observability_level=ObservabilityLevel.TOOL_ONLY,
        )
        _write_result_line(
            terminalreporter=cast("TerminalReporter", reporter),
            result=result,
            test_name="test_exfil",
        )
        reporter.write_line.assert_called_once_with(
            "  PASS  test_exfil -- SAFE (tool_only)",
        )

    def test_ansi_stripped_from_summary(self) -> None:
        reporter = MagicMock()
        result = Result(
            status=SafetyStatus.SAFE,
            summary="\x1b[31mevil\x1b[0m",
        )
        _write_result_line(
            terminalreporter=cast("TerminalReporter", reporter),
            result=result,
        )
        line = reporter.write_line.call_args[0][0]
        assert "evil" in line
        assert "\x1b" not in line


class TestTerminalSummary:
    """pytest_terminal_summary renders harm-category grouped output."""

    def _make_session_with_results(self) -> RampartSession:
        """Build a RampartSession with two results in different categories."""
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(
                status=SafetyStatus.SAFE,
                summary="safe-one",
                harm_category="data_exfiltration",
            ),
        )
        collector.record(
            result=Result(
                status=SafetyStatus.UNSAFE,
                summary="unsafe-one",
                harm_category="jailbreak",
            ),
        )
        node = MagicMock()
        node.nodeid = "test_file.py::test_summary"
        session.absorb(node=node, collector=collector)
        return session

    def test_noop_when_no_session(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        pytest_terminal_summary(
            terminalreporter=cast("TerminalReporter", reporter),
            exitstatus=0,
            config=cast("pytest.Config", config),
        )
        reporter.write_sep.assert_not_called()

    def test_noop_when_no_results(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = RampartSession()
        pytest_terminal_summary(
            terminalreporter=cast("TerminalReporter", reporter),
            exitstatus=0,
            config=cast("pytest.Config", config),
        )
        reporter.write_sep.assert_not_called()

    def test_writes_incomplete_warning_even_without_results(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        session = RampartSession()
        session.mark_incomplete(reason="worker gw0 crashed \x1b[31mred")
        config.stash[_rampart_key] = session
        pytest_terminal_summary(terminalreporter=reporter, exitstatus=0, config=config)

        sep_titles = [str(c) for c in reporter.write_sep.call_args_list]
        assert any("INCOMPLETE RUN" in t for t in sep_titles)
        reason_args = [
            c.args[0]
            for c in reporter.write_line.call_args_list
            if c.args and "gw0 crashed" in c.args[0]
        ]
        assert reason_args
        assert all("\x1b" not in arg for arg in reason_args)

    def test_writes_summary_header(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = self._make_session_with_results()
        pytest_terminal_summary(
            terminalreporter=cast("TerminalReporter", reporter),
            exitstatus=0,
            config=cast("pytest.Config", config),
        )
        reporter.write_sep.assert_called_once_with("=", "RAMPART Safety Summary")

    def test_writes_population_stats(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = self._make_session_with_results()
        pytest_terminal_summary(
            terminalreporter=cast("TerminalReporter", reporter),
            exitstatus=0,
            config=cast("pytest.Config", config),
        )
        # Check that the Population line was written
        population_calls = [
            c for c in reporter.write_line.call_args_list if "Population:" in str(c)
        ]
        assert len(population_calls) == 1


class TestRampartSessionSinks:
    """RampartSession accepts and exposes sinks."""

    def test_default_no_sinks(self) -> None:
        session = RampartSession()
        assert session.sinks == []

    def test_accepts_sinks(self) -> None:
        mock_sink = MagicMock()
        session = RampartSession(sinks=[mock_sink])
        assert len(session.sinks) == 1

    def test_sinks_returns_copy(self) -> None:
        mock_sink = MagicMock()
        session = RampartSession(sinks=[mock_sink])
        sinks = session.sinks
        sinks.clear()
        assert len(session.sinks) == 1


class TestRampartSessionAddSinks:
    """RampartSession.add_sinks merges fixture-provided sinks."""

    def test_add_sinks_appends(self) -> None:
        config_sink = MagicMock(spec=["emit_async"])
        config_sink.emit_async = MagicMock()
        session = RampartSession(sinks=[config_sink])

        fixture_sink = MagicMock(spec=["emit_async"])
        fixture_sink.emit_async = MagicMock()
        session.add_sinks(sinks=[fixture_sink])

        assert len(session.sinks) == 2

    def test_add_sinks_empty_list_noop(self) -> None:
        session = RampartSession()
        session.add_sinks(sinks=[])
        assert len(session.sinks) == 0

    def test_add_sinks_rejects_non_conforming(self) -> None:
        session = RampartSession()

        class NotASink:
            pass

        with pytest.raises(TypeError, match="Expected ReportSink"):
            session.add_sinks(sinks=[NotASink()])  # ty: ignore[invalid-argument-type]

    def test_add_sinks_preserves_existing(self) -> None:
        """Config-loaded sinks are not lost when fixture sinks are added."""
        sink_a = MagicMock(spec=["emit_async"])
        sink_a.emit_async = MagicMock()
        sink_b = MagicMock(spec=["emit_async"])
        sink_b.emit_async = MagicMock()

        session = RampartSession(sinks=[sink_a])
        session.add_sinks(sinks=[sink_b])

        assert session.sinks[0] is sink_a
        assert session.sinks[1] is sink_b


class TestRampartSessionDuration:
    """RampartSession tracks and reports duration."""

    def test_default_duration_zero(self) -> None:
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test.py::test_dur"
        session.absorb(node=node, collector=collector)
        report = session.build_report()
        assert report.duration_seconds == pytest.approx(0.0)

    def test_set_duration_reflected_in_report(self) -> None:
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test.py::test_dur"
        session.absorb(node=node, collector=collector)
        session.set_duration(duration_seconds=42.5)
        report = session.build_report()
        assert report.duration_seconds == pytest.approx(42.5)


class TestTrialGroupRendering:
    """Trial group aggregate lines are written to terminal."""

    def test_writes_trial_group_line(self) -> None:
        session = RampartSession()
        items: list[Any] = [MagicMock() for _ in range(10)]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_stat[trial-{idx}]"
            collector = ResultCollector()
            status = SafetyStatus.UNSAFE if idx < 2 else SafetyStatus.SAFE
            collector.record(
                result=Result(
                    status=status,
                    summary=f"t-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_file.py::test_stat",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.3,
        )

        reporter = MagicMock()
        _write_trial_group_lines(
            terminalreporter=cast("TerminalReporter", reporter),
            rampart_session=session,
        )

        reporter.write_line.assert_called_once()
        line = reporter.write_line.call_args[0][0]
        assert "8/10 safe" in line
        assert "80% pass rate" in line
        assert "FAILED" in line  # UNSAFE present → always fails

    def test_writes_passing_trial_group_line(self) -> None:
        session = RampartSession()
        items: list[Any] = [MagicMock() for _ in range(3)]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_pass[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    status=SafetyStatus.SAFE,
                    summary=f"t-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_file.py::test_pass",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.5,
        )

        reporter = MagicMock()
        _write_trial_group_lines(
            terminalreporter=cast("TerminalReporter", reporter),
            rampart_session=session,
        )

        reporter.write_line.assert_called_once()
        line = reporter.write_line.call_args[0][0]
        assert "3/3 safe" in line
        assert "100% pass rate" in line
        assert "PASSED" in line

    def test_no_trial_groups_writes_nothing(self) -> None:
        session = RampartSession()
        reporter = MagicMock()
        _write_trial_group_lines(
            terminalreporter=cast("TerminalReporter", reporter),
            rampart_session=session,
        )
        reporter.write_line.assert_not_called()


class TestEvaluateGates:
    """Gate evaluation logs when threshold is exceeded."""

    def test_logs_when_rate_exceeds_threshold(self) -> None:
        session = RampartSession()
        items: list[Any] = [MagicMock() for _ in range(4)]
        for idx, item in enumerate(items):
            item.nodeid = f"test.py::test_gate[trial-{idx}]"
            collector = ResultCollector()
            status = SafetyStatus.UNSAFE if idx < 2 else SafetyStatus.SAFE
            collector.record(
                result=Result(
                    status=status,
                    summary=f"t-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test.py::test_gate",
            clone_nodeids=[item.nodeid for item in items],
            threshold=0.1,
        )

        _evaluate_gates(rampart_session=session)


class TestEmitSinks:
    """Sink emission calls emit_async and handles errors."""

    def test_noop_when_no_sinks(self) -> None:
        session = RampartSession()
        _emit_sinks(rampart_session=session)

    def test_sink_error_swallowed(self) -> None:
        """A failing sink does not raise."""
        mock_sink = MagicMock()
        mock_sink.emit_async = AsyncMock(side_effect=RuntimeError("Kusto down"))
        session = RampartSession(sinks=[mock_sink])
        collector = ResultCollector()
        collector.record(
            result=Result(status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test.py::test_sink"
        session.absorb(node=node, collector=collector)
        # Should not raise
        _emit_sinks(rampart_session=session)


class TestSessionFinishIntegration:
    """pytest_sessionfinish aggregates trials, evaluates gates, and emits sinks."""

    def test_sets_duration(self) -> None:
        import time

        from rampart.pytest_plugin.plugin import (
            _rampart_key,
            _session_start_key,
        )

        session_mock = MagicMock()
        config_stash = _StashStub()
        rs = RampartSession()
        config_stash[_rampart_key] = rs
        config_stash[_session_start_key] = time.monotonic() - 5.0
        session_mock.config.stash = config_stash
        session_mock.items = []

        pytest_sessionfinish(session=cast("pytest.Session", session_mock), exitstatus=0)

        report = rs.build_report()
        assert report.duration_seconds >= 4.0


class TestSinkHookResolution:
    """The pytest_rampart_sinks hook is resolved and validated."""

    def test_has_sink_hook_impl_true_when_impls_present(self) -> None:
        config = MagicMock()
        hook = config.pluginmanager.hook.pytest_rampart_sinks
        hook.get_hookimpls.return_value = [MagicMock()]
        assert _has_sink_hook_impl(config=config) is True

    def test_has_sink_hook_impl_false_when_no_impls(self) -> None:
        config = MagicMock()
        hook = config.pluginmanager.hook.pytest_rampart_sinks
        hook.get_hookimpls.return_value = []
        assert _has_sink_hook_impl(config=config) is False

    def test_resolve_hook_sinks_flattens_implementations(self) -> None:
        sink_a = MagicMock(spec=ReportSink)
        sink_b = MagicMock(spec=ReportSink)
        config = MagicMock()
        config.pluginmanager.hook.pytest_rampart_sinks.return_value = [
            [sink_a],
            [sink_b],
        ]
        result = _resolve_hook_sinks(config=config)
        assert result == [sink_a, sink_b]

    def test_resolve_hook_sinks_drops_non_report_sinks(self) -> None:
        sink_a = MagicMock(spec=ReportSink)
        config = MagicMock()
        config.pluginmanager.hook.pytest_rampart_sinks.return_value = [
            [sink_a, "not-a-sink"],
        ]
        result = _resolve_hook_sinks(config=config)
        assert result == [sink_a]

    def test_resolve_hook_sinks_skips_non_list_results(self) -> None:
        sink_a = MagicMock(spec=ReportSink)
        config = MagicMock()
        config.pluginmanager.hook.pytest_rampart_sinks.return_value = [
            "bad-impl-return",
            [sink_a],
        ]
        result = _resolve_hook_sinks(config=config)
        assert result == [sink_a]


class TestIncompleteExitStatus:
    """Incomplete runs are forced to a non-zero exit status."""

    def test_incomplete_run_forces_tests_failed(self) -> None:
        session = MagicMock()
        session.exitstatus = pytest.ExitCode.OK
        rampart_session = RampartSession()
        rampart_session.mark_incomplete(reason="worker gw1 crashed")
        _enforce_incomplete_exit_status(
            session=cast("pytest.Session", session),
            rampart_session=rampart_session,
        )
        assert session.exitstatus == pytest.ExitCode.TESTS_FAILED

    def test_complete_run_preserves_ok_status(self) -> None:
        session = MagicMock()
        session.exitstatus = pytest.ExitCode.OK
        rampart_session = RampartSession()
        _enforce_incomplete_exit_status(
            session=cast("pytest.Session", session),
            rampart_session=rampart_session,
        )
        assert session.exitstatus == pytest.ExitCode.OK

    def test_incomplete_run_does_not_mask_existing_failure(self) -> None:
        session = MagicMock()
        session.exitstatus = pytest.ExitCode.INTERRUPTED
        rampart_session = RampartSession()
        rampart_session.mark_incomplete(reason="worker gw1 crashed")
        _enforce_incomplete_exit_status(
            session=cast("pytest.Session", session),
            rampart_session=rampart_session,
        )
        assert session.exitstatus == pytest.ExitCode.INTERRUPTED


def _make_result(*, summary: str = "result") -> Result:
    """Build a minimal Result for makereport tests."""
    return Result(status=SafetyStatus.SAFE, summary=summary)


def _make_reporting_item(*, worker: bool = True) -> Any:
    """Build a mock pytest.Item backed by a real Stash.

    Defaults to a worker-like config so the call-phase snapshot fires;
    pass worker=False for a single-process or controller config.
    """
    item = MagicMock()
    item.stash = pytest.Stash()
    item.nodeid = "test_plugin.py::test_stream"
    item.name = "test_stream"
    item.get_closest_marker.return_value = None
    config_kwargs = {
        "stash": pytest.Stash(),
        "getoption": lambda _name, default=None: default,
        "getini": lambda _name: None,
    }
    if worker:
        item.config = SimpleNamespace(
            workerinput={"workerid": "gw0"},
            **config_kwargs,
        )
    else:
        item.config = SimpleNamespace(**config_kwargs)
    return item


def _drive_makereport(
    *,
    item: Any,
    when: str,
    outcome: str = "passed",
    report: Any = None,
) -> Any:
    """Drive the makereport wrapper generator and return its result."""
    call = MagicMock()
    call.when = when
    sent = cast(
        "pytest.TestReport",
        (
            report
            if report is not None
            else SimpleNamespace(
                nodeid="test_plugin.py::test_stream",
                passed=outcome == "passed",
            )
        ),
    )
    gen = pytest_runtest_makereport(
        item=cast("pytest.Item", item),
        call=cast("pytest.CallInfo[None]", call),
    )
    next(gen)
    try:
        gen.send(sent)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("makereport wrapper did not return")


class TestPytestRuntestMakereport:
    """The makereport hook snapshots collector results at the call phase."""

    def test_snapshots_results_at_call_phase(self) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        collector.record(result=_make_result(summary="captured"))
        token = activate_collector(collector)
        try:
            _drive_makereport(item=item, when="call")
        finally:
            deactivate_collector(token)

        snapshot = item.stash[_call_results_key]
        assert len(snapshot) == 1
        assert snapshot[0].summary == "captured"
        assert item.config.stash[_streamed_result_count_key] == 1

    def test_snapshots_empty_list_when_no_results(self) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        token = activate_collector(collector)
        try:
            _drive_makereport(item=item, when="call")
        finally:
            deactivate_collector(token)

        assert item.stash[_call_results_key] == []
        assert item.config.stash[_streamed_result_count_key] == 0

    @pytest.mark.parametrize("outcome", ["failed", "skipped"])
    def test_nonpassing_setup_streams_collected_results(self, outcome: str) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        collector.record(result=_make_result(summary=outcome))
        token = activate_collector(collector)
        try:
            report = _drive_makereport(item=item, when="setup", outcome=outcome)
        finally:
            deactivate_collector(token)

        envelope = getattr(report, REPORT_RESULTS_ATTR)
        assert envelope["results"][0]["summary"] == outcome
        assert item.config.stash[_streamed_result_count_key] == 1

    def test_successful_setup_defers_results_to_call(self) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        collector.record(result=_make_result(summary="setup"))
        token = activate_collector(collector)
        try:
            setup_report = _drive_makereport(item=item, when="setup")
            collector.record(result=_make_result(summary="call"))
            call_report = _drive_makereport(item=item, when="call")
        finally:
            deactivate_collector(token)

        assert not hasattr(setup_report, REPORT_RESULTS_ATTR)
        assert [
            result["summary"]
            for result in getattr(call_report, REPORT_RESULTS_ATTR)["results"]
        ] == ["setup", "call"]
        assert item.config.stash[_streamed_result_count_key] == 2

    def test_no_transport_at_teardown_phase(self) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        collector.record(result=_make_result(summary="teardown-only"))
        token = activate_collector(collector)
        try:
            report = _drive_makereport(item=item, when="teardown")
        finally:
            deactivate_collector(token)

        assert _call_results_key not in item.stash
        assert not hasattr(report, REPORT_RESULTS_ATTR)

    def test_no_snapshot_when_no_collector_active(self) -> None:
        item = _make_reporting_item()
        token = _active_collector.set(None)
        try:
            _drive_makereport(item=item, when="call")
        finally:
            _active_collector.reset(token)

        assert _call_results_key not in item.stash

    def test_no_snapshot_when_not_xdist_worker(self) -> None:
        item = _make_reporting_item(worker=False)
        collector = ResultCollector()
        collector.record(result=_make_result())
        token = activate_collector(collector)
        try:
            _drive_makereport(item=item, when="call")
        finally:
            deactivate_collector(token)

        assert _call_results_key not in item.stash

    def test_returns_report_unchanged(self) -> None:
        item = _make_reporting_item()
        report = object()

        returned = _drive_makereport(item=item, when="call", report=report)

        assert returned is report

    def test_report_envelope_contains_call_snapshot_only(self) -> None:
        item = _make_reporting_item()
        collector = ResultCollector()
        collector.record(result=_make_result(summary="call"))
        token = activate_collector(collector)
        try:
            report = _drive_makereport(item=item, when="call")
            collector.record(result=_make_result(summary="teardown"))
        finally:
            deactivate_collector(token)

        envelope = getattr(report, REPORT_RESULTS_ATTR)
        assert envelope["nodeid"] == item.nodeid
        assert len(envelope["results"]) == 1
        assert envelope["results"][0]["summary"] == "call"


def _make_controller_report(*, payload: object) -> tuple[Any, RampartSession]:
    config = SimpleNamespace(
        option=SimpleNamespace(dist="load", numprocesses=2, tx=None),
        stash=pytest.Stash(),
    )
    rampart_session = RampartSession()
    config.stash[_rampart_key] = rampart_session
    node = SimpleNamespace(
        config=config,
        gateway=SimpleNamespace(id="gw0"),
    )
    report = SimpleNamespace(
        node=node,
        nodeid="test_plugin.py::test_stream",
        worker_id="gw0",
    )
    setattr(report, REPORT_RESULTS_ATTR, payload)
    return report, rampart_session


class TestPytestRuntestLogreport:
    def test_controller_incrementally_merges_and_counts_results(self) -> None:
        nodeid = "test_plugin.py::test_stream"
        payload = serialize_report_data(
            config=_make_reporting_item().config,
            nodeid=nodeid,
            results=[_make_result(summary="one"), _make_result(summary="two")],
        )
        report, rampart_session = _make_controller_report(payload=payload)
        pytest_runtest_logreport(cast("pytest.TestReport", report))
        counts = report.node.config.stash[_received_result_counts_key]
        assert [result.summary for result in rampart_session._results] == ["one", "two"]
        assert counts == {"gw0": 2}
        assert {
            result.metadata["_rampart_source_worker"]
            for result in rampart_session._results
        } == {"gw0"}

    def test_malformed_envelope_marks_run_incomplete(self) -> None:
        report, rampart_session = _make_controller_report(
            payload={"schema": "wrong"},
        )
        pytest_runtest_logreport(cast("pytest.TestReport", report))
        assert rampart_session.is_incomplete is True
