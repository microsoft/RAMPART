# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Surface and InjectionHandle protocols.

Two protocols serving two audiences: Surface is what surface authors
implement; InjectionHandle is what execution strategies consume.

``sleep_until_ready`` is a helper function for surfaces that only need
a simple delay-based readiness wait.
"""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    import types

    from rampart.core.types import Payload


@runtime_checkable
class InjectionHandle(AbstractAsyncContextManager["InjectionHandle", None], Protocol):
    """A prepared injection, ready to activate as an async context manager.

    Returned by Surface.inject(). Entering activates the injection
    (writes the payload to the data source); exiting removes it
    (guaranteed cleanup even on exceptions).

    Execution strategies depend only on this protocol — never on
    Surface or its concrete implementations.
    """

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

        Implementations should raise `TimeoutError` if readiness
        operations are long-running to prevent indefinite blocking.
        """
        ...

    async def __aenter__(self) -> Self:
        """Activate the injection (write payload to data source)."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
        /,
    ) -> None:
        """Remove the injection. Must be idempotent. Must not raise."""
        ...


async def sleep_until_ready(delay: float) -> None:
    """Sleep for `delay` seconds. Default readiness strategy for simple surfaces.

    Args:
        delay: Seconds to sleep before the injection is considered ready.
    """
    await asyncio.sleep(delay)


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
