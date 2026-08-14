# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the flake8-rampart local plugin (RMP001)."""

from __future__ import annotations

import ast
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest
from flake8_rampart import RampartChecker

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _messages(source: str) -> list[str]:
    """Return the messages the checker reports for a source snippet."""
    return [msg for _, _, msg, _ in RampartChecker(ast.parse(source)).run()]


class TestAsyncSuffixRule:
    def test_flags_async_function_without_suffix(self) -> None:
        (message,) = _messages("async def fetch(): ...")
        assert message.startswith("RMP001")
        assert "`fetch`" in message

    def test_accepts_async_function_with_suffix(self) -> None:
        assert _messages("async def fetch_async(): ...") == []

    def test_ignores_sync_function(self) -> None:
        assert _messages("def fetch(): ...") == []

    def test_exempts_dunder(self) -> None:
        assert _messages("async def __aenter__(self): ...") == []

    def test_flags_method_inside_class(self) -> None:
        source = "class A:\n    async def fetch(self): ...\n"
        assert len(_messages(source)) == 1

    def test_flags_nested_function(self) -> None:
        source = "def outer():\n    async def inner(): ...\n"
        assert len(_messages(source)) == 1

    def test_reports_position_of_definition(self) -> None:
        checker = RampartChecker(ast.parse("\n\nasync def fetch(): ..."))
        ((line, col, _, _),) = checker.run()
        assert (line, col) == (3, 0)


@pytest.mark.slow
class TestPluginWiring:
    """Guard against the plugin silently failing to load.

    ``flake8 --select=RMP`` exits 0 when no plugin owns the ``RMP`` prefix, so
    a broken registration would disable the rule with no visible error. These
    tests run the repository's real ``.flake8`` configuration to prove
    otherwise.
    """

    def _run_flake8(self, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [sys.executable, "-m", "flake8", str(target)],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_reports_violation_through_flake8(self, tmp_path: Path) -> None:
        target = tmp_path / "sample.py"
        target.write_text("async def fetch():\n    pass\n", encoding="utf-8")

        result = self._run_flake8(target)

        assert result.returncode == 1
        assert "RMP001" in result.stdout

    def test_honors_noqa_through_flake8(self, tmp_path: Path) -> None:
        target = tmp_path / "sample.py"
        target.write_text(
            "async def fetch():  # noqa: RMP001\n    pass\n",
            encoding="utf-8",
        )

        result = self._run_flake8(target)

        assert result.returncode == 0, result.stdout

    def test_runs_no_rules_other_than_rmp(self, tmp_path: Path) -> None:
        """``select = RMP`` keeps pycodestyle and pyflakes off; that is ruff's job."""
        target = tmp_path / "sample.py"
        target.write_text("import os\nx=1\n", encoding="utf-8")

        result = self._run_flake8(target)

        assert result.returncode == 0, result.stdout
