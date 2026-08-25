# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Flake8 plugin for RAMPART conventions that ruff cannot express.

Registered as a flake8 *local plugin*: see the ``[flake8:local-plugins]``
section of ``.flake8``. Local plugins need no packaging or installation:
flake8 adds ``tools/`` to ``sys.path`` and imports this module directly.

Rules:
    RMP001: Async functions must be named with an ``_async`` suffix.
    RMP002: Lazy exports must be included in ``__all__``.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator

RMP001 = "RMP001 async function `{name}` must be named with an `_async` suffix"
RMP002 = "RMP002 lazy export `{name}` must be included in `__all__`"
RMP002_DYNAMIC_ALL = (
    "RMP002 `__all__` must be declared as one list, tuple, or set literal "
    "containing only strings"
)
RMP002_DYNAMIC_REGISTRY = (
    "RMP002 `__lazy_imports__` must be declared as one dictionary literal "
    "with string keys"
)


def _is_dunder(name: str) -> bool:
    """Return whether a name follows Python's ``__dunder__`` convention.

    Args:
        name (str): The function name to test.

    Returns:
        bool: True for names like ``__aenter__`` that Python itself defines.
    """
    return name.startswith("__") and name.endswith("__")


def _direct_assignment(
    *,
    statement: ast.stmt,
    name: str,
) -> tuple[ast.expr, ast.expr] | None:
    """Return a direct assignment target and value for a name.

    Args:
        statement (ast.stmt): Module-level statement to inspect.
        name (str): Assignment target to find.

    Returns:
        tuple[ast.expr, ast.expr] | None: Assignment target and value, or
            ``None`` when the statement is not a direct assignment.
    """
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            return target, statement.value
    elif (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id == name
        and statement.value is not None
    ):
        return statement.target, statement.value
    return None


def _unsupported_reference(*, statement: ast.stmt, name: str) -> ast.expr | None:
    """Return a module-level write or direct call involving a name.

    Args:
        statement (ast.stmt): Module-level statement to inspect.
        name (str): Governed declaration name.

    Returns:
        ast.expr | None: Unsupported expression, or ``None`` when absent.
    """
    for node in ast.walk(statement):
        if isinstance(node, ast.Call):
            root = node.func
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name) and root.id == name:
                return node
        if not isinstance(node, (ast.Attribute, ast.Name, ast.Subscript)):
            continue
        if not isinstance(node.ctx, (ast.Del, ast.Store)):
            continue
        if any(
            isinstance(child, ast.Name) and child.id == name for child in ast.walk(node)
        ):
            return node
    return None


def _module_declaration(
    *,
    tree: ast.AST,
    name: str,
) -> tuple[ast.expr | None, ast.expr | None]:
    """Return one direct declaration and any unsupported reference.

    Args:
        tree (ast.AST): Parsed module syntax tree.
        name (str): Declaration name to inspect.

    Returns:
        tuple[ast.expr | None, ast.expr | None]: The sole assigned value and
            an unsupported reference. A second assignment is unsupported and
            returned as the reference.
    """
    if not isinstance(tree, ast.Module):
        return None, None

    value: ast.expr | None = None
    for statement in tree.body:
        assignment = _direct_assignment(statement=statement, name=name)
        if assignment is not None:
            target, assigned_value = assignment
            if value is not None:
                return None, target
            value = assigned_value
            continue

        reference = _unsupported_reference(statement=statement, name=name)
        if reference is not None:
            return None, reference

    return value, None


def _literal_string_dict_keys(
    value: ast.expr,
) -> list[tuple[str, ast.Constant]] | None:
    """Return string keys and nodes from a literal dictionary.

    Args:
        value (ast.expr): Expression expected to contain a dictionary.

    Returns:
        list[tuple[str, ast.Constant]] | None: Literal string keys and their
            nodes, or ``None`` when the expression is dynamic.
    """
    if not isinstance(value, ast.Dict):
        return None

    keys: list[tuple[str, ast.Constant]] = []
    for key in value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.append((key.value, key))
    return keys


def _literal_string_collection(value: ast.expr) -> set[str] | None:
    """Return strings from a literal list, tuple, or set.

    Args:
        value (ast.expr): Expression expected to contain string values.

    Returns:
        set[str] | None: Literal strings, or ``None`` when the expression is
            dynamic.
    """
    if not isinstance(value, (ast.List, ast.Set, ast.Tuple)):
        return None

    names: set[str] = set()
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(
            element.value,
            str,
        ):
            return None
        names.add(element.value)
    return names


def _lazy_export_violations(tree: ast.AST) -> Iterator[tuple[ast.expr, str]]:
    """Yield invalid declarations and lazy exports missing from ``__all__``.

    Args:
        tree (ast.AST): Parsed module syntax tree.

    Yields:
        tuple[ast.expr, str]: Invalid expression and formatted violation.
    """
    lazy_value, lazy_reference = _module_declaration(
        tree=tree,
        name="__lazy_imports__",
    )
    if lazy_reference is not None:
        yield lazy_reference, RMP002_DYNAMIC_REGISTRY
        return
    if lazy_value is None:
        return
    lazy_exports = _literal_string_dict_keys(lazy_value)
    if lazy_exports is None:
        yield lazy_value, RMP002_DYNAMIC_REGISTRY
        return

    all_value, all_reference = _module_declaration(tree=tree, name="__all__")
    if all_reference is not None:
        yield all_reference, RMP002_DYNAMIC_ALL
        return
    if all_value is None:
        yield lazy_value, RMP002_DYNAMIC_ALL
        return
    public_names = _literal_string_collection(all_value)
    if public_names is None:
        yield all_value, RMP002_DYNAMIC_ALL
        return

    for name, key in lazy_exports:
        if name not in public_names:
            yield key, RMP002.format(name=name)


class AsyncSuffixChecker:
    """Flake8 checker enforcing RAMPART's async naming convention."""

    name: ClassVar[str] = "flake8-rampart-async-suffix"
    version: ClassVar[str] = "1.1.0"

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


class LazyExportChecker:
    """Flake8 checker ensuring lazy exports remain public."""

    name: ClassVar[str] = "flake8-rampart-lazy-export"
    version: ClassVar[str] = "1.1.0"

    def __init__(self, tree: ast.AST) -> None:
        """Store the module AST supplied by flake8.

        Args:
            tree (ast.AST): Parsed syntax tree for the file under check.
        """
        self._tree = tree

    def run(self) -> Iterator[tuple[int, int, str, type]]:
        """Yield a violation for every lazy export missing from ``__all__``.

        Yields:
            tuple[int, int, str, type]: Line, column, message, and checker
                type, in the 4-tuple shape flake8 expects.
        """
        for expression, message in _lazy_export_violations(self._tree):
            yield (
                expression.lineno,
                expression.col_offset,
                message,
                type(self),
            )
