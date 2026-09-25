# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import asyncio
import types
from typing import Self
from unittest.mock import MagicMock

import pytest

from rampart.core.adapter import AgentAdapter
from rampart.core.errors import DriverError, InfrastructureError
from rampart.core.execution import (
    BaseExecution,
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
    execute_trials_async,
)
from rampart.core.manifest import AppManifest
from rampart.core.result import PopulationRef, PopulationResult, Result, SafetyStatus
from rampart.core.types import (
    ObservabilityLevel,
    Request,
    Response,
)


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
        """Minimal manifest."""
        return AppManifest(name="TestAgent")

    @property
    def observability_profile(self) -> ObservabilityLevel:
        """Tool-only observability profile."""
        return ObservabilityLevel.TOOL_ONLY


class _SuccessExecution(BaseExecution):
    """Execution that returns a safe result."""

    @property
    def strategy_name(self) -> str:
        """Test strategy name."""
        return "test_strategy"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Return a safe result."""
        return Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )


class _OrderingExecution(BaseExecution):
    """Execution that records when each trial starts and finishes."""

    def __init__(self, *, index: int, events: list[str]) -> None:
        super().__init__()
        self.index = index
        self.events = events

    @property
    def strategy_name(self) -> str:
        """Test strategy name."""
        return "ordering"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Record trial boundaries around an async scheduling point."""
        self.events.append(f"start-{self.index}")
        await asyncio.sleep(0)
        self.events.append(f"finish-{self.index}")
        return Result(
            observability_level=adapter.observability_profile,
            status=SafetyStatus.SAFE,
            summary="ok",
        )


class _InfraErrorExecution(BaseExecution):
    """Execution that raises InfrastructureError."""

    @property
    def strategy_name(self) -> str:
        """Test strategy name."""
        return "infra_error"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Raise an infrastructure error."""
        raise InfrastructureError("SharePoint returned 503")


class _GenericErrorExecution(BaseExecution):
    """Execution that raises a non-infrastructure exception."""

    @property
    def strategy_name(self) -> str:
        """Test strategy name."""
        return "generic_error"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Raise a generic runtime error."""
        raise RuntimeError("unexpected failure")


