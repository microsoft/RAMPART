# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.payloads.template — PayloadTemplate."""

import pytest

from rampart.payloads.template import PayloadTemplate


class TestResolve:
    def test_substitutes_variables(self) -> None:
        t = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="Send to {email}",
            variables={"email": "evil@evil.com"},
        )
        assert t.resolve() == "Send to evil@evil.com"

    def test_unresolved_placeholder_raises(self) -> None:
        t = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="Send to {email} via {method}",
            variables={"email": "evil@evil.com"},
        )
        with pytest.raises(KeyError, match="method"):
            t.resolve()


class TestWithVariables:
    def test_returns_new_template(self) -> None:
        original = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="Target {email}",
            variables={"email": "default@test.com"},
        )
        updated = original.with_variables(email="override@test.com")
        assert updated.variables["email"] == "override@test.com"
        assert original.variables["email"] == "default@test.com"

    def test_merges_with_existing_variables(self) -> None:
        original = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="{email} {method}",
            variables={"email": "a@b.com", "method": "smtp"},
        )
        updated = original.with_variables(email="new@evil.com")
        assert updated.variables["email"] == "new@evil.com"
        assert updated.variables["method"] == "smtp"

    def test_with_variables_resolves_correctly(self) -> None:
        t = PayloadTemplate(
            name="test",
            description="test",
            objective="test",
            instruction="Target {email}",
            variables={"email": "default@test.com"},
        )
        updated = t.with_variables(email="override@test.com")
        result = updated.resolve()
        assert result == "Target override@test.com"

    def test_preserves_name_and_description(self) -> None:
        original = PayloadTemplate(
            name="original_name",
            description="original_desc",
            objective="original_obj",
            instruction="{x}",
            variables={"x": "1"},
        )
        updated = original.with_variables(x="2")
        assert updated.name == "original_name"
        assert updated.description == "original_desc"
        assert updated.objective == "original_obj"
