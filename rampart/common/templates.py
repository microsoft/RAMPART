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

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, TypeAlias, TypeVar

import yaml
from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateError,
    meta,
    select_autoescape,
)
from pydantic import AfterValidator, BaseModel, ConfigDict, ValidationError

__all__ = [
    "PromptTemplate",
    "PromptTemplateDefinitionError",
    "TemplateParameterError",
]

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path
    from typing import Self


_JINJA_ENVIRONMENT = Environment(
    autoescape=select_autoescape(default_for_string=False, default=False),
    undefined=StrictUndefined,
)


class PromptTemplateDefinitionError(ValueError):
    """Raised when file contents do not define a valid prompt template."""

    def __init__(self, *, path: Path, details: str) -> None:
        """Initialize an invalid-definition error.

        Args:
            path: Path to the invalid YAML template.
            details: Human-readable failure details.
        """
        self.path = path
        msg = f"Prompt template {path} is invalid:\n{details}"
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


@dataclass(frozen=True, kw_only=True, slots=True)
class PromptTemplate:
    """Compiled prompt template with metadata and an explicit render contract."""

    name: str
    description: str | None
    parameter_keys: tuple[str, ...]
    _template: Template = field(repr=False, compare=False)

    @classmethod
    def from_yaml(cls, path: Path) -> Self:
        """Load and compile a prompt template from YAML.

        ``name``, ``parameters``, and ``value`` are required. ``description``
        is optional. Declared parameters must exactly match the variables
        referenced by the Jinja template.

        Args:
            path: Path to the YAML template file.

        Returns:
            Self: A structured, compiled prompt template.

        Raises:
            FileNotFoundError: If *path* does not exist.
            PromptTemplateDefinitionError: If the file contents do not define
                a valid prompt template.
        """
        definition = _load_yaml_definition(path)
        return cls(
            name=definition.name,
            description=definition.description,
            parameter_keys=tuple(definition.parameters),
            _template=_compile_template(definition, path=path),
        )

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


_UniqueItemT = TypeVar("_UniqueItemT", bound=Hashable)


def _require_unique(values: list[_UniqueItemT]) -> list[_UniqueItemT]:
    """Reject duplicate values.

    Args:
        values: Values to validate.

    Returns:
        list[_UniqueItemT]: The validated values in their original order.

    Raises:
        ValueError: If any value appears more than once.
    """
    if len(values) != len(set(values)):
        msg = "items must be unique"
        raise ValueError(msg)
    return values


_UniqueList: TypeAlias = Annotated[
    list[_UniqueItemT],
    AfterValidator(_require_unique),
]


class _PromptTemplateYaml(BaseModel):
    """Strict schema for the serialized YAML representation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )

    name: str
    parameters: _UniqueList[str]
    value: str
    description: str | None = None


def _load_yaml_definition(path: Path) -> _PromptTemplateYaml:
    """Load and validate the serialized YAML representation.

    Args:
        path: Path to the YAML template file.

    Returns:
        _PromptTemplateYaml: The validated YAML definition.

    Raises:
        FileNotFoundError: If *path* does not exist.
        PromptTemplateDefinitionError: If the file is not valid UTF-8 or YAML,
            or if its data does not match the template schema.
    """
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (UnicodeError, yaml.YAMLError) as exc:
        raise PromptTemplateDefinitionError(path=path, details=str(exc)) from exc

    try:
        return _PromptTemplateYaml.model_validate(data)
    except ValidationError as exc:
        raise PromptTemplateDefinitionError(path=path, details=str(exc)) from exc


def _compile_template(
    definition: _PromptTemplateYaml,
    *,
    path: Path,
) -> Template:
    """Compile a validated definition after checking its parameter contract.

    Args:
        definition: Validated YAML template definition.
        path: Source path used in Jinja diagnostics.

    Returns:
        Template: The compiled Jinja template.

    Raises:
        PromptTemplateDefinitionError: If the Jinja template is invalid or
            declared parameters do not match its variables.
    """
    try:
        parsed = _JINJA_ENVIRONMENT.parse(
            definition.value,
            name=definition.name,
            filename=str(path),
        )
        referenced_keys = meta.find_undeclared_variables(parsed)
    except TemplateError as exc:
        raise PromptTemplateDefinitionError(path=path, details=str(exc)) from exc

    declared_keys = set(definition.parameters)
    if referenced_keys != declared_keys:
        missing = tuple(sorted(referenced_keys - declared_keys))
        unused = tuple(sorted(declared_keys - referenced_keys))
        msg = (
            f"Prompt template {definition.name!r} parameters do not match its "
            f"Jinja variables: missing={missing!r}, unused={unused!r}"
        )
        raise PromptTemplateDefinitionError(path=path, details=msg)

    try:
        return _JINJA_ENVIRONMENT.from_string(parsed)
    except TemplateError as exc:
        raise PromptTemplateDefinitionError(path=path, details=str(exc)) from exc
