# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.llm — LLMConfig dataclass."""

import pytest

from rampart.core.llm import LLMConfig


class TestLLMConfigConstruction:
    """Construction with required, optional, and keyword-only fields."""

    def test_minimal_construction(self):
        cfg = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        assert cfg.model == "gpt-4o"
        assert cfg.endpoint == "https://api.example.com"

    def test_defaults(self):
        cfg = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        assert cfg.api_key is None
        assert cfg.deployment is None
        assert cfg.metadata == {}

    def test_full_construction(self):
        cfg = LLMConfig(
            model="gpt-4",
            endpoint="https://my-resource.openai.azure.com/",
            api_key="secret",
            deployment="my-gpt4-deployment",
            metadata={"api_version": "2024-06-01"},
        )
        assert cfg.model == "gpt-4"
        assert cfg.endpoint == "https://my-resource.openai.azure.com/"
        assert cfg.api_key == "secret"
        assert cfg.deployment == "my-gpt4-deployment"
        assert cfg.metadata == {"api_version": "2024-06-01"}

    def test_keyword_only(self):
        with pytest.raises(TypeError):
            LLMConfig("gpt-4o", "https://api.example.com")  # ty: ignore[too-many-positional-arguments, missing-argument]

    def test_requires_model(self):
        with pytest.raises(TypeError):
            LLMConfig(endpoint="https://api.example.com")  # ty: ignore[missing-argument]

    def test_requires_endpoint(self):
        with pytest.raises(TypeError):
            LLMConfig(model="gpt-4o")  # ty: ignore[missing-argument]


class TestLLMConfigImmutability:
    """Frozen dataclass prevents mutation."""

    def test_cannot_set_field(self):
        cfg = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        with pytest.raises(AttributeError):
            cfg.model = "gpt-4"  # ty: ignore[invalid-assignment]

    def test_cannot_delete_field(self):
        cfg = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        with pytest.raises(AttributeError):
            del cfg.model


class TestLLMConfigEquality:
    """Frozen dataclasses support equality and hashing."""

    def test_equal_configs(self):
        a = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        b = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        assert a == b

    def test_different_configs(self):
        a = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        b = LLMConfig(model="gpt-4", endpoint="https://api.example.com")
        assert a != b

    def test_metadata_prevents_hashing(self):
        """Metadata is a mutable dict, so frozen hash falls back to TypeError."""
        cfg = LLMConfig(model="gpt-4o", endpoint="https://api.example.com")
        with pytest.raises(TypeError):
            hash(cfg)


class TestLLMConfigReExport:
    """LLMConfig is available via the rampart.core public package."""

    def test_importable_from_core_package(self):
        from rampart.core import LLMConfig as CoreLLMConfig

        assert CoreLLMConfig is LLMConfig

    def test_in_core_all(self):
        import rampart.core

        assert "LLMConfig" in rampart.core.__all__