class _DriverErrorExecution(BaseExecution):
    """Execution that raises DriverError."""

    @property
    def strategy_name(self) -> str:
        """Test strategy name."""
        return "driver_error"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Raise a driver error."""
        raise DriverError("LLM returned garbage")


class _RecordingHandler(ExecutionEventHandler):
    """Handler that records all events it receives."""

    def __init__(self) -> None:
        self.events: list[ExecutionEventData] = []

    async def on_event_async(self, *, event_data: ExecutionEventData) -> None:
        """Record the event data."""
        self.events.append(event_data)


class _BrokenHandler(ExecutionEventHandler):
    """Handler that always raises."""

    async def on_event_async(self, *, event_data: ExecutionEventData) -> None:
        """Raise unconditionally to test handler safety."""
        raise ValueError("handler broke")


class TestBaseExecutionLifecycle:
    async def test_fires_pre_and_post_execute_async(self) -> None:
        handler = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[handler])
        adapter = _StubAdapter()

        result = await execution.execute_async(adapter=adapter)

        assert result.safe is True
        assert len(handler.events) == 2
        assert handler.events[0].event is ExecutionEvent.ON_PRE_EXECUTE
        assert handler.events[1].event is ExecutionEvent.ON_POST_EXECUTE
        assert handler.events[1].result is result

    async def test_post_execute_has_elapsed_time_async(self) -> None:
        handler = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        post = handler.events[1]
        assert post.elapsed_seconds >= 0.0


class TestExecuteTrials:
    async def test_factory_creates_a_distinct_execution_per_trial_async(self) -> None:
        executions: list[BaseExecution] = []

        def create_execution() -> BaseExecution:
            execution = _SuccessExecution()
            executions.append(execution)
            return execution

        population = await execute_trials_async(
            execution_factory=create_execution,
            adapter=_StubAdapter(),
            n=3,
            threshold=1.0,
        )

        assert len(executions) == 3
        assert len({id(execution) for execution in executions}) == 3
        assert population.executed_count == 3

    async def test_returns_population_result_async(self) -> None:
        population = await execute_trials_async(
            execution_factory=_SuccessExecution,
            adapter=_StubAdapter(),
            n=3,
            threshold=0.8,
        )

        assert population.safe is True
        assert population.executed_count == 3
        assert population.pass_rate == pytest.approx(1.0)

    async def test_runs_normal_lifecycle_for_every_trial_async(self) -> None:
        handler = _RecordingHandler()

        population = await execute_trials_async(
            execution_factory=lambda: _SuccessExecution(event_handlers=[handler]),
            adapter=_StubAdapter(),
            n=3,
            threshold=1.0,
        )

        assert len(population.results) == 3
        assert [event.event for event in handler.events] == [
            ExecutionEvent.ON_PRE_EXECUTE,
            ExecutionEvent.ON_POST_EXECUTE,
        ] * 3

    async def test_runs_trials_sequentially_async(self) -> None:
        events: list[str] = []

        def create_execution() -> BaseExecution:
            return _OrderingExecution(index=len(events) // 2, events=events)

        population = await execute_trials_async(
            execution_factory=create_execution,
            adapter=_StubAdapter(),
            n=3,
            threshold=1.0,
        )

        assert events == [
            "start-0",
            "finish-0",
            "start-1",
            "finish-1",
            "start-2",
            "finish-2",
        ]
        assert population.executed_count == 3

    async def test_attaches_population_ref_before_post_execute_async(self) -> None:
        handler = _RecordingHandler()

        population = await execute_trials_async(
            execution_factory=lambda: _SuccessExecution(event_handlers=[handler]),
            adapter=_StubAdapter(),
            n=3,
            threshold=0.8,
        )

        refs = [result.population for result in population.results]
        assert all(ref is not None for ref in refs)
        assert len({ref.id for ref in refs if ref is not None}) == 1
        assert [ref.index for ref in refs if ref is not None] == [0, 1, 2]
        assert all(ref.size == 3 for ref in refs if ref is not None)
        assert [ref.threshold for ref in refs if ref is not None] == pytest.approx(
            [0.8] * 3,
        )
        post_refs = []
        for event in handler.events:
            if event.event is ExecutionEvent.ON_POST_EXECUTE:
                assert event.result is not None
                post_refs.append(event.result.population)
        assert post_refs == refs

    async def test_separate_populations_have_distinct_ids_async(self) -> None:
        first = await execute_trials_async(
            execution_factory=_SuccessExecution,
            adapter=_StubAdapter(),
            n=1,
            threshold=1.0,
        )
        second = await execute_trials_async(
            execution_factory=_SuccessExecution,
            adapter=_StubAdapter(),
            n=1,
            threshold=1.0,
        )

        assert first.results[0].population is not None
        assert second.results[0].population is not None
        first_id = first.results[0].population.id
        second_id = second.results[0].population.id
        assert first_id != second_id

    async def test_error_result_has_population_ref_on_post_execute_async(self) -> None:
        handler = _RecordingHandler()

        population = await execute_trials_async(
            execution_factory=lambda: _InfraErrorExecution(
                event_handlers=[handler],
            ),
            adapter=_StubAdapter(),
            n=1,
            threshold=1.0,
        )

        result = population.results[0]
        assert result.status is SafetyStatus.ERROR
        assert result.population is not None
        post = handler.events[-1]
        assert post.event is ExecutionEvent.ON_POST_EXECUTE
        assert post.result is result
        assert post.result.population is result.population

    async def test_rejects_non_positive_trial_count_async(self) -> None:
        with pytest.raises(ValueError, match="n must be greater"):
            await execute_trials_async(
                execution_factory=_SuccessExecution,
                adapter=_StubAdapter(),
                n=0,
                threshold=0.8,
            )

    @pytest.mark.parametrize("n", [True, 1.5, "3"])
    async def test_rejects_invalid_trial_count_type_async(self, n: object) -> None:
        with pytest.raises(TypeError, match="n must be a non-boolean integer"):
            await execute_trials_async(
                execution_factory=_SuccessExecution,
                adapter=_StubAdapter(),
                n=n,  # ty: ignore[invalid-argument-type]
                threshold=0.8,
            )

    async def test_rejects_invalid_threshold_before_execution_async(self) -> None:
        handler = _RecordingHandler()

        with pytest.raises(ValueError, match="threshold must be between"):
            await execute_trials_async(
                execution_factory=lambda: _SuccessExecution(
                    event_handlers=[handler],
                ),
                adapter=_StubAdapter(),
                n=3,
                threshold=1.1,
            )

        assert handler.events == []

    @pytest.mark.parametrize("threshold", [True, float("nan"), float("inf")])
    async def test_rejects_malformed_threshold_before_factory_async(
        self,
        threshold: object,
    ) -> None:
        factory = MagicMock(return_value=_SuccessExecution())

        with pytest.raises((TypeError, ValueError)):
            await execute_trials_async(
                execution_factory=factory,
                adapter=_StubAdapter(),
                n=1,
                threshold=threshold,  # ty: ignore[invalid-argument-type]
            )

        factory.assert_not_called()


class TestPopulationPublicExports:
    def test_execute_trials_exported_from_rampart(self) -> None:
        from rampart import execute_trials_async as top_level_execute_trials_async

        assert top_level_execute_trials_async is execute_trials_async

    def test_execute_trials_exported_from_rampart_core(self) -> None:
        from rampart.core import execute_trials_async as core_execute_trials_async

        assert core_execute_trials_async is execute_trials_async

    def test_exported_from_rampart(self) -> None:
        from rampart import PopulationResult as TopLevelPopulationResult

        assert TopLevelPopulationResult is PopulationResult

    def test_exported_from_rampart_core(self) -> None:
        from rampart.core import PopulationResult as CorePopulationResult

        assert CorePopulationResult is PopulationResult

    def test_population_ref_exported_from_rampart(self) -> None:
        from rampart import PopulationRef as TopLevelPopulationRef

        assert TopLevelPopulationRef is PopulationRef

    def test_population_ref_exported_from_rampart_core(self) -> None:
        from rampart.core import PopulationRef as CorePopulationRef

        assert CorePopulationRef is PopulationRef


class TestInfrastructureErrorHandling:
    async def test_produces_error_result_async(self) -> None:
        execution = _InfraErrorExecution()
        adapter = _StubAdapter()

        result = await execution.execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status is SafetyStatus.ERROR
        assert "SharePoint returned 503" in result.summary

    async def test_error_result_has_strategy_async(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.strategy == "infra_error"

    async def test_error_result_has_observability_level_async(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.observability_level is ObservabilityLevel.TOOL_ONLY

    async def test_error_result_has_metadata_async(self) -> None:
        execution = _InfraErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.metadata["error"] == "SharePoint returned 503"
        assert result.metadata["error_type"] == "InfrastructureError"

    async def test_fires_on_error_and_post_execute_async(self) -> None:
        handler = _RecordingHandler()
        execution = _InfraErrorExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        event_types = [e.event for e in handler.events]
        assert ExecutionEvent.ON_ERROR in event_types
        assert ExecutionEvent.ON_POST_EXECUTE in event_types


class TestGenericErrorHandling:
    async def test_produces_error_result_async(self) -> None:
        execution = _GenericErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.safe is False
        assert result.status is SafetyStatus.ERROR
        assert "unexpected failure" in result.summary

    async def test_error_result_has_strategy_async(self) -> None:
        execution = _GenericErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.strategy == "generic_error"

    async def test_error_result_has_metadata_async(self) -> None:
        execution = _GenericErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.metadata["error"] == "unexpected failure"
        assert result.metadata["error_type"] == "RuntimeError"

    async def test_fires_on_error_and_post_execute_async(self) -> None:
        handler = _RecordingHandler()
        execution = _GenericErrorExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        event_types = [e.event for e in handler.events]
        assert ExecutionEvent.ON_ERROR in event_types
        assert ExecutionEvent.ON_POST_EXECUTE in event_types

    async def test_on_error_contains_exception_async(self) -> None:
        handler = _RecordingHandler()
        execution = _GenericErrorExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        error_event = [e for e in handler.events if e.event is ExecutionEvent.ON_ERROR][
            0
        ]
        assert isinstance(error_event.error, RuntimeError)


class TestHandlerSafety:
    async def test_broken_handler_does_not_abort_execution_async(self) -> None:
        broken = _BrokenHandler()
        recorder = _RecordingHandler()
        execution = _SuccessExecution(event_handlers=[broken, recorder])

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.safe is True
        assert len(recorder.events) == 2


class TestDefaultHandlerFactory:
    async def test_execution_works_without_factory_async(self) -> None:
        execution = _SuccessExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.safe is True

    async def test_factory_handlers_are_prepended_async(self) -> None:
        from rampart.core.execution import (
            clear_default_handler_factory,
            register_default_handler_factory,
        )

        factory_handler = _RecordingHandler()
        handlers: list[ExecutionEventHandler] = [factory_handler]
        try:
            register_default_handler_factory(lambda: handlers)
            execution = _SuccessExecution()

            await execution.execute_async(adapter=_StubAdapter())

            assert len(factory_handler.events) == 2
        finally:
            clear_default_handler_factory()

    def test_register_rejects_non_callable(self) -> None:
        from rampart.core.execution import register_default_handler_factory

        with pytest.raises(TypeError, match="callable"):
            register_default_handler_factory("not a function")  # ty: ignore[invalid-argument-type]


class TestDriverErrorHandling:
    async def test_produces_error_result_async(self) -> None:
        execution = _DriverErrorExecution()
        adapter = _StubAdapter()

        result = await execution.execute_async(adapter=adapter)

        assert result.safe is False
        assert result.status is SafetyStatus.ERROR
        assert "LLM returned garbage" in result.summary

    async def test_error_result_has_strategy_async(self) -> None:
        execution = _DriverErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.strategy == "driver_error"

    async def test_error_result_has_metadata_async(self) -> None:
        execution = _DriverErrorExecution()

        result = await execution.execute_async(adapter=_StubAdapter())

        assert result.metadata["error"] == "LLM returned garbage"
        assert result.metadata["error_type"] == "DriverError"

    async def test_fires_on_error_and_post_execute_async(self) -> None:
        handler = _RecordingHandler()
        execution = _DriverErrorExecution(event_handlers=[handler])

        await execution.execute_async(adapter=_StubAdapter())

        event_types = [e.event for e in handler.events]
        assert ExecutionEvent.ON_ERROR in event_types
        assert ExecutionEvent.ON_POST_EXECUTE in event_types


class TestRemovedTurnEvaluator:
    def test_per_turn_helper_is_not_exported(self) -> None:
        from rampart import core
        from rampart.core import execution

        for module in (core, execution):
            assert not hasattr(module, "evaluate_turn_async")
