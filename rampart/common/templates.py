# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""YAML prompt-template loader shared by drivers and evaluators.

RAMPART keeps prompt text in YAML files under per-package ``prompts/``
directories. Each file uses this schema:

- ``name`` (required): Human-readable template name.
- ``parameters`` (required): Exact keyword names accepted by ``render()``.
- ``value`` (required): Jinja2 template source.
- ``description`` (optional): Human-readable purpose; defaults to ``None``.

The loader maps ``parameters`` to :attr:`PromptTemplate.parameter_keys`,
compiles ``value``, and returns a structured template that validates every
render call before evaluating Jinja markup.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import yaml
from jinja2 import Environment, StrictUndefined, Template, meta, select_autoescape

if TYPE_CHECKING:
    from pathlib import Path


_JINJA_ENVIRONMENT = Environment(
    autoescape=select_autoescape(default_for_string=False, default=False),
    undefined=StrictUndefined,
)


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
        KeyError: If a required YAML key is absent.
        TypeError: If a YAML field has the wrong type.
        ValueError: If parameter declarations are duplicated or do not match
            the Jinja template variables.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, Mapping):
        msg = f"Prompt template {path} must contain a YAML mapping."
        raise TypeError(msg)

    name = _required_string(data, "name", path=path)
    value = _required_string(data, "value", path=path)
    description = data.get("description")
    if description is not None and not isinstance(description, str):
        msg = f"Prompt template {path} field 'description' must be a string or null."
        raise TypeError(msg)

    if "parameters" not in data:
        msg = f"Prompt template {path} is missing required field 'parameters'."
        raise KeyError(msg)
    raw_parameter_keys = data["parameters"]
    if not isinstance(raw_parameter_keys, list) or not all(
        isinstance(key, str) for key in raw_parameter_keys
    ):
        msg = f"Prompt template {path} field 'parameters' must be a list of strings."
        raise TypeError(msg)
    parameter_keys = tuple(raw_parameter_keys)
    if len(parameter_keys) != len(set(parameter_keys)):
        msg = f"Prompt template {path} field 'parameters' contains duplicate keys."
        raise ValueError(msg)

    parsed = _JINJA_ENVIRONMENT.parse(value, name=name, filename=str(path))
    referenced_keys = meta.find_undeclared_variables(parsed)
    declared_keys = set(parameter_keys)
    if referenced_keys != declared_keys:
        missing = tuple(sorted(referenced_keys - declared_keys))
        unused = tuple(sorted(declared_keys - referenced_keys))
        msg = (
            f"Prompt template {name!r} parameter declarations do not match its "
            f"Jinja variables: missing={missing!r}, unused={unused!r}"
        )
        raise ValueError(msg)

    return PromptTemplate(
        name=name,
        description=description,
        parameter_keys=parameter_keys,
        _template=_JINJA_ENVIRONMENT.from_string(parsed),
    )


def _required_string(
    data: Mapping[object, object],
    key: str,
    *,
    path: Path,
) -> str:
    """Return a required string field from parsed YAML data.

    Raises:
        KeyError: If *key* is absent.
        TypeError: If the field value is not a string.
    """
    if key not in data:
        msg = f"Prompt template {path} is missing required field {key!r}."
        raise KeyError(msg)
    value = data[key]
    if not isinstance(value, str):
        msg = f"Prompt template {path} field {key!r} must be a string."
        raise TypeError(msg)
    return value
