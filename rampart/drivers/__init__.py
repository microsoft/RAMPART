# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Driver implementations.

Re-exports StaticDriver and provides the _coerce_driver helper
for ergonomic prompt/driver coercion.
"""

from __future__ import annotations

from rampart.core.prompt_driver import PromptDriver
from rampart.core.types import Request
from rampart.drivers.static import StaticDriver

__all__ = ["StaticDriver", "_coerce_driver"]


def _coerce_driver(
    value: str | list[str] | Request | list[Request] | PromptDriver,
) -> PromptDriver:
    """Coerce a string, Request, or list into a PromptDriver.

    Args:
        value: A single prompt string, a list of prompt strings,
            a single Request, a list of Requests, or an existing
            PromptDriver.

    Returns:
        PromptDriver: A driver wrapping the input.
    """
    if isinstance(value, str):
        return StaticDriver(prompts=[value])
    if isinstance(value, Request):
        return StaticDriver(prompts=[value])
    if isinstance(value, list):
        return StaticDriver(prompts=value)
    if isinstance(value, PromptDriver):
        return value
    msg = (
        f"Cannot coerce {type(value).__name__} to PromptDriver. "
        f"Expected str, list[str], Request, list[Request], or PromptDriver."
    )
    raise TypeError(
        msg,
    )
