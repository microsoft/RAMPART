# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Flake8 plugin for RAMPART conventions that ruff cannot express.

Registered as a flake8 *local plugin*: see the ``[flake8:local-plugins]``
section of ``.flake8``. Local plugins need no packaging or installation:
flake8 adds ``tools/`` to ``sys.path`` and imports this module directly.

Rules:
    RMP001: Async functions must be named with an ``_async`` suffix.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator

RMP001 = "RMP001 async function `{name}` must be named with an `_async` suffix"


def _is_dunder(name: str) -> bool:
    """Return whether a name follows Python's ``__dunder__`` convention.

    Args:
        name (str): The function name to test.

    Returns:
        bool: True for names like ``__aenter__`` that Python itself defines.
    """
    return name.startswith("__") and name.endswith("__")


class RampartChecker:
    """Flake8 checker enforcing RAMPART's async naming convention."""

    name: ClassVar[str] = "flake8-rampart"
    version: ClassVar[str] = "1.0.0"

    def __init__(self, tree: ast.AST) -> None:
        """Store the module AST supplied by flake8.

        Args:
            tree (ast.AST): Parsed syntax tree for the file under check.
        """
        self._tree = tree

    def run(self) -> Iterator[tuple[int, int, str, type]]:
        """Yield a violation for every async function missing the suffix.

        Yields:
            tuple[int, int, str, type]: Line, column, message, and checker
                type, in the 4-tuple shape flake8 expects.
        """
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            # Dunders implement Python protocols; their names are not ours to choose.
            if _is_dunder(node.name) or node.name.endswith("_async"):
                continue
            yield (
                node.lineno,
                node.col_offset,
                RMP001.format(name=node.name),
                type(self),
            )
