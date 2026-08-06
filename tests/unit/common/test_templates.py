# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from jinja2 import TemplateSyntaxError
from pydantic import ValidationError

from rampart.common.templates import (
    PromptTemplate,
    PromptTemplateDefinition,
    PromptTemplateDefinitionError,
    TemplateParameterError,
)


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


class TestPromptTemplateConstruction:
    def test_constructs_and_renders_from_definition(self) -> None:
        definition = PromptTemplateDefinition(
            name="Greeting",
            parameters=("subject",),
            value="Hello, {{ subject }}!",
            description="Greets a subject.",
        )

        template = PromptTemplate(definition=definition)

        assert template.name == "Greeting"
        assert template.description == "Greets a subject."
        assert template.parameter_keys == ("subject",)
        assert template.render(subject="Ada") == "Hello, Ada!"

    def test_reports_structured_jinja_syntax_error(self) -> None:
        definition = PromptTemplateDefinition(
            name="Broken",
            parameters=(),
            value="first template line\n{{ broken",
        )

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(definition=definition)

        assert exc_info.value.template_name == "Broken"
        assert exc_info.value.template_line == 2
        assert exc_info.value.path is None
        assert str(exc_info.value) == (
            "Prompt template 'Broken' is invalid (template value line 2):\n"
            f"{exc_info.value.details}"
        )
        assert isinstance(exc_info.value.__cause__, TemplateSyntaxError)

    def test_uses_definition_name_for_introspection_error(self) -> None:
        definition = PromptTemplateDefinition(
            name="Duplicate blocks",
            parameters=(),
            value=(
                "{% block repeated %}{% endblock %}\n{% block repeated %}{% endblock %}"
            ),
        )

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate(definition=definition)

        assert exc_info.value.template_name == "Duplicate blocks"
        assert "<introspection>" not in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, TemplateSyntaxError)

    def test_rejects_parameter_declaration_drift(self) -> None:
        definition = PromptTemplateDefinition(
            name="Drifted",
            parameters=("declared_but_unused",),
            value="{{ referenced_but_missing }}",
        )

        with pytest.raises(
            PromptTemplateDefinitionError,
            match=(
                r"missing=\('referenced_but_missing',\), "
                r"unused=\('declared_but_unused',\)"
            ),
        ) as exc_info:
            PromptTemplate(definition=definition)

        assert str(exc_info.value) == (
            f"Prompt template 'Drifted' is invalid:\n{exc_info.value.details}"
        )

    def test_does_not_enable_autoescape_from_definition_name(self) -> None:
        definition = PromptTemplateDefinition(
            name="summary.html",
            parameters=("markup",),
            value="{{ markup }}",
        )

        template = PromptTemplate(definition=definition)

        assert template.render(markup="<b>") == "<b>"

    @pytest.mark.parametrize(
        "attribute",
        ["name", "description", "parameter_keys"],
    )
    def test_metadata_properties_are_read_only(self, attribute: str) -> None:
        template = PromptTemplate(
            definition=PromptTemplateDefinition(
                name="Greeting",
                parameters=("subject",),
                value="Hello, {{ subject }}!",
            ),
        )

        with pytest.raises(AttributeError):
            setattr(template, attribute, "changed")

    def test_prevents_unknown_attributes(self) -> None:
        template = PromptTemplate(
            definition=PromptTemplateDefinition(
                name="Greeting",
                parameters=(),
                value="Hello!",
            ),
        )

        assert not hasattr(template, "__dict__")

    def test_uses_identity_equality_and_hashing(self) -> None:
        definition = PromptTemplateDefinition(
            name="Greeting",
            parameters=(),
            value="Hello!",
        )

        first = PromptTemplate(definition=definition)
        second = PromptTemplate(definition=definition)

        assert first != second
        assert len({first, second}) == 2

    def test_representation_contains_only_public_metadata(self) -> None:
        template = PromptTemplate(
            definition=PromptTemplateDefinition(
                name="Greeting",
                parameters=("subject",),
                value="Hidden prompt: {{ subject }}",
            ),
        )

        assert repr(template) == (
            "PromptTemplate(name='Greeting', description=None, "
            "parameter_keys=('subject',))"
        )
        assert "Hidden prompt" not in repr(template)


