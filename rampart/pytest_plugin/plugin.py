# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""RAMPART pytest plugin — hooks, markers, collection, and terminal summary.

Registered via the pytest11 entry point in pyproject.toml. Provides:
- harm and trial markers
- automatic result collection via the default handler factory
- trial cloning at collection time
- terminal summary with harm-category grouping
- session-finish aggregation for trial groups
- sink emission for structured reporting

Note: The architecture places RampartSession in plugin.py. This
implementation extracts it to _session.py for file size management.
This is a documented deviation from the architecture.

Note: The architecture defines _default_handler_factory as a plain
module-level Callable in core/execution.py, written to directly by
the plugin. This implementation uses register_default_handler_factory
and clear_default_handler_factory for better encapsulation. This is
a documented deviation from the architecture.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

from rampart.core.execution import (
    clear_default_handler_factory,
    register_default_handler_factory,
)
from rampart.core.result import Result, SafetyStatus
from rampart.pytest_plugin._collection import (
    ResultCollectionHandler,
    ResultCollector,
    activate_collector,
    deactivate_collector,
)
from rampart.pytest_plugin._session import RampartSession

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.terminal import TerminalReporter

logger = logging.getLogger(__name__)

__all__ = [
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_sessionfinish",
    "pytest_terminal_summary",
    "pytest_unconfigure",
]

_rampart_key = pytest.StashKey[RampartSession]()
_session_start_key = pytest.StashKey[float]()

# Module-level constants are an acceptable exception in a hook-based
# plugin module where there is no natural owning class.
_ANSI_ESCAPE_RE: re.Pattern[str] = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_STATUS_LABELS: dict[SafetyStatus, str] = {
    SafetyStatus.SAFE: "PASS",
    SafetyStatus.UNSAFE: "FAIL",
    SafetyStatus.UNDETERMINED: "WARN",
    SafetyStatus.ERROR: "ERR",
}


def _sanitize_for_terminal(text: str) -> str:
    """Strip ANSI escape sequences from text before terminal output.

    Prevents terminal injection from attacker-controlled payload text
    that may appear in result summaries.

    Args:
        text (str): The raw text to sanitize.

    Returns:
        str: Text with ANSI escape sequences removed.
    """
    return _ANSI_ESCAPE_RE.sub("", text)


def _resolve_trial_n(marker: pytest.Mark) -> int:
    """Extract the trial count from a trial marker.

    Supports both positional and keyword argument forms:
    ``@pytest.mark.trial(5)`` and ``@pytest.mark.trial(n=5)``.
    Keyword takes precedence when both are provided.

    Args:
        marker (pytest.Mark): The trial marker.

    Returns:
        int: The number of trial repetitions.

    Raises:
        pytest.UsageError: If the resolved value is not an integer.
    """
    raw: Any
    if "n" in marker.kwargs:
        raw = marker.kwargs["n"]
    elif marker.args:
        raw = marker.args[0]
    else:
        return 1

    if not isinstance(raw, int) or isinstance(raw, bool):
        msg = f"trial(n=) must be an integer, got {type(raw).__name__}: {raw!r}"
        raise pytest.UsageError(
            msg,
        )
    if raw < 1:
        msg = f"trial(n=) must be >= 1, got {raw}"
        raise pytest.UsageError(
            msg,
        )
    return raw


