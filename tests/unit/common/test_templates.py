# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, cast

import pytest
import yaml
from jinja2 import Template, TemplateError

from rampart.common.templates import (
    PromptTemplate,
    PromptTemplateDefinitionError,
    TemplateParameterError,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _write_yaml(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "prompt.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _write_raw_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "prompt.yaml"
    path.write_text(dedent(content), encoding="utf-8")
    return path


def _write_template(tmp_path: Path, **overrides: object) -> Path:
    definition: dict[str, object] = {
        "name": "Greeting",
        "parameters": ["subject"],
        "value": "Hello, {{ subject }}!",
    }
    definition.update(overrides)
    return _write_yaml(tmp_path, definition)


class TestPromptTemplateInitialization:
    def test_requires_path_keyword(self, tmp_path: Path) -> None:
        constructor = cast("Callable[..., PromptTemplate]", PromptTemplate)

        with pytest.raises(TypeError):
            constructor(_write_template(tmp_path))

    def test_rejects_component_construction(self) -> None:
        constructor = cast("Callable[..., PromptTemplate]", PromptTemplate)

        with pytest.raises(TypeError):
            constructor(
                name="Greeting",
                description=None,
                parameter_keys=("subject",),
                _template=Template("Hello, {{ subject }}!"),
            )

    @pytest.mark.parametrize(
        "attribute",
        ["name", "description", "parameter_keys"],
    )
    def test_metadata_properties_are_read_only(
        self,
        tmp_path: Path,
        attribute: str,
    ) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        with pytest.raises(AttributeError):
            setattr(template, attribute, "changed")

    def test_prevents_unknown_attributes(self, tmp_path: Path) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        assert not hasattr(template, "__dict__")

    def test_uses_identity_equality_and_hashing(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path)

        first = PromptTemplate(path=path)
        second = PromptTemplate(path=path)

        assert first != second
        assert len({first, second}) == 2

    def test_representation_contains_only_public_metadata(
        self,
        tmp_path: Path,
    ) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        assert repr(template) == (
            "PromptTemplate(name='Greeting', description=None, "
            "parameter_keys=('subject',))"
        )

    def test_loads_raw_yaml_block_scalars(self, tmp_path: Path) -> None:
        path = _write_raw_yaml(
            tmp_path,
            (
                "name: Greeting\n"
                "description: |\n"
                "  Greets a subject across\n"
                "  multiple lines.\n"
                "parameters:\n"
                "  - subject\n"
                "value: |\n"
                "  Hello, {{ subject }}!\n"
                "  Welcome to RAMPART.\n"
            ),
        )

        template = PromptTemplate(path=path)

        assert template.name == "Greeting"
        assert template.description == "Greets a subject across\nmultiple lines.\n"
        assert template.parameter_keys == ("subject",)
        assert template.render(subject="Ada") == "Hello, Ada!\nWelcome to RAMPART."

    def test_rejects_malformed_raw_yaml(self, tmp_path: Path) -> None:
        path = _write_raw_yaml(
            tmp_path,
            """\
            name: Broken
            parameters:
              - subject
            value: "{{ subject }}"
            description: [unterminated
            """,
        )

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(path=path)

        assert isinstance(exc_info.value.__cause__, yaml.YAMLError)

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("", id="empty"),
            pytest.param("- name\n- parameters\n- value\n", id="sequence"),
        ],
    )
    def test_rejects_raw_yaml_without_mapping(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        path = _write_raw_yaml(tmp_path, content)

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(path=path)

        assert exc_info.value.path == path
        assert exc_info.value.__cause__ is not None

    def test_loads_metadata_and_renders_successfully(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, description="Greets a subject.")

        template = PromptTemplate(path=path)

        assert isinstance(template, PromptTemplate)
        assert template.name == "Greeting"
        assert template.description == "Greets a subject."
        assert template.parameter_keys == ("subject",)
        assert template.render(subject="Ada") == "Hello, Ada!"

    def test_optional_description_defaults_to_none(self, tmp_path: Path) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        assert template.description is None

    def test_rejects_missing_parameter(self, tmp_path: Path) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        with pytest.raises(TemplateParameterError) as exc_info:
            template.render()

        assert exc_info.value.template_name == "Greeting"
        assert exc_info.value.missing == ("subject",)
        assert exc_info.value.unexpected == ()

    def test_rejects_unexpected_parameter(self, tmp_path: Path) -> None:
        template = PromptTemplate(path=_write_template(tmp_path))

        with pytest.raises(TemplateParameterError) as exc_info:
            template.render(subject="Ada", subejct="typo")

        assert exc_info.value.missing == ()
        assert exc_info.value.unexpected == ("subejct",)

    def test_rejects_parameter_declaration_drift(self, tmp_path: Path) -> None:
        path = _write_template(
            tmp_path,
            parameters=["declared_but_unused"],
        )

        with pytest.raises(
            PromptTemplateDefinitionError,
            match=r"missing=\('subject',\), unused=\('declared_but_unused',\)",
        ):
            PromptTemplate(path=path)

    def test_wraps_invalid_jinja_syntax(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, value="{{ subject")

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(path=path)

        assert isinstance(exc_info.value.__cause__, TemplateError)

    def test_wraps_invalid_utf8(self, tmp_path: Path) -> None:
        path = tmp_path / "prompt.yaml"
        path.write_bytes(b"\xff")

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(path=path)

        assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)

    def test_preserves_missing_file_error(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.yaml"

        with pytest.raises(FileNotFoundError):
            PromptTemplate(path=path)

    @pytest.mark.parametrize(
        ("definition", "error_fragment"),
        [
            (
                {"name": "Greeting", "value": "Hello!"},
                "parameters",
            ),
            (
                {
                    "name": 42,
                    "parameters": ["subject"],
                    "value": "Hello, {{ subject }}!",
                },
                "name",
            ),
            (
                {
                    "name": "Greeting",
                    "parameters": ["subject"],
                    "value": "Hello, {{ subject }}!",
                    "unexpected": True,
                },
                "unexpected",
            ),
            (
                {
                    "name": "Greeting",
                    "parameters": ["subject", "subject"],
                    "value": "Hello, {{ subject }}!",
                },
                "items must be unique",
            ),
        ],
    )
    def test_rejects_invalid_yaml_schema(
        self,
        tmp_path: Path,
        definition: object,
        error_fragment: str,
    ) -> None:
        path = _write_yaml(tmp_path, definition)

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(path=path)

        assert exc_info.value.path == path
        assert error_fragment in str(exc_info.value)
        assert exc_info.value.__cause__ is not None
