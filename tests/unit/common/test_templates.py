# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from pathlib import Path

import pytest
import yaml

from rampart.common.templates import (
    PromptTemplate,
    TemplateParameterError,
    load_prompt_template,
)


def _write_template(tmp_path: Path, **overrides: object) -> Path:
    data: dict[str, object] = {
        "name": "Greeting",
        "parameters": ["subject"],
        "value": "Hello, {{ subject }}!",
    }
    data.update(overrides)
    path = tmp_path / "prompt.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class TestLoadPromptTemplate:
    def test_loads_metadata_and_renders_successfully(self, tmp_path: Path) -> None:
        path = _write_template(tmp_path, description="Greets a subject.")

        template = load_prompt_template(path)

        assert isinstance(template, PromptTemplate)
        assert template.name == "Greeting"
        assert template.description == "Greets a subject."
        assert template.parameter_keys == ("subject",)
        assert template.render(subject="Ada") == "Hello, Ada!"

    def test_optional_description_defaults_to_none(self, tmp_path: Path) -> None:
        template = load_prompt_template(_write_template(tmp_path))

        assert template.description is None

    def test_rejects_missing_parameter(self, tmp_path: Path) -> None:
        template = load_prompt_template(_write_template(tmp_path))

        with pytest.raises(TemplateParameterError) as exc_info:
            template.render()

        assert exc_info.value.template_name == "Greeting"
        assert exc_info.value.missing == ("subject",)
        assert exc_info.value.unexpected == ()

    def test_rejects_unexpected_parameter(self, tmp_path: Path) -> None:
        template = load_prompt_template(_write_template(tmp_path))

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
            ValueError,
            match=r"missing=\('subject',\), unused=\('declared_but_unused',\)",
        ):
            load_prompt_template(path)
