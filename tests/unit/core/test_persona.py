# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.persona — Persona dataclass."""

from rampart.core.persona import Persona


class TestPersona:
    def test_construction_with_defaults(self):
        p = Persona(name="test")
        assert p.name == "test"
        assert p.description == ""
        assert p.system_prompt == ""

    def test_full_construction(self):
        p = Persona(
            name="social_engineer",
            description="Crafts socially plausible payloads",
            system_prompt="You are a social engineer...",
        )
        assert p.name == "social_engineer"
        assert p.description == "Crafts socially plausible payloads"
        assert p.system_prompt == "You are a social engineer..."
