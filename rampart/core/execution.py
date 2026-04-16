# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""BaseExecution ABC and execution lifecycle infrastructure.

All execution strategies inherit BaseExecution, which owns the execution
lifecycle and cross-cutting concerns (result collection, timing, event
dispatch, infrastructure error handling).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rampart.core.errors import InfrastructureError
from rampart.core.result import Result, SafetyStatus

if TYPE_CHECKING:
    from rampart.core.adapter import AgentAdapter

logger = logging.getLogger(__name__)


class ExecutionEvent(Enum):
    """Lifecycle events fired during a BaseExecution run.

    ON_PRE_EXECUTE:  Fired before _execute_async is called.
    ON_POST_EXECUTE: Fired after _execute_async returns a Result.
    ON_ERROR:        Fired if _execute_async raises. The exception
                     is re-raised after all handlers have been notified.
    """

    ON_PRE_EXECUTE = "on_pre_execute"
    ON_POST_EXECUTE = "on_post_execute"
    ON_ERROR = "on_error"


@dataclass(kw_only=True)
class ExecutionEventData:
    """Data passed to event handlers at each lifecycle point.

    Args:
        event (ExecutionEvent): Which lifecycle point fired.
        adapter (AgentAdapter): The adapter under test.
        result (Result | None): Populated on ON_POST_EXECUTE only.
        error (Exception | None): Populated on ON_ERROR only.
        elapsed_seconds (float): Wall-clock seconds since execute_async was called.
    """

    event: ExecutionEvent
    adapter: AgentAdapter
    result: Result | None = None
    error: Exception | None = None
    elapsed_seconds: float = 0.0


class ExecutionEventHandler(ABC):
    """Receives lifecycle events from BaseExecution.

    The pytest plugin installs a ResultCollectionHandler on every
    execution via the _default_handler_factory hook. Teams can
    register additional handlers via the event_handlers constructor
    parameter for custom observability.
    """

    @abstractmethod
    async def on_event(self, *, event_data: ExecutionEventData) -> None:
        """Handle an execution lifecycle event.

        Args:
            event_data (ExecutionEventData): The event data.
        """
        ...


@runtime_checkable
class ExecutionHandlerFactory(Protocol):
    """Factory that creates default ExecutionEventHandlers for every BaseExecution.

    When a BaseExecution is instantiated it needs a set of framework-level
    handlers (e.g. the ResultCollectionHandler that funnels results into
    the reporting pipeline). Rather than forcing every test to wire those
    handlers manually, a single factory is registered once at startup and
    called automatically inside ``BaseExecution.__init__`` to supply them.

    Lifecycle:
        1. The pytest plugin calls ``register_default_handler_factory(factory)``
           during ``pytest_configure``.
        2. Each ``BaseExecution.__init__`` invokes the factory to obtain a
           fresh list of handlers, which are prepended to any user-supplied
           handlers.
        3. The plugin calls ``clear_default_handler_factory()`` during
           ``pytest_unconfigure`` to remove the factory.

    Any callable with the signature ``() -> list[ExecutionEventHandler]``
    satisfies this protocol — a plain function, a lambda, or an object
    with a ``__call__`` method all work.
    """

    def __call__(self) -> list[ExecutionEventHandler]:
        """Return a fresh list of default handlers for a new BaseExecution."""
        ...


class _DefaultHandlerRegistry:
    """Mutable registry for the default handler factory.

    Wrapping the reference in a registry instance avoids ``global``
    statements — register/clear simply mutate the ``.factory``
    attribute on the module-level singleton.
    """

    def __init__(self) -> None:
        self.factory: ExecutionHandlerFactory | None = None

    def __call__(self) -> list[ExecutionEventHandler]:
        """Invoke the stored factory, or return an empty list if unset."""
        if self.factory is None:
            return []
        return self.factory()


# Singleton instance — the pytest plugin writes to .factory;
# BaseExecution reads via __call__.
_default_handler_factory = _DefaultHandlerRegistry()


def register_default_handler_factory(
    factory: ExecutionHandlerFactory,
) -> None:
    """Install a factory that provides default handlers for every BaseExecution.

    Called by the pytest plugin at configure time. The factory is invoked
    once per BaseExecution.__init__ to supply framework-level handlers
    (e.g. ResultCollectionHandler) without requiring test authors to
    wire them manually.

    Args:
        factory (ExecutionHandlerFactory): Callable returning a list of
            ExecutionEventHandler instances.

    Raises:
        TypeError: If factory does not satisfy ExecutionHandlerFactory.
    """
    if not callable(factory):
        msg = (
            "factory must satisfy ExecutionHandlerFactory (callable returning "
            "list[ExecutionEventHandler])"
        )
        raise TypeError(
            msg,
        )
    _default_handler_factory.factory = factory


