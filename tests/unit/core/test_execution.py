# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import types
from typing import Self

import pytest

from rampart.core.adapter import AgentAdapter
from rampart.core.errors import InfrastructureError
from rampart.core.execution import (
    BaseExecution,
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
)
from rampart.core.manifest import AppManifest
from rampart.core.result import Result, SafetyStatus
from rampart.core.types import ObservabilityLevel, Request, Response


class _StubSession:
    """Minimal Session satisfying the protocol."""

    async def send_async(self, request: Request) -> Response:
        """Return a fixed response."""
        return Response(text="ok")

    async def __aenter__(self) -> Self:
        """Enter context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Exit context."""


class _StubAdapter:
    """Minimal AgentAdapter satisfying the protocol."""

    async def create_session_async(self) -> _StubSession:
        """Create a stub session."""
        return _StubSession()

    @property
    def manifest(self) -> AppManifest:
        """Return a minimal manifest."""
        return AppManifest(name="TestAgent")

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """Return tool-only observability."""
        return ObservabilityLevel.TOOL_ONLY


class _SuccessExecution(BaseExecution):
    """Execution that returns a safe result."""

    @property
    def strategy_name(self) -> str:
        """Return test strategy name."""
        return "test_strategy"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Return a safe result."""
        return Result(safe=True, status=SafetyStatus.SAFE, summary="ok")


class _InfraErrorExecution(BaseExecution):
    """Execution that raises InfrastructureError."""

    @property
    def strategy_name(self) -> str:
        """Return test strategy name."""
        return "infra_error"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Raise an infrastructure error."""
        raise InfrastructureError("SharePoint returned 503")


class _GenericErrorExecution(BaseExecution):
    """Execution that raises a non-infrastructure exception."""

    @property
    def strategy_name(self) -> str:
        """Return test strategy name."""
        return "generic_error"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Raise a generic runtime error."""
        raise RuntimeError("unexpected failure")


class _RecordingHandler(ExecutionEventHandler):
    """Handler that records all events it receives."""

    def __init__(self) -> None:
        self.events: list[ExecutionEventData] = []

    async def on_event(self, *, event_data: ExecutionEventData) -> None:
        """Record the event data."""
        self.events.append(event_data)


class _BrokenHandler(ExecutionEventHandler):
    """Handler that always raises."""

    async def on_event(self, *, event_data: ExecutionEventData) -> None:
        """Raise unconditionally to test handler safety."""
        raise ValueError("handler broke")


class TestBaseExecutionLifecycle:
    @pytest.mark.asyncio
    async def test_fires_pre_and_post_execute(self) -> None:
        handler = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[handler])
        adapter = _StubAdapter()

        result = await execution.execute_async(adapter=adapter)

        assert result.safe is True
        assert len(handler.events) == 2
        assert handler.events[0].event is ExecutionEvent.ON_PRE_EXECUTE
        assert handler.events[1].event is ExecutionEvent.ON_POST_EXECUTE
        assert handler.events[1].result is result

    @pytest.mark.asyncio
    async def test_post_execute_has_elapsed_time(self) -> None:
        handler = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        post = handler.events[1]
        assert post.elapsed_seconds >= 0.0


class TestInfrastructureErrorHandling:
    @pytest.mark.asyncio
    async def test_produces_error_result(self) -> None:
        execution = _InfraErrorExecution()
        adapter = _StubAdapter()

        result = await execution.execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status is SafetyStatus.ERROR
        assert "SharePoint returned 503" in result.summary

    @pytest.mark.asyncio
    async def test_error_result_has_strategy(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.strategy == "infra_error"

    @pytest.mark.asyncio
    async def test_error_result_has_observability_level(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.observability_level is ObservabilityLevel.TOOL_ONLY

    @pytest.mark.asyncio
    async def test_error_result_has_metadata(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.metadata["error"] == "SharePoint returned 503"
        assert result.metadata["error_type"] == "InfrastructureError"

    @pytest.mark.asyncio
    async def test_fires_post_execute_not_on_error(self) -> None:
        handler = _RecordingHandler()
        execution = _InfraErrorExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        event_types = [e.event for e in handler.events]
        assert ExecutionEvent.ON_POST_EXECUTE in event_types
        assert ExecutionEvent.ON_ERROR not in event_types


class TestGenericErrorPropagation:
    @pytest.mark.asyncio
    async def test_non_infra_error_propagates(self) -> None:
        execution = _GenericErrorExecution()

        with pytest.raises(RuntimeError, match="unexpected failure"):
            await execution.execute_async(adapter=_StubAdapter())

    @pytest.mark.asyncio
    async def test_on_error_fires_before_propagation(self) -> None:
        handler = _RecordingHandler()
        execution = _GenericErrorExecution(event_handlers=[handler])

        with pytest.raises(RuntimeError):
            await execution.execute_async(adapter=_StubAdapter())

        event_types = [e.event for e in handler.events]
        assert ExecutionEvent.ON_PRE_EXECUTE in event_types
        assert ExecutionEvent.ON_ERROR in event_types
        assert ExecutionEvent.ON_POST_EXECUTE not in event_types

    @pytest.mark.asyncio
    async def test_on_error_contains_exception(self) -> None:
        handler = _RecordingHandler()
        execution = _GenericErrorExecution(event_handlers=[handler])

        with pytest.raises(RuntimeError):
            await execution.execute_async(adapter=_StubAdapter())

        error_event = [e for e in handler.events if e.event is ExecutionEvent.ON_ERROR][
            0
        ]
        assert isinstance(error_event.error, RuntimeError)


class TestHandlerSafety:
    @pytest.mark.asyncio
    async def test_broken_handler_does_not_abort_execution(self) -> None:
        broken = _BrokenHandler()
        recorder = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[broken, recorder])

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.safe is True
        assert len(recorder.events) == 2


class TestDefaultHandlerFactory:
    @pytest.mark.asyncio
    async def test_execution_works_without_factory(self) -> None:
        execution = _SuccessExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.safe is True

    @pytest.mark.asyncio
    async def test_factory_handlers_are_prepended(self) -> None:
        from rampart.core.execution import (
            clear_default_handler_factory,
            register_default_handler_factory,
        )

        factory_handler = _RecordingHandler()
        try:
            register_default_handler_factory(lambda: [factory_handler])
            execution = _SuccessExecution()

            await execution.execute_async(adapter=_StubAdapter())

            assert len(factory_handler.events) == 2
        finally:
            clear_default_handler_factory()

    def test_register_rejects_non_callable(self) -> None:
        from rampart.core.execution import register_default_handler_factory

        with pytest.raises(TypeError, match="callable"):
            register_default_handler_factory("not a function")  # type: ignore[arg-type]
