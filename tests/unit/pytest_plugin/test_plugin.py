# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the RAMPART pytest plugin hooks."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rampart.core.result import Result, SafetyStatus
from rampart.core.types import ObservabilityLevel
from rampart.pytest_plugin._collection import ResultCollectionHandler, ResultCollector
from rampart.pytest_plugin._session import RampartSession
from rampart.pytest_plugin.plugin import (
    _emit_sinks,
    _evaluate_gates,
    _resolve_trial_n,
    _sanitize_for_terminal,
    _write_result_line,
    _write_trial_group_lines,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_sessionfinish,
    pytest_terminal_summary,
    pytest_unconfigure,
)


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
            result=Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test_file.py::test_absorb"

        session.absorb(node=node, collector=collector)

        assert session.has_results
        report = session.build_report()
        assert report.total_runs == 1
        assert report.passed == 1

    def test_has_results_false_when_empty(self) -> None:
        session = RampartSession()
        assert not session.has_results

    def test_build_report_counts(self) -> None:
        session = RampartSession()

        collector = ResultCollector()
        collector.record(
            result=Result(safe=True, status=SafetyStatus.SAFE, summary="s"),
        )
        collector.record(
            result=Result(safe=False, status=SafetyStatus.UNSAFE, summary="u"),
        )
        collector.record(
            result=Result(safe=False, status=SafetyStatus.ERROR, summary="e"),
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
                    safe=statuses[idx] == SafetyStatus.SAFE,
                    status=statuses[idx],
                    summary=f"trial-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_example",
            trial_items=items,
            threshold=0.3,
        )

        groups = session.trial_groups
        assert "test_example" in groups
        group = groups["test_example"]
        assert group.total == 5
        assert group.safe == 2
        assert group.unsafe == 2
        assert group.errors == 1
        assert group.threshold == 0.3
        assert group.pass_rate == pytest.approx(0.4)  # pyright: ignore[reportUnknownMemberType]
        assert not group.passed  # UNSAFE present → always fails

    def test_record_trial_group_all_errors(self) -> None:
        session = RampartSession()

        items: list[Any] = [MagicMock() for _ in range(3)]
        for idx, item in enumerate(items):
            item.nodeid = f"test_file.py::test_err[trial-{idx}]"
            collector = ResultCollector()
            collector.record(
                result=Result(
                    safe=False,
                    status=SafetyStatus.ERROR,
                    summary=f"err-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_err",
            trial_items=items,
            threshold=0.0,
        )

        group = session.trial_groups["test_err"]
        assert group.errors == 3
        assert group.unsafe == 0
        assert group.pass_rate == 0.0
        assert group.passed  # threshold=0.0 means any pass rate is acceptable

    def test_record_trial_group_empty_items_noop(self) -> None:
        session = RampartSession()
        session.record_trial_group(
            base_nodeid="test_empty",
            trial_items=[],
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
        pytest_collection_modifyitems(config=config, items=items)

        assert len(items) == 3
        calls = mock_from_parent.call_args_list
        for i, call in enumerate(calls):
            assert call.kwargs["name"] == f"test_example[trial-{i}]"

    def test_trial_n_zero_raises_usage_error(self) -> None:
        item = _make_trial_item(n=0)
        items: list[Any] = [item]
        config = MagicMock()

        with pytest.raises(pytest.UsageError, match="must be >= 1"):
            pytest_collection_modifyitems(config=config, items=items)

    def test_non_trial_items_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        plain = _make_plain_item()
        trial = _make_trial_item(n=2)
        clone_instances = [MagicMock() for _ in range(2)]
        for clone in clone_instances:
            clone.iter_markers.return_value = []
        type(trial).from_parent = MagicMock(side_effect=clone_instances)

        items: list[Any] = [plain, trial]
        config = MagicMock()
        pytest_collection_modifyitems(config=config, items=items)

        assert items[0] is plain
        assert len(items) == 3

    def test_trial_item_with_no_parent_raises(self) -> None:
        item = _make_trial_item(n=2)
        item.parent = None

        items: list[Any] = [item]
        config = MagicMock()

        with pytest.raises(pytest.UsageError, match="no parent"):
            pytest_collection_modifyitems(config=config, items=items)


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


class TestWriteResultLine:
    """_write_result_line writes formatted status, summary, and observability level."""

    def test_safe_result_includes_observability(self) -> None:
        reporter = MagicMock()
        result = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="ok",
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
        )
        _write_result_line(terminalreporter=reporter, result=result)
        reporter.write_line.assert_called_once_with("  PASS  ok (response_only)")

    def test_unsafe_result_includes_observability(self) -> None:
        reporter = MagicMock()
        result = Result(
            safe=False,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        )
        _write_result_line(terminalreporter=reporter, result=result)
        reporter.write_line.assert_called_once_with(
            "  FAIL  bad (tool_and_side_effects)",
        )

    def test_with_test_name(self) -> None:
        reporter = MagicMock()
        result = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="SAFE",
            observability_level=ObservabilityLevel.TOOL_ONLY,
        )
        _write_result_line(
            terminalreporter=reporter,
            result=result,
            test_name="test_exfil",
        )
        reporter.write_line.assert_called_once_with(
            "  PASS  test_exfil -- SAFE (tool_only)",
        )

    def test_ansi_stripped_from_summary(self) -> None:
        reporter = MagicMock()
        result = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="\x1b[31mevil\x1b[0m",
        )
        _write_result_line(terminalreporter=reporter, result=result)
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
                safe=True,
                status=SafetyStatus.SAFE,
                summary="safe-one",
                harm_category="data_exfiltration",
            ),
        )
        collector.record(
            result=Result(
                safe=False,
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
        pytest_terminal_summary(terminalreporter=reporter, exitstatus=0, config=config)
        reporter.write_sep.assert_not_called()

    def test_noop_when_no_results(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = RampartSession()
        pytest_terminal_summary(terminalreporter=reporter, exitstatus=0, config=config)
        reporter.write_sep.assert_not_called()

    def test_writes_summary_header(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = self._make_session_with_results()
        pytest_terminal_summary(terminalreporter=reporter, exitstatus=0, config=config)
        reporter.write_sep.assert_called_once_with("=", "RAMPART Safety Summary")

    def test_writes_population_stats(self) -> None:
        reporter = MagicMock()
        config = MagicMock()
        config.stash = _StashStub()
        from rampart.pytest_plugin.plugin import _rampart_key

        config.stash[_rampart_key] = self._make_session_with_results()
        pytest_terminal_summary(terminalreporter=reporter, exitstatus=0, config=config)
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
            session.add_sinks(sinks=[NotASink()])  # pyright: ignore[reportArgumentType]

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
            result=Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test.py::test_dur"
        session.absorb(node=node, collector=collector)
        report = session.build_report()
        assert report.duration_seconds == 0.0

    def test_set_duration_reflected_in_report(self) -> None:
        session = RampartSession()
        collector = ResultCollector()
        collector.record(
            result=Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
        )
        node = MagicMock()
        node.nodeid = "test.py::test_dur"
        session.absorb(node=node, collector=collector)
        session.set_duration(duration_seconds=42.5)
        report = session.build_report()
        assert report.duration_seconds == 42.5


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
                    safe=status == SafetyStatus.SAFE,
                    status=status,
                    summary=f"t-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test_file.py::test_stat",
            trial_items=items,
            threshold=0.3,
        )

        reporter = MagicMock()
        _write_trial_group_lines(terminalreporter=reporter, rampart_session=session)

        reporter.write_line.assert_called_once()
        line = reporter.write_line.call_args[0][0]
        assert "8/10 safe" in line
        assert "80% pass rate" in line
        assert "FAILED" in line  # UNSAFE present → always fails

    def test_no_trial_groups_writes_nothing(self) -> None:
        session = RampartSession()
        reporter = MagicMock()
        _write_trial_group_lines(terminalreporter=reporter, rampart_session=session)
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
                    safe=status == SafetyStatus.SAFE,
                    status=status,
                    summary=f"t-{idx}",
                ),
            )
            session.absorb(node=item, collector=collector)

        session.record_trial_group(
            base_nodeid="test.py::test_gate",
            trial_items=items,
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
            result=Result(safe=True, status=SafetyStatus.SAFE, summary="ok"),
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

        pytest_sessionfinish(session=session_mock, exitstatus=0)

        report = rs.build_report()
        assert report.duration_seconds >= 4.0