def clear_default_handler_factory() -> None:
    """Remove the installed default handler factory.

    Called by the pytest plugin at unconfigure time to restore the
    module to its clean, no-plugin state.
    """
    _default_handler_factory.factory = None


class BaseExecution(ABC):
    """ABC for all execution strategies.

    Owns the execution lifecycle: ON_PRE_EXECUTE → _execute_async →
    ON_POST_EXECUTE (or ON_ERROR). Subclasses implement only
    _execute_async — the skeleton is fixed here.

    Cross-cutting concerns (result collection, timing, infrastructure
    error handling) are handled by the lifecycle skeleton and
    ExecutionEventHandlers.

    Infrastructure resilience is a base-class concern. If
    _execute_async raises InfrastructureError, the base class catches
    it and produces a Result with SafetyStatus.ERROR.

    Args:
        event_handlers (list[ExecutionEventHandler] | None): Additional
            handlers to register alongside the framework defaults.
    """

    def __init__(
        self,
        *,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> None:
        """Initialize with optional extra event handlers."""
        defaults = _default_handler_factory()
        self._handlers: list[ExecutionEventHandler] = defaults + (event_handlers or [])

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Short identifier for this execution strategy.

        Used in Result.strategy for reporting and dashboard grouping.
        Examples: "xpia", "probe", "crescendo", "pair".
        """
        ...

    async def execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Execute the safety test.

        Fires lifecycle events and delegates to _execute_async for
        strategy-specific logic.

        InfrastructureError from _execute_async is caught here and
        converted to a Result with SafetyStatus.ERROR.

        Other exceptions propagate after ON_ERROR fires.

        Args:
            adapter (AgentAdapter): The agent to test.

        Returns:
            Result: Safety verdict with evidence and diagnostics.

        Raises:
            Exception: Any non-InfrastructureError exception from
                _execute_async, after notifying handlers via ON_ERROR.
        """
        start = time.monotonic()
        await self._fire(
            ExecutionEvent.ON_PRE_EXECUTE,
            adapter=adapter,
            elapsed=0.0,
        )

        try:
            result = await self._execute_async(adapter=adapter)
        except InfrastructureError as exc:
            logger.warning(
                "Infrastructure error during %s execution: %s",
                self.strategy_name,
                exc,
                exc_info=True,
            )
            result = Result(
                safe=False,
                status=SafetyStatus.ERROR,
                summary=f"Infrastructure error: {exc}",
                strategy=self.strategy_name,
                observability_level=adapter.observability_profile,
                metadata={"error": str(exc), "error_type": type(exc).__name__},
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            await self._fire(
                ExecutionEvent.ON_ERROR,
                adapter=adapter,
                elapsed=elapsed,
                error=exc,
            )
            raise

        elapsed = time.monotonic() - start
        result.duration_seconds = elapsed
        await self._fire(
            ExecutionEvent.ON_POST_EXECUTE,
            adapter=adapter,
            elapsed=elapsed,
            result=result,
        )
        return result

    @abstractmethod
    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Core execution logic implemented by each strategy.

        Args:
            adapter (AgentAdapter): The agent to test.

        Returns:
            Result: Safety verdict.
        """
        ...

    async def _fire(
        self,
        event: ExecutionEvent,
        *,
        adapter: AgentAdapter,
        elapsed: float,
        result: Result | None = None,
        error: Exception | None = None,
    ) -> None:
        """Dispatch an event to all registered handlers.

        Handler exceptions are logged and swallowed — a failing
        handler must not abort the test or suppress its result.

        Args:
            event (ExecutionEvent): The lifecycle event to fire.
            adapter (AgentAdapter): The adapter under test.
            elapsed (float): Wall-clock seconds since execute_async started.
            result (Result | None): Present on ON_POST_EXECUTE only.
            error (Exception | None): Present on ON_ERROR only.
        """
        event_data = ExecutionEventData(
            event=event,
            adapter=adapter,
            result=result,
            error=error,
            elapsed_seconds=elapsed,
        )
        for handler in self._handlers:
            try:
                await handler.on_event(event_data=event_data)
            except Exception:  # noqa: BLE001  — handler errors must not break execution
                logger.warning(
                    "ExecutionEventHandler %s raised on %s — ignored.",
                    handler.__class__.__name__,
                    event.value,
                    exc_info=True,
                )