class TestPromptTemplateDefinition:
    def test_normalizes_parameters_to_immutable_tuple(self) -> None:
        definition = PromptTemplateDefinition.model_validate(
            {
                "name": "Greeting",
                "parameters": ["subject"],
                "value": "Hello, {{ subject }}!",
            },
        )

        assert definition.parameters == ("subject",)
        assert not hasattr(definition.parameters, "append")

    def test_rejects_unordered_parameter_collection(self) -> None:
        with pytest.raises(ValidationError):
            PromptTemplateDefinition.model_validate(
                {
                    "name": "Greeting",
                    "parameters": {"subject"},
                    "value": "Hello, {{ subject }}!",
                },
            )

    def test_rejects_duplicate_parameters(self) -> None:
        with pytest.raises(ValidationError, match="items must be unique"):
            PromptTemplateDefinition.model_validate(
                {
                    "name": "Greeting",
                    "parameters": ["subject", "subject"],
                    "value": "Hello, {{ subject }}!",
                },
            )

    def test_is_hashable_without_exposing_prompt_in_repr(self) -> None:
        definition = PromptTemplateDefinition(
            name="Greeting",
            parameters=("subject",),
            value="Hidden prompt: {{ subject }}",
        )

        assert hash(definition)
        assert "Hidden prompt" not in repr(definition)

    def test_serializes_parameters_as_yaml_sequence(self) -> None:
        definition = PromptTemplateDefinition(
            name="Greeting",
            parameters=("subject",),
            value="Hello, {{ subject }}!",
        )

        serialized = yaml.safe_load(yaml.safe_dump(definition.model_dump()))

        assert serialized["parameters"] == ["subject"]


class TestPromptTemplateFromYaml:
    def test_matches_in_memory_construction(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, description="Greets a subject.")
        definition = PromptTemplateDefinition(
            name="Greeting",
            parameters=("subject",),
            value="Hello, {{ subject }}!",
            description="Greets a subject.",
        )

        loaded = PromptTemplate.from_yaml(path)
        in_memory = PromptTemplate(definition=definition)

        assert loaded.name == in_memory.name
        assert loaded.description == in_memory.description
        assert loaded.parameter_keys == in_memory.parameter_keys
        assert loaded.render(subject="Ada") == in_memory.render(subject="Ada")

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

        template = PromptTemplate.from_yaml(path)

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
            PromptTemplate.from_yaml(path)

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
            PromptTemplate.from_yaml(path)

        assert exc_info.value.path == path
        assert exc_info.value.__cause__ is not None
        assert str(exc_info.value) == (
            f"Prompt template {path} is invalid:\n{exc_info.value.details}"
        )

    def test_loads_metadata_and_renders_successfully(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, description="Greets a subject.")

        template = PromptTemplate.from_yaml(path)

        assert isinstance(template, PromptTemplate)
        assert template.name == "Greeting"
        assert template.description == "Greets a subject."
        assert template.parameter_keys == ("subject",)
        assert template.render(subject="Ada") == "Hello, Ada!"

    def test_optional_description_defaults_to_none(self, tmp_path: Path) -> None:
        template = PromptTemplate.from_yaml(_write_template(tmp_path))

        assert template.description is None

    def test_rejects_missing_parameter(self, tmp_path: Path) -> None:
        template = PromptTemplate.from_yaml(_write_template(tmp_path))

        with pytest.raises(TemplateParameterError) as exc_info:
            template.render()

        assert exc_info.value.template_name == "Greeting"
        assert exc_info.value.missing == ("subject",)
        assert exc_info.value.unexpected == ()

    def test_rejects_unexpected_parameter(self, tmp_path: Path) -> None:
        template = PromptTemplate.from_yaml(_write_template(tmp_path))

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
            PromptTemplate.from_yaml(path)

    def test_wraps_invalid_jinja_syntax(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, value="{{ subject")

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate.from_yaml(path)

        assert isinstance(exc_info.value.__cause__, TemplateSyntaxError)

    def test_labels_jinja_line_as_template_value_line(self, tmp_path: Path) -> None:
        path = _write_raw_yaml(
            tmp_path,
            (
                "name: Broken\n"
                "parameters: []\n"
                "description: Demonstrates line mapping\n"
                "value: |\n"
                "  first template line\n"
                "  {{ broken\n"
            ),
        )
        physical_line = next(
            line_number
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            )
            if "{{ broken" in line
        )

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate.from_yaml(path)

        assert physical_line == 6
        assert exc_info.value.template_line == 2
        assert exc_info.value.path == path
        assert str(exc_info.value) == (
            f"Prompt template 'Broken' loaded from {path} is invalid "
            f"(template value line 2):\n{exc_info.value.details}"
        )
        assert exc_info.value.args == (str(exc_info.value),)
        assert isinstance(exc_info.value.__cause__, TemplateSyntaxError)

    def test_wraps_invalid_utf8(self, tmp_path: Path) -> None:
        path = tmp_path / "prompt.yaml"
        path.write_bytes(b"\xff")

        with pytest.raises(PromptTemplateDefinitionError) as exc_info:
            PromptTemplate.from_yaml(path)

        assert isinstance(exc_info.value.__cause__, UnicodeDecodeError)

    def test_preserves_missing_file_error(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.yaml"

        with pytest.raises(FileNotFoundError):
            PromptTemplate.from_yaml(path)

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
            PromptTemplate.from_yaml(path)

        assert exc_info.value.path == path
        assert error_fragment in str(exc_info.value)
        assert exc_info.value.__cause__ is not None
