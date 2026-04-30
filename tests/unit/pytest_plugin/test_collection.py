# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for pytest plugin result collection."""

from __future__ import annotations

from unittest.mock import MagicMock

from rampart.core.execution import ExecutionEvent, ExecutionEventData
from rampart.core.result import Result, SafetyStatus
from rampart.pytest_plugin._collection import (
    ResultCollectionHandler,
    ResultCollector,
    _active_collector,
    activate_collector,
    deactivate_collector,
    record_result,
)


def _make_result(*, summary: str = "test") -> Result:
    """Build a minimal Result for testing."""
    return Result(safe=True, status=SafetyStatus.SAFE, summary=summary)


def _make_event_data(
    *,
    event: ExecutionEvent,
    result: Result | None = None,
) -> ExecutionEventData:
    """Build an ExecutionEventData with a mock adapter."""
    return ExecutionEventData(
        event=event,
        adapter=MagicMock(),
        result=result,
    )


class TestResultCollector:
    """ResultCollector accumulates results through record."""

    def test_record_accumulates(self) -> None:
        collector = ResultCollector()
        r1 = _make_result(summary="first")
        r2 = _make_result(summary="second")

        collector.record(result=r1)
        collector.record(result=r2)

        assert len(collector.results) == 2
        assert collector.results[0].summary == "first"
        assert collector.results[1].summary == "second"

    def test_results_returns_copy(self) -> None:
        collector = ResultCollector()
        collector.record(result=_make_result())

        results = collector.results
        results.clear()

        assert len(collector.results) == 1

    def test_empty_collector(self) -> None:
        collector = ResultCollector()
        assert collector.results == []


class TestResultCollectionHandler:
    """ResultCollectionHandler writes to active collector on ON_POST_EXECUTE."""

    async def test_records_on_post_execute_async(self) -> None:
        collector = ResultCollector()
        token = _active_collector.set(collector)
        try:
            handler = ResultCollectionHandler()
            result = _make_result(summary="captured")
            event_data = _make_event_data(
                event=ExecutionEvent.ON_POST_EXECUTE,
                result=result,
            )

            await handler.on_event(event_data=event_data)

            assert len(collector.results) == 1
            assert collector.results[0].summary == "captured"
        finally:
            _active_collector.reset(token)

    async def test_ignores_pre_execute_async(self) -> None:
        collector = ResultCollector()
        token = _active_collector.set(collector)
        try:
            handler = ResultCollectionHandler()
            event_data = _make_event_data(event=ExecutionEvent.ON_PRE_EXECUTE)

            await handler.on_event(event_data=event_data)

            assert collector.results == []
        finally:
            _active_collector.reset(token)

    async def test_ignores_on_error_async(self) -> None:
        collector = ResultCollector()
        token = _active_collector.set(collector)
        try:
            handler = ResultCollectionHandler()
            event_data = _make_event_data(event=ExecutionEvent.ON_ERROR)

            await handler.on_event(event_data=event_data)

            assert collector.results == []
        finally:
            _active_collector.reset(token)

    async def test_noop_when_no_collector_active_async(self) -> None:
        handler = ResultCollectionHandler()
        result = _make_result()
        event_data = _make_event_data(
            event=ExecutionEvent.ON_POST_EXECUTE,
            result=result,
        )

        await handler.on_event(event_data=event_data)

    async def test_noop_when_result_is_none_async(self) -> None:
        collector = ResultCollector()
        token = _active_collector.set(collector)
        try:
            handler = ResultCollectionHandler()
            event_data = _make_event_data(
                event=ExecutionEvent.ON_POST_EXECUTE,
                result=None,
            )

            await handler.on_event(event_data=event_data)

            assert collector.results == []
        finally:
            _active_collector.reset(token)


class TestRecordResult:
    """record_result is a no-op outside a pytest context."""

    def test_noop_when_no_collector(self) -> None:
        record_result(result=_make_result())

    def test_records_when_collector_active(self) -> None:
        collector = ResultCollector()
        token = _active_collector.set(collector)
        try:
            record_result(result=_make_result(summary="manual"))

            assert len(collector.results) == 1
            assert collector.results[0].summary == "manual"
        finally:
            _active_collector.reset(token)


class TestActivateDeactivateCollector:
    """Public activate/deactivate helpers manage the ContextVar cleanly."""

    def test_activate_and_deactivate_roundtrip(self) -> None:
        collector = ResultCollector()
        token = activate_collector(collector)
        try:
            record_result(result=_make_result(summary="via-helper"))
            assert len(collector.results) == 1
        finally:
            deactivate_collector(token)

        # After deactivation, record_result is a no-op
        record_result(result=_make_result(summary="dropped"))
        assert len(collector.results) == 1

    def test_nested_activation(self) -> None:
        outer = ResultCollector()
        inner = ResultCollector()

        outer_token = activate_collector(outer)
        inner_token = activate_collector(inner)

        record_result(result=_make_result(summary="inner"))
        assert len(inner.results) == 1
        assert len(outer.results) == 0

        deactivate_collector(inner_token)
        record_result(result=_make_result(summary="outer"))
        assert len(outer.results) == 1

        deactivate_collector(outer_token)