def pytest_configure(config: pytest.Config) -> None:
    """Register RAMPART markers and install default handler factory.

    Initializes session. Sinks are provided by teams via the
    ``rampart_sinks`` fixture in their conftest.py, not through
    configuration.

    Args:
        config (pytest.Config): The pytest configuration object.
    """
    config.addinivalue_line("markers", "harm(*categories): categorize by harm type")
    config.addinivalue_line("markers", "trial(n=, threshold=): statistical repetition")

    register_default_handler_factory(lambda: [ResultCollectionHandler()])

    config.stash[_rampart_key] = RampartSession()
    config.stash[_session_start_key] = time.monotonic()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Clean up the handler factory on plugin teardown.

    Args:
        config (pytest.Config): The pytest configuration object.
    """
    clear_default_handler_factory()
    if _rampart_key in config.stash:
        del config.stash[_rampart_key]
    if _session_start_key in config.stash:
        del config.stash[_session_start_key]


def _copy_markers_to_clone(*, source: pytest.Item, clone: pytest.Item) -> None:
    """Copy all markers from the original item to its trial clone.

    Markers applied at the class level, module level, or via conftest
    pytestmark are NOT transferred by ``from_parent``. This function
    ensures trial clones inherit all markers (harm, parametrize, etc.)
    from the original item. The trial marker itself is re-attached
    separately by the caller.

    Args:
        source (pytest.Item): The original test item with all markers.
        clone (pytest.Item): The cloned item that needs markers copied.
    """
    for marker in source.iter_markers():
        if marker.name == "trial":
            continue
        clone.add_marker(
            pytest.mark.__getattr__(marker.name)(*marker.args, **marker.kwargs),
        )


def _create_trial_clones(
    *,
    item: pytest.Item,
    trial_marker: pytest.Mark,
    count: int,
) -> list[pytest.Item]:
    """Create trial clone items from an original test item.

    Each clone gets a unique ``[trial-N]`` suffix, all markers from
    the original item (including class-level and module-level markers),
    and private attributes for session-end aggregation.

    Args:
        item (pytest.Item): The original test item to clone.
        trial_marker (pytest.Mark): The trial marker to re-attach.
        count (int): Number of trial repetitions to create.

    Returns:
        list[pytest.Item]: The cloned trial items with trial metadata.
    """
    original_name: str = getattr(item, "originalname", item.name)
    display_name = item.name
    parent = item.parent
    callspec = getattr(item, "callspec", None)
    fixtureinfo = getattr(item, "_fixtureinfo", None)
    if parent is None:
        msg = f"Cannot clone trial item with no parent: {item.nodeid}"
        raise pytest.UsageError(
            msg,
        )
    clones: list[pytest.Item] = []

    for i in range(count):
        trial_name = f"{display_name}[trial-{i}]"
        from_parent_kwargs: dict[str, Any] = {
            "parent": parent,
            "name": trial_name,
            "originalname": original_name,
        }
        if callspec is not None:
            from_parent_kwargs["callspec"] = callspec
        if fixtureinfo is not None:
            from_parent_kwargs["fixtureinfo"] = fixtureinfo

        clone = type(item).from_parent(**from_parent_kwargs)  # type: ignore[arg-type]
        clone._rampart_trial_index = i  # type: ignore[attr-defined]  # noqa: SLF001
        clone._rampart_trial_base = item.nodeid  # type: ignore[attr-defined]  # noqa: SLF001

        _copy_markers_to_clone(source=item, clone=clone)
        clone.add_marker(
            pytest.mark.trial(*trial_marker.args, **trial_marker.kwargs),
        )
        # Group all trials for the same base test on one xdist worker
        # so that trial aggregation works correctly across workers.
        clone.add_marker(pytest.mark.xdist_group(item.nodeid))
        clones.append(clone)

    return clones


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001  — pytest hook signature
    items: list[pytest.Item],
) -> None:
    """Clone trial-marked items and validate marker usage.

    Uses ``trylast=True`` so clones are created after pytest-asyncio
    has wrapped async items — ``item.obj`` on the original already
    carries the async wrapper, which is passed to clones via callobj.

    Expands each ``@pytest.mark.trial(n=)`` item into *n* clones with
    distinct node IDs. All markers (harm, parametrize, etc.) from the
    original item are copied to each clone. Attaches
    ``_rampart_trial_index`` and ``_rampart_trial_base`` to each clone
    for session-end aggregation.

    Args:
        config (pytest.Config): The pytest configuration object.
        items (list[pytest.Item]): The collected test items.

    Raises:
        pytest.UsageError: If trial(n=) is not a positive integer or
            item has no parent.
    """
    expanded: list[pytest.Item] = []
    for item in items:
        trial_marker = item.get_closest_marker("trial")
        if trial_marker is None:
            expanded.append(item)
            continue

        n = _resolve_trial_n(trial_marker)

        expanded.extend(
            _create_trial_clones(item=item, trial_marker=trial_marker, count=n),
        )

    items[:] = expanded


def _absorb_results(
    *,
    rampart_session: RampartSession,
    node: pytest.Item,
    collector: ResultCollector,
) -> None:
    """Safely absorb collected results into the session.

    Catches and logs any unexpected errors to prevent the plugin from
    breaking the test run.

    Args:
        rampart_session (RampartSession): The session to absorb into.
        node (pytest.Item): The test item that produced the results.
        collector (ResultCollector): The test's result collector.
    """
    try:
        rampart_session.absorb(node=node, collector=collector)
    except Exception:  # noqa: BLE001  — plugin must not break test runs
        logger.warning(
            "Failed to absorb results for %s — results may be incomplete.",
            node.nodeid,
            exc_info=True,
        )


@pytest.fixture(autouse=True)
def _rampart_collect(  # type: ignore[reportUnusedFunction]  # pytest discovers this via autouse=True
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Installed automatically on every test. Invisible to test authors.

    Scopes a ResultCollector to the current test via ContextVar.
    The ResultCollectionHandler (installed on every BaseExecution via
    the default handler factory) writes into this collector on
    ON_POST_EXECUTE. The collector is drained after the test body
    completes and its results are absorbed by the session-scoped
    RampartSession for terminal summary and sink emission.

    ContextVar state is per-task, so concurrent async tests in the
    same thread each see their own collector.

    No test author ever imports or references this fixture.
    """
    collector = ResultCollector()
    node = cast("pytest.Item", request.node)
    rampart_session = request.config.stash.get(_rampart_key, None)
    token = activate_collector(collector)
    yield
    deactivate_collector(token)
    if rampart_session is not None:
        _absorb_results(rampart_session=rampart_session, node=node, collector=collector)

    # Note: collector.results returns a copy of the internal list,
    # so reading it after deactivation and absorption is safe.
    # absorb() shallow-copies each Result before tagging, so the
    # collector's originals are unmodified.
    harm_marker = node.get_closest_marker("harm")
    if harm_marker and not collector.results:
        logger.warning(
            "Test %s is marked @harm but recorded no results — "
            "did you forget record_result() or assert result?",
            node.nodeid,
        )


