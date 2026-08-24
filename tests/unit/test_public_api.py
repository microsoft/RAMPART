# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the top-level RAMPART public API."""

from __future__ import annotations

import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import rampart


def test_pytest_plugin_import_does_not_load_heavy_dependencies() -> None:
    """Plugin startup should not import heavy execution dependencies."""
    script = """
import sys

import rampart.pytest_plugin.plugin

heavy_modules = sorted(
    name
    for name in sys.modules
    if name == "pyrit"
    or name.startswith("pyrit.")
    or name == "transformers"
    or name.startswith("transformers.")
)
if heavy_modules:
    raise SystemExit(f"unexpected heavy imports: {heavy_modules}")
"""

    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("name", "module_name", "attribute_name"),
    [
        ("Attacks", "rampart.attacks", "Attacks"),
        ("LLMDriver", "rampart.drivers.llm", "LLMDriver"),
        ("LLMJudge", "rampart.evaluators", "LLMJudge"),
        ("Probes", "rampart.probes", "Probes"),
        ("TranscriptScope", "rampart.evaluators", "TranscriptScope"),
    ],
)
def test_heavy_public_export_is_loaded_on_demand(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    module_name: str,
    attribute_name: str,
) -> None:
    """A deferred top-level export should resolve once and then be cached."""
    sentinel = object()
    previous: Any = rampart.__dict__.pop(name, None)

    def fake_import_module(requested_module: str) -> SimpleNamespace:
        assert requested_module == module_name
        return SimpleNamespace(**{attribute_name: sentinel})

    monkeypatch.setattr(rampart, "import_module", fake_import_module)
    try:
        assert getattr(rampart, name) is sentinel
        assert rampart.__dict__[name] is sentinel
    finally:
        rampart.__dict__.pop(name, None)
        if previous is not None:
            rampart.__dict__[name] = previous
