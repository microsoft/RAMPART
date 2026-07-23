# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Result collection infrastructure for the pytest plugin.

Provides the ContextVar-based mechanism for collecting Result objects
produced during test execution. The pytest plugin activates a collector
per test; execution event handlers write into it automatically.
"""

from __future__ import annotations

import sys
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from rampart.core.execution import (
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
)

if TYPE_CHECKING:
    from rampart.core.result import Result

_active_collector: ContextVar[ResultCollector | None] = ContextVar(
    "_active_collector",
    default=None,
)


def activate_collector(collector: ResultCollector) -> Token[ResultCollector | None]:
    """Set the given collector as the active per-test collector.

    Returns a token that must be passed to deactivate_collector to
    restore the previous state.

    Args:
        collector (ResultCollector): The collector to install.

    Returns:
        Token[ResultCollector | None]: Reset token for deactivation.
    """
    return _active_collector.set(collector)


def deactivate_collector(token: Token[ResultCollector | None]) -> None:
    """Restore the previous collector state using the token from activate_collector.

    Args:
        token (Token[ResultCollector | None]): The token returned by activate_collector.
    """
    _active_collector.reset(token)


class ResultCollector:
    """Accumulates Result objects produced during a single test.

    Framework-internal. Never referenced by test authors.
    """

    def __init__(self) -> None:
        self._results: list[Result] = []

    def record(self, *, result: Result) -> None:
        """Record a result.

        Args:
            result (Result): The result to record.
        """
        self._results.append(result)

    @property
    def results(self) -> list[Result]:
        """All results recorded so far."""
        return list(self._results)


class ResultCollectionHandler(ExecutionEventHandler):
    """Default ExecutionEventHandler installed on every BaseExecution.

    Writes the Result into the active per-test collector on
    ON_POST_EXECUTE. No-op for all other events. No-op when no
    collector is active (safe to use outside pytest).
    """

    @override
    async def on_event(self, *, event_data: ExecutionEventData) -> None:
        """Record result on post-execute. Ignore all other events.

        Args:
            event_data (ExecutionEventData): The event data.
        """
        if event_data.event is not ExecutionEvent.ON_POST_EXECUTE:
            return
        if event_data.result is None:
            return
        collector = _active_collector.get()
        if collector is not None:
            collector.record(result=event_data.result)


def record_result(result: Result) -> None:
    """Record a Result into the active test's collector.

    For building-block tests that construct Results manually rather
    than via Attacks.* or Probes.* factories. No-op when called
    outside a pytest test context (e.g., in library usage or scripts).

    Re-exported from rampart at the top level — consumers import it as:

        from rampart import record_result

    Args:
        result (Result): The result to record.
    """
    collector = _active_collector.get()
    if collector is not None:
        collector.record(result=result)
