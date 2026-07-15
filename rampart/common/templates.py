# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""YAML prompt-template loader shared by drivers and evaluators.

RAMPART keeps prompt text in YAML files under per-package ``prompts/``
directories. Each file uses this schema:

- ``name`` (required): Human-readable template name.
- ``parameters`` (required): Exact keyword names accepted by ``render()``.
- ``value`` (required): Jinja2 template source.
- ``description`` (optional): Human-readable purpose; defaults to ``None``.

Unknown keys and type coercion are rejected. Parameter names must be unique.
The loader maps ``parameters`` to :attr:`PromptTemplate.parameter_keys`,
compiles ``value``, and returns a structured template that validates every
render call before evaluating Jinja markup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml
from jinja2 import Environment, StrictUndefined, Template, meta, select_autoescape
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path


_JINJA_ENVIRONMENT = Environment(
    autoescape=select_autoescape(default_for_string=False, default=False),
    undefined=StrictUndefined,
)


class _PromptTemplateYaml(BaseModel):
    """Strict schema for the serialized YAML representation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )

    name: str
    parameters: list[str]
    value: str
    description: str | None = None

    @field_validator("parameters")
    @classmethod
    def _require_unique_parameters(cls, parameters: list[str]) -> list[str]:
        """Reject duplicate parameter declarations.

        Args:
            parameters: Parameter keys parsed from YAML.

        Returns:
            list[str]: The validated parameter keys.

        Raises:
            ValueError: If a parameter key appears more than once.
        """
        if len(parameters) != len(set(parameters)):
            msg = "parameters must contain unique keys"
            raise ValueError(msg)
        return parameters


class PromptTemplateSchemaError(ValueError):
    """Raised when YAML data does not match the prompt-template schema."""

    def __init__(self, *, path: Path, details: str) -> None:
        """Initialize an error without exposing Pydantic in the public contract.

        Args:
            path: Path to the invalid YAML template.
            details: Human-readable validation details.
        """
        self.path = path
        msg = f"Prompt template {path} has an invalid YAML schema:\n{details}"
        super().__init__(msg)


class TemplateParameterError(ValueError):
    """Raised when render arguments do not match a template's declared keys."""

    def __init__(
        self,
        *,
        template_name: str,
        missing: Collection[str],
        unexpected: Collection[str],
    ) -> None:
        """Initialize a deterministic parameter-mismatch error.

        Args:
            template_name: Human-readable name of the template.
            missing: Declared keys absent from the render call.
            unexpected: Render keys not declared by the template.
        """
        self.template_name = template_name
        self.missing = tuple(sorted(missing))
        self.unexpected = tuple(sorted(unexpected))

        details = []
        if self.missing:
            details.append(f"missing={self.missing!r}")
        if self.unexpected:
            details.append(f"unexpected={self.unexpected!r}")
        joined_details = ", ".join(details)
        msg = f"Prompt template {template_name!r} parameter mismatch: {joined_details}"
        super().__init__(msg)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """Compiled prompt template with metadata and an explicit render contract."""

    name: str
    description: str | None
    parameter_keys: tuple[str, ...]
    _template: Template = field(repr=False, compare=False)

    def render(self, **kwargs: object) -> str:
        """Render with exactly the declared keyword arguments.

        Args:
            **kwargs: Values keyed by :attr:`parameter_keys`.

        Returns:
            str: The rendered prompt text.

        Raises:
            TemplateParameterError: If any declared key is missing or any
                undeclared key is provided.
        """
        expected = frozenset(self.parameter_keys)
        provided = frozenset(kwargs)
        missing = expected - provided
        unexpected = provided - expected
        if missing or unexpected:
            raise TemplateParameterError(
                template_name=self.name,
                missing=missing,
                unexpected=unexpected,
            )
        return self._template.render(**kwargs)


def load_prompt_template(path: Path) -> PromptTemplate:
    """Load and compile a structured YAML prompt template.

    ``name``, ``parameters``, and ``value`` are required. ``description``
    is optional. The declared parameters must exactly match the variables
    referenced by the Jinja template.

    Args:
        path: Absolute path to the YAML template file
            (e.g. ``.../prompts/llm_judge.yaml``).

    Returns:
        PromptTemplate: Structured metadata and a compiled template.

    Raises:
        FileNotFoundError: If *path* does not exist.
        PromptTemplateSchemaError: If the YAML data does not match the schema,
            including duplicate parameter declarations.
        ValueError: If parameter declarations do not match the Jinja template
            variables.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    try:
        definition = _PromptTemplateYaml.model_validate(data)
    except ValidationError as exc:
        raise PromptTemplateSchemaError(path=path, details=str(exc)) from exc

    parameter_keys = tuple(definition.parameters)
    parsed = _JINJA_ENVIRONMENT.parse(
        definition.value,
        name=definition.name,
        filename=str(path),
    )
    referenced_keys = meta.find_undeclared_variables(parsed)
    declared_keys = set(parameter_keys)
    if referenced_keys != declared_keys:
        missing = tuple(sorted(referenced_keys - declared_keys))
        unused = tuple(sorted(declared_keys - referenced_keys))
        msg = (
            f"Prompt template {definition.name!r} parameter declarations do not match "
            "its "
            f"Jinja variables: missing={missing!r}, unused={unused!r}"
        )
        raise ValueError(msg)

    return PromptTemplate(
        name=definition.name,
        description=definition.description,
        parameter_keys=parameter_keys,
        _template=_JINJA_ENVIRONMENT.from_string(parsed),
    )
