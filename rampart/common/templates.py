# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Source-neutral prompt-template definition, compilation, and YAML loading.

``PromptTemplate`` accepts only a validated ``PromptTemplateDefinition`` and
compiles its Jinja source internally. ``PromptTemplate.from_yaml`` is the
filesystem and YAML adapter used by RAMPART's built-in drivers and evaluators.
Every render call must provide exactly the definition's declared parameters.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import TYPE_CHECKING, Annotated, TypeAlias, TypeVar, final

import yaml
from jinja2 import (
    Environment,
    StrictUndefined,
    Template,
    TemplateError,
    TemplateSyntaxError,
    meta,
    select_autoescape,
)
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
)

__all__ = [
    "PromptTemplate",
    "PromptTemplateDefinition",
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
    """Raised when data does not define a valid prompt template."""

    def __init__(
        self,
        *,
        details: str,
        template_name: str | None = None,
        template_line: int | None = None,
        path: Path | None = None,
    ) -> None:
        """Initialize an invalid-definition error.

        Args:
            details: Human-readable failure details.
            template_name: Human-readable template name, when available.
            template_line: Line within the template value, when available.
            path: Path from which the definition was loaded, when applicable.
        """
        self.path = path
        self.details = details
        self.template_name = template_name
        self.template_line = template_line
        super().__init__(self._format_message())

    def add_path(self, path: Path) -> None:
        """Add adapter context while preserving this exception instance.

        Args:
            path: Path from which the invalid definition was loaded.
        """
        self.path = path
        self.args = (self._format_message(),)

    def _format_message(self) -> str:
        """Format the error from its structured fields.

        Returns:
            str: Human-readable error message.
        """
        if self.template_name is not None:
            subject = f"Prompt template {self.template_name!r}"
            if self.path is not None:
                subject += f" loaded from {self.path}"
        elif self.path is not None:
            subject = f"Prompt template {self.path}"
        else:
            subject = "Prompt template"

        location = ""
        if self.template_line is not None:
            location = f" (template value line {self.template_line})"
        return f"{subject} is invalid{location}:\n{self.details}"


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


@final
class PromptTemplate:
    """Compiled prompt template with metadata and an explicit render contract."""

    __slots__ = ("_description", "_name", "_parameter_keys", "_template")

    def __init__(self, *, definition: PromptTemplateDefinition) -> None:
        """Compile a validated prompt template definition.

        Args:
            definition: Source-neutral prompt template definition.
        """
        template = _compile_template(definition)

        self._name = definition.name
        self._description = definition.description
        self._parameter_keys = definition.parameters
        self._template = template

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
        try:
            return cls(definition=definition)
        except PromptTemplateDefinitionError as exc:
            exc.add_path(path)
            raise

    @property
    def name(self) -> str:
        """Human-readable template name."""
        return self._name

    @property
    def description(self) -> str | None:
        """Human-readable template purpose, when provided."""
        return self._description

    @property
    def parameter_keys(self) -> tuple[str, ...]:
        """Keyword names accepted by :meth:`render`."""
        return self._parameter_keys

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

    def __repr__(self) -> str:
        """Return a representation containing only public metadata."""
        return (
            f"PromptTemplate(name={self.name!r}, "
            f"description={self.description!r}, "
            f"parameter_keys={self.parameter_keys!r})"
        )


_UniqueItemT = TypeVar("_UniqueItemT", bound=Hashable)


def _convert_list_to_tuple(values: object) -> object:
    """Convert a serialized list to its immutable domain representation.

    Args:
        values: Raw value to normalize.

    Returns:
        object: A tuple for list input; otherwise the original value.
    """
    if isinstance(values, list):
        return tuple(values)
    return values


def _require_unique(
    values: tuple[_UniqueItemT, ...],
) -> tuple[_UniqueItemT, ...]:
    """Reject duplicate values.

    Args:
        values: Values to validate.

    Returns:
        tuple[_UniqueItemT, ...]: The validated values in their original order.

    Raises:
        ValueError: If any value appears more than once.
    """
    if len(values) != len(set(values)):
        msg = "items must be unique"
        raise ValueError(msg)
    return values


_UniqueTuple: TypeAlias = Annotated[
    tuple[_UniqueItemT, ...],
    BeforeValidator(_convert_list_to_tuple),
    AfterValidator(_require_unique),
]


class PromptTemplateDefinition(BaseModel):
    """Strict, source-neutral definition of a prompt template.

    Attributes:
        name: Human-readable template name.
        parameters: Ordered, unique keyword names accepted by ``render()``.
        value: Jinja template source, omitted from the representation.
        description: Human-readable purpose, when provided.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        strict=True,
    )

    name: str
    parameters: _UniqueTuple[str]
    value: str = Field(repr=False)
    description: str | None = None


def _load_yaml_definition(path: Path) -> PromptTemplateDefinition:
    """Load and validate the serialized YAML representation.

    Args:
        path: Path to the YAML template file.

    Returns:
        PromptTemplateDefinition: The validated template definition.

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
        return PromptTemplateDefinition.model_validate(data)
    except ValidationError as exc:
        raise PromptTemplateDefinitionError(path=path, details=str(exc)) from exc


def _compile_template(
    definition: PromptTemplateDefinition,
) -> Template:
    """Compile a validated definition after checking its parameter contract.

    Args:
        definition: Validated source-neutral template definition.

    Returns:
        Template: The compiled Jinja template.

    Raises:
        PromptTemplateDefinitionError: If the Jinja template is invalid or
            declared parameters do not match its variables.
    """
    try:
        parsed = _JINJA_ENVIRONMENT.parse(definition.value)
        referenced_keys = meta.find_undeclared_variables(parsed)
    except TemplateSyntaxError as exc:
        raise PromptTemplateDefinitionError(
            details=exc.message or str(exc),
            template_name=definition.name,
            template_line=exc.lineno,
        ) from exc
    except TemplateError as exc:
        raise PromptTemplateDefinitionError(
            details=str(exc),
            template_name=definition.name,
        ) from exc

    declared_keys = set(definition.parameters)
    if referenced_keys != declared_keys:
        missing = tuple(sorted(referenced_keys - declared_keys))
        unused = tuple(sorted(declared_keys - referenced_keys))
        details = (
            "parameters do not match Jinja variables: "
            f"missing={missing!r}, unused={unused!r}"
        )
        raise PromptTemplateDefinitionError(
            details=details,
            template_name=definition.name,
        )

    try:
        return _JINJA_ENVIRONMENT.from_string(parsed)
    except TemplateSyntaxError as exc:
        raise PromptTemplateDefinitionError(
            details=exc.message or str(exc),
            template_name=definition.name,
            template_line=exc.lineno,
        ) from exc
    except TemplateError as exc:
        raise PromptTemplateDefinitionError(
            details=str(exc),
            template_name=definition.name,
        ) from exc
