# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Hook specifications contributed by the RAMPART pytest plugin.

Registered via ``pytest_addhooks`` in ``plugin.py`` so consuming
projects can implement them in their ``conftest.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pluggy import HookspecMarker

if TYPE_CHECKING:
    import pytest

    from rampart.reporting.sink import ReportSink

hookspec = HookspecMarker("pytest")


@hookspec
def pytest_rampart_sinks(config: pytest.Config) -> list[ReportSink]:  # noqa: ARG001
    """Return the report sinks RAMPART should emit the final report to.

    Implement this hook in your ``conftest.py`` to register sinks in a
    way that works identically in single-process and ``pytest-xdist``
    runs. Unlike the ``rampart_sinks`` fixture, hook implementations are
    resolved on the xdist controller, which never executes fixtures.

    Multiple implementations are supported; RAMPART emits to the union
    of every returned sink.

    Args:
        config (pytest.Config): The active pytest configuration.

    Returns:
        list[ReportSink]: Sinks to emit the run report to. Return an
            empty list to contribute none.
    """
    return []
