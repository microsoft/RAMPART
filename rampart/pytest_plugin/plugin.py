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

Note: The architecture defines _default_handler_factory as a plain
module-level Callable in core/execution.py, written to directly by
the plugin. This implementation uses register_default_handler_factory
and clear_default_handler_factory for better encapsulation. This is
a documented deviation from the architecture.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

from rampart.common.deprecation import emit_deprecation_warning
from rampart.common.text import strip_ansi
from rampart.core.execution import (
    ExecutionEventHandler,
    clear_default_handler_factory,
    register_default_handler_factory,
)
from rampart.core.result import Result, SafetyStatus
from rampart.pytest_plugin import _hooks
from rampart.pytest_plugin._collection import (
    ResultCollectionHandler,
    ResultCollector,
    activate_collector,
    deactivate_collector,
    get_active_collector,
)
from rampart.pytest_plugin._session import RampartSession, tag_collected_results
from rampart.pytest_plugin._xdist import (
    DEFAULT_SIZE_LIMIT_BYTES,
    SIZE_LIMIT_OPTION,
    WorkerOutputError,
    attach_report_results,
    discover_sinks_from_conftest,
    finalize_worker,
    get_dist_mode,
    get_worker_count,
    get_worker_id,
    handle_testnodedown,
    is_xdist_controller,
    is_xdist_worker,
    merge_report_results,
)
from rampart.reporting.sink import ReportSink

if TYPE_CHECKING:
    from collections.abc import Generator

    from _pytest.terminal import TerminalReporter

logger = logging.getLogger(__name__)

__all__ = [
    "pytest_addhooks",
    "pytest_addoption",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_runtest_logreport",
    "pytest_runtest_makereport",
    "pytest_sessionfinish",
    "pytest_terminal_summary",
    "pytest_testnodedown",
    "pytest_unconfigure",
]

# Config-scoped stash keys: one entry per pytest session.
_rampart_key = pytest.StashKey[RampartSession]()
_session_start_key = pytest.StashKey[float]()
_streamed_result_count_key = pytest.StashKey[int]()
_received_result_counts_key = pytest.StashKey[dict[str, int]]()

# Item-scoped stash key: a per-test snapshot consumed by xdist streaming.
_call_results_key = pytest.StashKey[list[Result]]()

# Module-level constants are an acceptable exception in a hook-based
# plugin module where there is no natural owning class.

_STATUS_LABELS: dict[SafetyStatus, str] = {
    SafetyStatus.SAFE: "PASS",
    SafetyStatus.UNSAFE: "FAIL",
    SafetyStatus.UNDETERMINED: "WARN",
    SafetyStatus.ERROR: "ERR",
}


def _sanitize_for_terminal(text: str) -> str:
    """Strip escape sequences and control bytes before terminal output.

    Prevents terminal injection from attacker-controlled payload text
    that may appear in result summaries or incomplete-run reasons.
    Delegates to :func:`rampart.common.text.strip_ansi`.

    Args:
        text (str): The raw text to sanitize.

    Returns:
        str: Text with escape sequences and control bytes removed.
    """
    return strip_ansi(text)


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
        raise pytest.UsageError(msg)
    if raw < 1:
        msg = f"trial(n=) must be >= 1, got {raw}"
        raise pytest.UsageError(msg)
    return raw


