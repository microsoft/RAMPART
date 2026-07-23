# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the PyRIT LLM bridge.

Validates translation from public LLMConfig to internal PyRIT
PromptChatTarget, and ensures the internal/public boundary holds.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rampart.core.llm import LLMConfig
from rampart.pyrit_bridge.llm_bridge import create_prompt_target


class TestModelNameResolution:
    """LLMConfig.model and .deployment map to PyRIT's model_name / underlying_model."""

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_model_becomes_model_name_without_deployment(
        self,
        mock_cls: MagicMock,
    ) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="sk-test",
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["model_name"] == "gpt-4o"
        assert kwargs["underlying_model"] is None

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_deployment_becomes_model_name_with_model_as_underlying(
        self,
        mock_cls: MagicMock,
    ) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://myresource.openai.azure.com/openai/v1",
                api_key="key",
                deployment="my-gpt4o-deployment",
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["model_name"] == "my-gpt4o-deployment"
        assert kwargs["underlying_model"] == "gpt-4o"


class TestEndpointAndAuth:
    """Endpoint and api_key are forwarded directly to PyRIT."""

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_endpoint_forwarded(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://custom.endpoint.com/v1",
                api_key="k",
            ),
        )

        assert mock_cls.call_args.kwargs["endpoint"] == "https://custom.endpoint.com/v1"

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_api_key_forwarded(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="sk-secret",
            ),
        )

        assert mock_cls.call_args.kwargs["api_key"] == "sk-secret"

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_none_api_key_forwarded_for_entra_auth(self, mock_cls: MagicMock) -> None:
        """None api_key lets PyRIT use Entra ID auth for Azure endpoints."""
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://myresource.openai.azure.com/v1",
            ),
        )

        assert mock_cls.call_args.kwargs["api_key"] is None


class TestMetadataForwarding:
    """Recognised model parameters in metadata are forwarded; unknown keys are not."""

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_temperature_and_top_p_forwarded(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
                metadata={"temperature": 0.7, "top_p": 0.9},
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["temperature"] == pytest.approx(0.7)
        assert kwargs["top_p"] == pytest.approx(0.9)

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_all_recognised_params_forwarded(self, mock_cls: MagicMock) -> None:
        meta = {
            "temperature": 0.5,
            "top_p": 0.8,
            "frequency_penalty": 0.3,
            "presence_penalty": 0.4,
            "seed": 42,
            "n": 2,
            "max_completion_tokens": 1000,
            "max_tokens": 500,
            "max_requests_per_minute": 60,
            "is_json_supported": False,
        }
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
                metadata=meta,
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        for key, value in meta.items():
            assert kwargs[key] == value, f"metadata[{key!r}] not forwarded"

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_unknown_metadata_keys_not_forwarded(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
                metadata={"custom_key": "custom_value", "temperature": 0.5},
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        assert "custom_key" not in kwargs
        assert kwargs["temperature"] == pytest.approx(0.5)

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_empty_metadata_adds_no_extra_kwargs(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        # Only the four core params should be present.
        assert set(kwargs.keys()) == {
            "model_name",
            "endpoint",
            "api_key",
            "underlying_model",
        }

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_is_json_supported_false_forwarded(self, mock_cls: MagicMock) -> None:
        create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
                metadata={"is_json_supported": False},
            ),
        )

        kwargs = mock_cls.call_args.kwargs
        assert kwargs["is_json_supported"] is False


class TestReturnValue:
    """create_prompt_target returns the constructed target."""

    @patch("rampart.pyrit_bridge.llm_bridge.OpenAIChatTarget")
    def test_returns_constructed_target(self, mock_cls: MagicMock) -> None:
        result = create_prompt_target(
            LLMConfig(
                model="gpt-4o",
                endpoint="https://api.openai.com/v1",
                api_key="k",
            ),
        )

        assert result is mock_cls.return_value


class TestValidation:
    """Input validation before PyRIT construction."""

    def test_empty_model_raises_value_error(self):
        with pytest.raises(ValueError, match="model"):
            create_prompt_target(
                LLMConfig(
                    model="",
                    endpoint="https://api.openai.com/v1",
                ),
            )

    def test_empty_endpoint_raises_value_error(self):
        with pytest.raises(ValueError, match="endpoint"):
            create_prompt_target(
                LLMConfig(
                    model="gpt-4o",
                    endpoint="",
                ),
            )

    def test_none_model_raises_value_error(self):
        config = LLMConfig(
            model=None,  # ty: ignore[invalid-argument-type]
            endpoint="https://api.openai.com/v1",
        )
        with pytest.raises(ValueError, match="model"):
            create_prompt_target(config)

    def test_none_endpoint_raises_value_error(self):
        config = LLMConfig(
            model="gpt-4o",
            endpoint=None,  # ty: ignore[invalid-argument-type]
        )
        with pytest.raises(ValueError, match="endpoint"):
            create_prompt_target(config)


def _module_imports_pyrit(module_name: str) -> list[str]:
    """Return any ``pyrit`` import statements found in *module_name*'s source."""
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, (
        f"Cannot locate source for {module_name}"
    )

    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=spec.origin)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "pyrit" in node.module:
            violations.append(f"from {node.module} import ...")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "pyrit" in alias.name:
                    violations.append(f"import {alias.name}")
    return violations


class TestBoundaryGuarantees:
    """Public RAMPART modules must never import from PyRIT directly."""

    @pytest.mark.parametrize(
        "module",
        [
            "rampart",
            "rampart.core",
            "rampart.core.llm",
            "rampart.attacks",
        ],
    )
    def test_public_module_has_no_pyrit_imports(self, module: str):
        violations = _module_imports_pyrit(module)
        assert not violations, (
            f"{module} imports PyRIT types — this breaks the internal/public boundary: "
            + ", ".join(violations)
        )