@pytest.fixture(scope="session", autouse=True)
def _rampart_sink_bootstrap(  # type: ignore[reportUnusedFunction]  # pytest discovers this via autouse=True
    request: pytest.FixtureRequest,
) -> None:
    """Merge team-provided sinks into the RAMPART session.

    If the consuming project defines a ``rampart_sinks`` fixture
    (session-scoped, returning ``list[ReportSink]``), this fixture
    picks it up and registers those sinks for report emission at
    session end.

    Example in a team's conftest.py::

        @pytest.fixture(scope="session")
        def rampart_sinks():
            return [JsonFileReportSink(output_dir=Path(".report"))]

    No test author ever imports or references this fixture.
    """
    rampart_session = request.config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return

    try:
        user_sinks = request.getfixturevalue("rampart_sinks")
    except pytest.FixtureLookupError:
        return

    if not isinstance(user_sinks, list):
        logger.warning(
            "rampart_sinks fixture must return list[ReportSink], got %s. Ignoring.",
            type(user_sinks).__name__,
        )
        return

    rampart_session.add_sinks(sinks=user_sinks)
    logger.info(
        "Loaded %d sink(s) from rampart_sinks fixture.",
        len(user_sinks),
    )


def _aggregate_trial_results(
    *,
    session: pytest.Session,
    rampart_session: RampartSession,
) -> None:
    """Group trial item reports by base node ID and compute per-group rates.

    A trial group is identified by ``_rampart_trial_base`` on the item.
    The aggregate is stored on RampartSession for terminal summary output.

    Args:
        session (pytest.Session): The pytest session.
        rampart_session (RampartSession): The RAMPART session state.
    """
    groups: dict[str, list[pytest.Item]] = {}
    for item in session.items:
        base: str | None = getattr(item, "_rampart_trial_base", None)
        if base is not None:
            groups.setdefault(base, []).append(item)

    for base_nodeid, trial_items in groups.items():
        marker = trial_items[0].get_closest_marker("trial")
        threshold = marker.kwargs.get("threshold", 0.0) if marker else 0.0
        rampart_session.record_trial_group(
            base_nodeid=base_nodeid,
            trial_items=trial_items,
            threshold=threshold,
        )


def _evaluate_gates(
    *,
    rampart_session: RampartSession,
) -> None:
    """Log trial group gate results.

    Reports whether each trial group passed or failed based on:
    - Any UNSAFE -> FAIL (unconditional)
    - Pass rate below threshold -> FAIL

    Args:
        rampart_session (RampartSession): The RAMPART session state.
    """
    for base_nodeid, group in rampart_session.trial_groups.items():
        if group.passed:
            logger.info(
                "Gate PASSED: %s — %d/%d safe (%.0f%% pass rate, threshold: %.0f%%)",
                base_nodeid,
                group.safe,
                group.total,
                group.pass_rate * 100,
                group.threshold * 100,
            )
        elif group.has_unsafe:
            logger.info(
                "Gate FAILED: %s — %d/%d runs were UNSAFE",
                base_nodeid,
                group.unsafe,
                group.total,
            )
        else:
            logger.info(
                "Gate FAILED: %s — pass rate %.0f%% below threshold %.0f%%",
                base_nodeid,
                group.pass_rate * 100,
                group.threshold * 100,
            )


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int,  # noqa: ARG001  — pytest hook signature
) -> None:
    """Aggregate trial results, evaluate gates, and emit sinks.

    Args:
        session (pytest.Session): The pytest session.
        exitstatus (int): The session exit status.
    """
    rampart_session = session.config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return

    start_time = session.config.stash.get(_session_start_key, None)
    if start_time is not None:
        rampart_session.set_duration(duration_seconds=time.monotonic() - start_time)

    _aggregate_trial_results(session=session, rampart_session=rampart_session)
    _evaluate_gates(rampart_session=rampart_session)
    _emit_sinks(rampart_session=rampart_session)