def _resolve_trial_threshold(marker: pytest.Mark) -> float:
    """Extract the threshold from a trial marker.

    Returns 0.0 when no threshold is provided (the historical default).

    Args:
        marker (pytest.Mark): The trial marker.

    Returns:
        float: The pass-rate threshold in [0.0, 1.0].
    """
    raw: Any = marker.kwargs.get("threshold", 0.0)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def pytest_addhooks(pluginmanager: pytest.PytestPluginManager) -> None:
    """Register RAMPART's hook specifications.

    Args:
        pluginmanager (pytest.PytestPluginManager): The active plugin
            manager.
    """
    pluginmanager.add_hookspecs(_hooks)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register RAMPART CLI and ini options.

    Args:
        parser (pytest.Parser): The pytest argument parser.
    """
    group = parser.getgroup("rampart")
    group.addoption(
        f"--{SIZE_LIMIT_OPTION.replace('_', '-')}",
        dest=SIZE_LIMIT_OPTION,
        type=int,
        default=None,
        help=(
            "Maximum size in bytes of each serialized Result "
            f"under pytest-xdist (default: {DEFAULT_SIZE_LIMIT_BYTES})."
        ),
    )
    parser.addini(
        SIZE_LIMIT_OPTION,
        help=(
            "Maximum size in bytes of each serialized Result "
            f"under pytest-xdist (default: {DEFAULT_SIZE_LIMIT_BYTES})."
        ),
        default=None,
    )


def _default_handler_factory() -> list[ExecutionEventHandler]:
    """Return the default execution handlers for every BaseExecution."""
    return [ResultCollectionHandler()]


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

    register_default_handler_factory(_default_handler_factory)

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
            getattr(pytest.mark, marker.name)(*marker.args, **marker.kwargs),
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

    Raises:
        pytest.UsageError: If the original item has no parent (cannot be
            cloned in isolation).
    """
    original_name: str = getattr(item, "originalname", item.name)
    display_name = item.name
    parent = item.parent
    callspec = getattr(item, "callspec", None)
    fixtureinfo = getattr(item, "_fixtureinfo", None)
    if parent is None:
        msg = f"Cannot clone trial item with no parent: {item.nodeid}"
        raise pytest.UsageError(msg)
    clones: list[pytest.Item] = []

    for i in range(count):
        trial_name = f"{display_name}[trial-{i}]"
        from_parent_kwargs: dict[str, Any] = {
            "name": trial_name,
            "originalname": original_name,
        }
        if callspec is not None:
            from_parent_kwargs["callspec"] = callspec
        if fixtureinfo is not None:
            from_parent_kwargs["fixtureinfo"] = fixtureinfo

        clone = type(item).from_parent(parent=parent, **from_parent_kwargs)
        # pytest.Item supports arbitrary user attributes for cross-hook state.
        clone._rampart_trial_index = i  # ty: ignore[unresolved-attribute]  # ruff: ignore[private-member-access]
        clone._rampart_trial_base = item.nodeid  # ty: ignore[unresolved-attribute]  # ruff: ignore[private-member-access]

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
    config: pytest.Config,
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
    saw_trial = False
    rampart_session = config.stash.get(_rampart_key, None)
    for item in items:
        trial_marker = item.get_closest_marker("trial")
        if trial_marker is None:
            expanded.append(item)
            continue

        saw_trial = True
        n = _resolve_trial_n(trial_marker)
        threshold = _resolve_trial_threshold(trial_marker)
        clones = _create_trial_clones(
            item=item,
            trial_marker=trial_marker,
            count=n,
        )

        if rampart_session is not None:
            # Registered on every process, including xdist workers whose
            # specs the controller's merge later drops via setdefault. The
            # redundancy is intentional: it keeps single-process and the
            # controller's own collection pass correct without branching on
            # worker vs controller. Do not "optimize" it away on workers —
            # that breaks the single-process and fallback paths.
            base_nodeid = item.nodeid
            for clone in clones:
                rampart_session.register_trial_spec(
                    clone_nodeid=clone.nodeid,
                    base_nodeid=base_nodeid,
                    threshold=threshold,
                )

        expanded.extend(clones)

    items[:] = expanded

    if saw_trial and is_xdist_controller(config=config):
        dist_mode = get_dist_mode(config=config)
        if dist_mode != "loadgroup":
            logger.warning(
                "RAMPART @trial markers present with --dist=%s. Trial "
                "clones may be split across workers. Aggregation remains "
                "correct (controller merges all results), but using "
                "--dist=loadgroup keeps trial clones co-located on one "
                "worker for better locality.",
                dist_mode,
            )


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
    except Exception:
        logger.warning(
            "Failed to absorb results for %s — results may be incomplete.",
            node.nodeid,
            exc_info=True,
        )


