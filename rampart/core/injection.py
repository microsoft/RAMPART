# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Surface and InjectionHandle protocols.

Two protocols serving two audiences: Surface is what surface authors
implement; InjectionHandle is what execution strategies consume.

``InjectionHandleMixin`` provides a default sleep-based
``wait_until_ready`` for surfaces that only need a simple delay.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    import types

    from rampart.core.types import Payload


@runtime_checkable
class InjectionHandle(Protocol):
    """A prepared injection, ready to activate as an async context manager.

    Returned by Surface.inject(). Entering activates the injection
    (writes the payload to the data source); exiting removes it
    (guaranteed cleanup even on exceptions).

    Execution strategies depend only on this protocol — never on
    Surface or its concrete implementations.
    """

    @property
    def indexing_delay_seconds(self) -> float:
        """How long to wait after activation for the agent to see the content."""
        ...

    @property
    def readiness_timeout_seconds(self) -> float:
        """Maximum time `wait_until_ready` may block before raising `TimeoutError`."""
        ...

    @property
    def payload_id(self) -> str | None:
        """The injected payload's identifier, for reporting."""
        ...

    @property
    def surface_name(self) -> str:
        """The name of the surface this handle injects into (e.g., 'SharePoint')."""
        ...

    async def wait_until_ready(self) -> None:
        """Block until the injected content is visible to the agent.

        Implementations must complete within `readiness_timeout_seconds`
        or raise `TimeoutError`.
        """
        ...

    async def __aenter__(self) -> Self:
        """Activate the injection (write payload to data source)."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Remove the injection. Must be idempotent. Must not raise."""
        ...


class InjectionHandleMixin:
    """Mixin providing a default sleep-based ``wait_until_ready``.

    Surfaces whose readiness strategy is a simple timed delay can
    inherit from this mixin instead of implementing
    ``wait_until_ready`` from scratch.  The mixin sleeps for
    ``indexing_delay_seconds`` with an upper bound of
    ``readiness_timeout_seconds`` to prevent indefinite blocking.

    Surfaces with more complex readiness logic (e.g. polling an
    API) should implement ``wait_until_ready`` directly.
    """

    indexing_delay_seconds: float
    readiness_timeout_seconds: float

    async def wait_until_ready(self) -> None:
        """Sleep for ``indexing_delay_seconds``, bounded by timeout.

        Raises:
            TimeoutError: If ``indexing_delay_seconds`` exceeds
                ``readiness_timeout_seconds``.
        """
        async with asyncio.timeout(self.readiness_timeout_seconds):
            await asyncio.sleep(self.indexing_delay_seconds)


@runtime_checkable
class Surface(Protocol):
    """An injectable data source.

    Surfaces are fully configured at construction (credentials, target
    location) and expose a universal inject() signature. Teams implement
    this to connect their data sources to the framework.

    The returned InjectionHandle is what execution strategies depend on.
    This separation means XPIAExecution never imports or depends on any
    Surface implementation — it only enters handles.
    """

    def inject(self, *, payload: Payload) -> InjectionHandle:
        """Prepare an injection of the given payload.

        Does not activate the injection — the caller enters the
        returned handle as an async context manager to activate it.

        Args:
            payload (Payload): The content to inject.

        Returns:
            InjectionHandle: Ready to activate via async with.
        """
        ...