async def _emit_sinks_async(*, rampart_session: RampartSession) -> None:
    """Emit the test run report to all configured sinks.

    Each sink receives the complete TestRunReport. Sink errors are
    logged and swallowed — a failing sink must not break the test
    session teardown.

    Args:
        rampart_session (RampartSession): The RAMPART session state.
    """
    if not rampart_session.sinks:
        return

    report = rampart_session.build_report()
    for sink in rampart_session.sinks:
        try:
            await sink.emit_async(report=report)
        except Exception:  # noqa: BLE001  — sink errors must not break teardown
            logger.warning(
                "Sink %s.emit_async failed — report may not be persisted.",
                type(sink).__name__,
                exc_info=True,
            )


_background_tasks: set[asyncio.Task[Any]] = set()


def _emit_sinks(*, rampart_session: RampartSession) -> None:
    """Synchronous wrapper for sink emission.

    Used by ``pytest_sessionfinish`` when no event loop is running.
    When an event loop is already running (e.g. pytest-asyncio),
    falls back to scheduling on the existing loop.

    Args:
        rampart_session (RampartSession): The RAMPART session state.
    """
    if not rampart_session.sinks:
        return

    coro = _emit_sinks_async(rampart_session=rampart_session)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop running — start one.
        asyncio.run(coro)
    else:
        # Event loop is already running — schedule the coroutine.
        task = loop.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


def _write_result_line(
    *,
    terminalreporter: TerminalReporter,
    result: Result,
    test_name: str = "",
) -> None:
    """Write a single result line to the terminal.

    Format matches the architecture's example output:
    ``PASS  test_name — summary (observability_level)``

    Args:
        terminalreporter: The pytest terminal reporter.
        result (Result): The result to display.
        test_name (str): The test name to include in the line.
    """
    label = _STATUS_LABELS.get(result.status, "????").ljust(4)
    sanitized_summary = _sanitize_for_terminal(result.summary)
    obs_level = result.observability_level.value

    if test_name:
        terminalreporter.write_line(
            f"  {label}  {test_name} -- {sanitized_summary} ({obs_level})",
        )
    else:
        terminalreporter.write_line(
            f"  {label}  {sanitized_summary} ({obs_level})",
        )


def _write_trial_group_lines(
    *,
    terminalreporter: TerminalReporter,
    rampart_session: RampartSession,
) -> None:
    """Write trial group aggregate lines to the terminal.

    Format: ``PASS  test_name [8/10 safe, 80% defense rate, threshold: 70%] — PASSED``

    Args:
        terminalreporter: The pytest terminal reporter.
        rampart_session (RampartSession): The RAMPART session state.
    """
    for base_nodeid, group in rampart_session.trial_groups.items():
        test_name = base_nodeid.split("::")[-1] if "::" in base_nodeid else base_nodeid
        terminalreporter.write_line(
            f"  {group.terminal_label}  {test_name} "
            f"[{group.detail}, {group.pass_rate:.0%} pass rate, "
            f"threshold: {group.threshold:.0%}] -- {group.verdict}",
        )


def pytest_terminal_summary(
    terminalreporter: TerminalReporter,
    exitstatus: int,  # noqa: ARG001  — pytest hook signature
    config: pytest.Config,
) -> None:
    """Append RAMPART harm-category summary after pytest's standard output.

    Fires after all tests complete. Writes harm-grouped result lines,
    trial group aggregates, and population statistics. No-op if no
    RAMPART results were collected.

    Args:
        terminalreporter: The pytest terminal reporter.
        exitstatus (int): The session exit status.
        config (pytest.Config): The pytest configuration object.
    """
    rampart_session = config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return
    if not rampart_session.has_results:
        return

    terminalreporter.write_sep("=", "RAMPART Safety Summary")
    report = rampart_session.build_report()

    status_order = {
        SafetyStatus.UNSAFE: 0,
        SafetyStatus.ERROR: 1,
        SafetyStatus.UNDETERMINED: 2,
        SafetyStatus.SAFE: 3,
    }

    for category, results in report.by_harm_category().items():
        sorted_results = sorted(results, key=lambda r: status_order.get(r.status, 99))
        terminalreporter.write_line(
            f"\n{category.upper()} ({len(sorted_results)} tests)",
        )
        for result in sorted_results:
            test_name = result.metadata.get("test_name", "")
            _write_result_line(
                terminalreporter=terminalreporter,
                result=result,
                test_name=test_name,
            )

    _write_trial_group_lines(
        terminalreporter=terminalreporter,
        rampart_session=rampart_session,
    )

    stats = report.population_summary()
    if stats.total_runs > 0:
        terminalreporter.write_line(
            f"\nPopulation: {stats.total_runs} runs - "
            f"{stats.unsafe_count} unsafe "
            f"({stats.attack_success_rate:.1%} attack success rate), "
            f"{stats.undetermined_count} undetermined, "
            f"{stats.error_count} errors",
        )