@pytest.fixture(autouse=True)
def _rampart_collect(  # pytest discovers this via autouse=True
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


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Snapshot the active collector's results for xdist transport.

    On xdist workers, the call report carries all Results recorded through
    successful setup and call. If setup fails or skips after recording Results,
    its report carries the snapshot because pytest will not produce a call report.
    Teardown-only Results remain outside the transport boundary.

    Restricted to worker processes: single-process and controller runs
    never consume the snapshot, so skipping it there keeps those paths
    allocation-free and byte-identical to their pre-snapshot behavior.

    Runs as a wrapper so it is never skipped by the firstresult builtin
    and always returns the report unchanged.

    Args:
        item (pytest.Item): The test item being reported.
        call (pytest.CallInfo[None]): The call phase information.

    Returns:
        Generator[None, pytest.TestReport, pytest.TestReport]: The
            unchanged report produced by downstream hookimpls.
    """
    report = yield
    if call.when not in {"setup", "call"} or not is_xdist_worker(config=item.config):
        return report
    collector = get_active_collector()
    if collector is None:
        return report
    snapshot = collector.results
    if call.when == "setup" and (report.passed or not snapshot):
        return report
    item.stash[_call_results_key] = snapshot
    results = tag_collected_results(
        node=item,
        results=item.stash[_call_results_key],
    )
    emitted_count = attach_report_results(
        config=item.config,
        report=report,
        results=results,
    )
    current_count = item.config.stash.get(_streamed_result_count_key, 0)
    item.config.stash[_streamed_result_count_key] = current_count + emitted_count
    return report


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Merge a streamed xdist Result envelope on the controller.

    Malformed envelopes mark the run incomplete instead of aborting
    pytest, matching the workeroutput trust-boundary convention.

    Args:
        report (pytest.TestReport): A setup, call, or teardown report.
    """
    node = getattr(report, "node", None)
    config = getattr(node, "config", None)
    if config is None or not is_xdist_controller(config=config):
        return
    rampart_session = config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return
    try:
        merged = merge_report_results(session=rampart_session, report=report)
    except WorkerOutputError as exc:
        worker_id = get_worker_id(node)
        logger.exception(
            "Failed to merge streamed Result report from worker %s.",
            worker_id,
        )
        rampart_session.mark_incomplete(
            reason=f"worker {worker_id} streamed report invalid: {exc}",
        )
        return
    if merged is None:
        return
    worker_id, result_count = merged
    received_counts = config.stash.get(_received_result_counts_key, None)
    if received_counts is None:
        received_counts = {}
        config.stash[_received_result_counts_key] = received_counts
    received_counts[worker_id] = received_counts.get(worker_id, 0) + result_count


def _has_sink_hook_impl(*, config: pytest.Config) -> bool:
    """Return True if any plugin implements ``pytest_rampart_sinks``.

    Keyed on implementation existence, not on the sinks returned: a hook
    implementation may legitimately contribute zero sinks, and that must
    still suppress the legacy fixture fallback.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        bool: True if at least one ``pytest_rampart_sinks`` impl exists.
    """
    hook = getattr(config.pluginmanager.hook, "pytest_rampart_sinks", None)
    if hook is None:
        return False
    return bool(hook.get_hookimpls())


def _resolve_hook_sinks(*, config: pytest.Config) -> list[ReportSink]:
    """Collect and validate sinks from the ``pytest_rampart_sinks`` hook.

    Returns the flattened union of every implementation's contribution.
    Non-``ReportSink`` items (and non-list returns) are dropped with a
    warning so one malformed implementation cannot break emission.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        list[ReportSink]: The validated, flattened sinks (may be empty).
    """
    hook = getattr(config.pluginmanager.hook, "pytest_rampart_sinks", None)
    if hook is None:
        return []
    impl_results = cast("list[object]", hook(config=config))
    sinks: list[ReportSink] = []
    for group in impl_results:
        if not isinstance(group, list):
            logger.warning(
                "pytest_rampart_sinks implementation returned %s, "
                "expected list[ReportSink]; ignoring.",
                type(group).__name__,
            )
            continue
        for sink in cast("list[object]", group):
            if isinstance(sink, ReportSink):
                sinks.append(sink)
            else:
                logger.warning(
                    "pytest_rampart_sinks yielded a non-ReportSink: %r; ignoring.",
                    sink,
                )
    return sinks


@pytest.fixture(scope="session", autouse=True)
def _rampart_sink_bootstrap(  # pytest discovers this via autouse=True
    request: pytest.FixtureRequest,
) -> None:
    """Merge team-provided sinks into the RAMPART session.

    If the consuming project defines a ``rampart_sinks`` fixture
    (session-scoped, returning ``list[ReportSink]``), this fixture
    picks it up and registers those sinks for report emission at
    session end.

    Example in a team's conftest.py:

    ```python
    @pytest.fixture(scope="session")
    def rampart_sinks():
        return [JsonFileReportSink(output_dir=Path(".report"))]
    ```

    Precedence: when a ``pytest_rampart_sinks`` hook implementation
    exists it is authoritative and this fixture-based path is skipped
    entirely (hook sinks are registered at session finish), so a project
    that defines both does not double-register.

    Under pytest-xdist, this fixture is a no-op on worker processes
    (workers skip sink emission entirely); sink discovery on the
    controller is handled by the ``pytest_rampart_sinks`` hook or, as a
    fallback, ``_xdist.discover_sinks_from_conftest``.

    No test author ever imports or references this fixture.
    """
    if is_xdist_worker(config=request.config):
        return

    if _has_sink_hook_impl(config=request.config):
        return

    rampart_session = request.config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return

    try:
        user_sinks = request.getfixturevalue("rampart_sinks")
    except pytest.FixtureLookupError:
        return

    emit_deprecation_warning(
        old_item="The rampart_sinks fixture",
        new_item="the pytest_rampart_sinks hook",
        removed_in="0.3.0",
    )

    if not isinstance(user_sinks, list):
        logger.warning(
            "rampart_sinks fixture must return list[ReportSink], got %s. Ignoring.",
            type(user_sinks).__name__,
        )
        return

    user_sinks = cast("list[object]", user_sinks)

    if not all(isinstance(x, ReportSink) for x in user_sinks):
        logger.warning(
            "rampart_sinks fixture must return list[ReportSink], "
            "got list with non-ReportSink items. Ignoring.",
        )
        return

    user_sinks = cast("list[ReportSink]", user_sinks)

    rampart_session.add_sinks(sinks=user_sinks)
    logger.info(
        "Loaded %d sink(s) from rampart_sinks fixture.",
        len(user_sinks),
    )


def _aggregate_trial_results(
    *,
    rampart_session: RampartSession,
) -> None:
    """Group trial specs by base node ID and compute per-group rates.

    Trial specs are recorded during ``pytest_collection_modifyitems``
    on every process and shipped through the xdist worker payload so
    aggregation does not depend on ``session.items`` — which is not
    reliably populated with trial clones on the xdist controller at
    session-finish time.

    Args:
        rampart_session (RampartSession): The RAMPART session state.
    """
    groups: dict[str, list[tuple[str, float]]] = {}
    for clone_nodeid, spec in rampart_session.trial_specs.items():
        groups.setdefault(spec.base_nodeid, []).append(
            (clone_nodeid, spec.threshold),
        )

    for base_nodeid, clones in groups.items():
        # All clones of the same base share the same threshold; pick any.
        threshold = clones[0][1]
        rampart_session.record_trial_group(
            base_nodeid=base_nodeid,
            clone_nodeids=[c[0] for c in clones],
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
    for base_nodeid, group in sorted(rampart_session.trial_groups.items()):
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


def _enforce_incomplete_exit_status(
    *,
    session: pytest.Session,
    rampart_session: RampartSession,
) -> None:
    """Force a non-zero exit status when the RAMPART run is incomplete.

    A lost or crashed xdist worker can leave every surviving test green,
    so a run that silently dropped a shard would otherwise exit zero. For
    a safety framework "green" must mean "ran and passed", so an
    incomplete run is failed here. An already-failing status is left
    untouched so we never mask a stronger failure signal.

    Args:
        session (pytest.Session): The active pytest session.
        rampart_session (RampartSession): The merged RAMPART session state.
    """
    if not rampart_session.is_incomplete:
        return
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        logger.warning(
            "RAMPART run is incomplete; forcing non-zero exit status.",
        )


def pytest_sessionfinish(
    session: pytest.Session,
    exitstatus: int,  # ruff: ignore[unused-function-argument]  — pytest hook signature
) -> None:
    """Aggregate trial results, evaluate gates, and emit sinks.

    Dispatches between three modes:

    - xdist worker: write slim session metadata to ``config.workeroutput``
      and skip sink emission (Results already streamed on test reports).
    - xdist controller: trials already aggregated against the merged
      ``_results_by_nodeid``; resolve sinks via the
      ``pytest_rampart_sinks`` hook (falling back to conftest discovery),
      evaluate gates, and emit.
    - non-xdist: original single-process pipeline (aggregate, gate,
      emit); hook sinks are added here when the fixture path was
      suppressed.

    An incomplete run (a lost or crashed worker) is forced to a non-zero
    exit status so a dropped shard cannot pass silently.

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

    if is_xdist_worker(config=session.config):
        streamed_result_count = session.config.stash.get(
            _streamed_result_count_key,
            0,
        )
        finalize_worker(
            config=session.config,
            session=rampart_session,
            streamed_result_count=streamed_result_count,
        )
        return

    _aggregate_trial_results(rampart_session=rampart_session)
    _evaluate_gates(rampart_session=rampart_session)
    _enforce_incomplete_exit_status(session=session, rampart_session=rampart_session)

    if is_xdist_controller(config=session.config):
        _record_xdist_metadata(session=session, rampart_session=rampart_session)
        if _has_sink_hook_impl(config=session.config):
            controller_sinks = _resolve_hook_sinks(config=session.config)
        else:
            controller_sinks = discover_sinks_from_conftest(config=session.config)
        if controller_sinks:
            rampart_session.add_sinks(sinks=controller_sinks)
        _emit_sinks(rampart_session=rampart_session)
        return

    if _has_sink_hook_impl(config=session.config):
        rampart_session.add_sinks(sinks=_resolve_hook_sinks(config=session.config))
    _emit_sinks(rampart_session=rampart_session)


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node: object, error: object) -> None:
    """Reconcile a finished xdist worker's streamed Result count.

    Thin delegate to ``_xdist.handle_testnodedown`` so plugin.py stays
    focused on hook registration. Registered as ``optionalhook`` so
    pytest does not warn when pytest-xdist is not installed.

    Args:
        node: The xdist worker node that has finished.
        error: The shutdown error reported by xdist, or None on
            clean exit.
    """
    config = getattr(node, "config", None)
    if config is None:
        return
    rampart_session = config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return
    received_counts = config.stash.get(_received_result_counts_key, {})
    worker_id = get_worker_id(node)
    handle_testnodedown(
        session=rampart_session,
        node=node,
        error=error,
        received_result_count=received_counts.get(worker_id, 0),
    )


def _record_xdist_metadata(
    *,
    session: pytest.Session,
    rampart_session: RampartSession,
) -> None:
    """Attach xdist run-mode metadata to the upcoming report."""
    rampart_session.set_report_metadata(
        metadata={
            "xdist_active": True,
            "worker_count": get_worker_count(config=session.config),
            "dist_mode": get_dist_mode(config=session.config),
        },
    )


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
        except Exception:
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

    Idempotent — subsequent invocations are no-ops, guarding against
    re-emission in nested hook scenarios.

    Args:
        rampart_session (RampartSession): The RAMPART session state.
    """
    if rampart_session.is_emitted:
        return
    if not rampart_session.sinks:
        rampart_session.mark_emitted()
        return

    rampart_session.mark_emitted()
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
    for base_nodeid, group in sorted(rampart_session.trial_groups.items()):
        test_name = base_nodeid.split("::")[-1] if "::" in base_nodeid else base_nodeid
        terminalreporter.write_line(
            f"  {group.terminal_label}  {test_name} "
            f"[{group.detail}, {group.pass_rate:.0%} pass rate, "
            f"threshold: {group.threshold:.0%}] -- {group.verdict}",
        )


def _write_incomplete_warning(
    *,
    terminalreporter: TerminalReporter,
    rampart_session: RampartSession,
) -> None:
    """Write a prominent warning when the RAMPART run is incomplete.

    Incomplete runs (e.g. a crashed or lost xdist worker) can still exit
    zero with every surviving test passing, so the reasons are surfaced
    here regardless of whether any results were collected.

    Args:
        terminalreporter: The pytest terminal reporter.
        rampart_session (RampartSession): The RAMPART session state.
    """
    terminalreporter.write_sep("=", "RAMPART: INCOMPLETE RUN", red=True, bold=True)
    terminalreporter.write_line(
        "Results may be partial; the report does not reflect every test.",
    )
    for reason in rampart_session.incomplete_reasons:
        terminalreporter.write_line(f"  - {_sanitize_for_terminal(reason)}")


def pytest_terminal_summary(
    terminalreporter: TerminalReporter,
    exitstatus: int,  # ruff: ignore[unused-function-argument]  — pytest hook signature
    config: pytest.Config,
) -> None:
    """Append RAMPART harm-category summary after pytest's standard output.

    Fires after all tests complete. Emits an incomplete-run warning first
    (even when no results were collected, since a lost worker can leave
    the run incomplete with zero results), then writes harm-grouped
    result lines, trial group aggregates, and population statistics.

    Args:
        terminalreporter: The pytest terminal reporter.
        exitstatus (int): The session exit status.
        config (pytest.Config): The pytest configuration object.
    """
    rampart_session = config.stash.get(_rampart_key, None)
    if rampart_session is None:
        return

    if rampart_session.is_incomplete:
        _write_incomplete_warning(
            terminalreporter=terminalreporter,
            rampart_session=rampart_session,
        )

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
            test_name = result.metadata.get("_pytest_test_name", "")
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
