# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Helpers for emitting consistent deprecation warnings."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def emit_deprecation_warning(
    *,
    old_item: type | Callable[..., Any] | str,
    new_item: type | Callable[..., Any] | str,
    removed_in: str,
) -> None:
    """Emit a ``DeprecationWarning`` from a deprecated item to its replacement.

    Args:
        old_item (type | Callable[..., Any] | str): The deprecated class,
            function, or its string name.
        new_item (type | Callable[..., Any] | str): The replacement class,
            function, or its string name.
        removed_in (str): The release in which ``old_item`` will be removed.
    """
    old_name = _qualified_name(item=old_item)
    new_name = _qualified_name(item=new_item)
    warnings.warn(
        f"{old_name} is deprecated and will be removed in {removed_in}. "
        f"Use {new_name} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def _qualified_name(*, item: type | Callable[..., Any] | str) -> str:
    """Return a printable name for a class, callable, or string label.

    Args:
        item (type | Callable[..., Any] | str): The item to describe.

    Returns:
        str: ``module.qualname`` for classes and callables, the string itself
            for string labels, or ``repr(item)`` as a last resort.
    """
    if isinstance(item, str):
        return item
    module = getattr(item, "__module__", None)
    qualname = getattr(item, "__qualname__", None)
    if module and qualname:
        return f"{module}.{qualname}"
    return repr(item)
