# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""RAMPART pytest plugin.

Plugin registration via the pytest11 entry point in pyproject.toml.
The plugin module contains all pytest hooks.
"""

from rampart.pytest_plugin._collection import (
    ResultCollectionHandler,
    ResultCollector,
    record_result,
)
from rampart.pytest_plugin._session import RampartSession

__all__ = [
    "RampartSession",
    "ResultCollectionHandler",
    "ResultCollector",
    "record_result",
]
