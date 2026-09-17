# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Adapter-local policies for the canonical dataclass trace schema."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from operator import attrgetter
from typing import TYPE_CHECKING

from pydantic_core import core_schema

from rampart.core.types import Payload, PayloadFormat

if TYPE_CHECKING:
    from pydantic import (
        GetCoreSchemaHandler,
        ValidationError,
        ValidationInfo,
    )


# Pydantic supplies source/handler positionally to schema hooks.
def trace_schema(
    source: object, handler: GetCoreSchemaHandler
) -> core_schema.CoreSchema:
    """Apply canonical policies to an adapter's schema, not its live classes.

    Returns:
        CoreSchema: A configured copy of the generated dataclass schema.
    """
    return _trace_schema(schema=handler(source), handler=handler, references=set())


def _trace_schema(
    *,
    schema: core_schema.CoreSchema,
    handler: GetCoreSchemaHandler,
    references: set[str],
) -> core_schema.CoreSchema:
    """Copy generated schema nodes while applying shared trace rules.

    Returns:
        CoreSchema: The adapter-local schema, preserving definition references.
    """
    if schema["type"] == "definition-ref":
        reference = schema["schema_ref"]
        if reference in references:
            return schema
        references.add(reference)
        return _trace_schema(
            schema=handler.resolve_ref_schema(schema),
            handler=handler,
            references=references,
        )

    schema = schema.copy()
    if schema["type"] == "dataclass":
        return _trace_dataclass(schema=schema, handler=handler, references=references)
    if schema["type"] == "default" or schema["type"] == "nullable":
        schema["schema"] = _trace_schema(
            schema=schema["schema"], handler=handler, references=references
        )
    elif schema["type"] == "dataclass-args":
        schema["fields"] = [
            {
                **field,
                "schema": _trace_schema(
                    schema=field["schema"], handler=handler, references=references
                ),
            }
            for field in schema["fields"]
        ]
    elif schema["type"] == "list":
        schema["items_schema"] = _trace_schema(
            schema=schema["items_schema"], handler=handler, references=references
        )
    elif schema["type"] == "union":
        schema["choices"] = [
            (
                _trace_schema(schema=choice[0], handler=handler, references=references),
                choice[1],
            )
            if isinstance(choice, tuple)
            else _trace_schema(schema=choice, handler=handler, references=references)
            for choice in schema["choices"]
        ]
    elif schema["type"] == "dict":
        return core_schema.no_info_before_validator_function(json_value, schema)

    return _trace_scalar(schema)


def _trace_scalar(schema: core_schema.CoreSchema) -> core_schema.CoreSchema:
    """Apply wire representations to copied enum and datetime schema nodes.

    Returns:
        CoreSchema: The schema with scalar serialization policies applied.
    """
    if schema["type"] == "enum":
        schema["serialization"] = core_schema.plain_serializer_function_ser_schema(
            attrgetter("value")
        )
    elif schema["type"] == "datetime":
        return core_schema.with_info_before_validator_function(
            _iso_datetime,
            schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                datetime.isoformat, return_schema=core_schema.str_schema()
            ),
        )

    return schema


def _trace_dataclass(
    *,
    schema: core_schema.DataclassSchema,
    handler: GetCoreSchemaHandler,
    references: set[str],
) -> core_schema.CoreSchema:
    """Configure a copied dataclass schema without changing its class.

    Returns:
        CoreSchema: A revalidating schema with trace-only payload guards.
    """
    schema["schema"] = _trace_schema(
        schema=schema["schema"], handler=handler, references=references
    )
    schema["config"] = {
        **schema.get("config", {}),
        "strict": True,
        "revalidate_instances": "always",
        "allow_inf_nan": False,
    }
    if schema["cls"] is Payload:
        reference = schema.pop("ref", None)
        return core_schema.no_info_before_validator_function(
            _trace_payload, schema, ref=reference
        )
    return schema


def _trace_payload(value: object) -> object:
    """Reject unsupported artifacts before dataclass construction touches them.

    Returns:
        object: The unchanged payload for normal field validation.

    Raises:
        ValueError: If identity is absent or a binary artifact is encountered.
    """
    if isinstance(value, Mapping):
        if "id" not in value:
            msg = "id: a trace payload must record its id"
            raise ValueError(msg)
        payload_format = value.get("format", PayloadFormat.TEXT)
        artifact = value.get("artifact")
    elif isinstance(value, Payload):
        payload_format = value.format
        artifact = value.artifact
    else:
        return value
    if isinstance(payload_format, PayloadFormat):
        payload_format = payload_format.value
    if isinstance(payload_format, str) and payload_format in {
        member.value for member in PayloadFormat if member.is_binary
    }:
        msg = "binary payload format and artifact are unsupported in traces"
        raise ValueError(msg)
    if artifact is not None:
        msg = "artifact: only null is supported in traces"
        raise ValueError(msg)
    return value


def json_string(*, value: str, path: str) -> str:
    """Require Unicode scalar values without altering the string.

    Returns:
        str: The unchanged string.

    Raises:
        ValueError: If the string contains surrogate code points.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = f"{path}: surrogate code points are not supported in strings"
        raise ValueError(msg) from exc
    return value


def json_value(value: object) -> object:
    """Check and copy JSON values without lossy coercion.

    Returns:
        object: JSON primitives, lists, and string-keyed dictionaries.

    Raises:
        ValueError: If a value is non-finite, cyclic, or outside the JSON domain.
    """
    return _json_value(value=value, path="$", active=set())


def _json_value(*, value: object, path: str, active: set[int]) -> object:
    """Recursively validate the JSON domain, retaining the offending path.

    Returns:
        object: A JSON-safe copy.

    Raises:
        ValueError: If the value cannot be represented faithfully in JSON.
    """
    if isinstance(value, str):
        return json_string(value=value, path=path)
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if not isinstance(value, Mapping | list):
        msg = f"{path}: {type(value).__name__} is outside the finite JSON domain"
        raise ValueError(msg)  # ruff: ignore[type-check-without-type-error] Pydantic wraps ValueError.
    if id(value) in active:
        msg = f"{path}: cyclic JSON value"
        raise ValueError(msg)
    active.add(id(value))
    try:
        if isinstance(value, list):
            return [
                _json_value(value=item, path=f"{path}[{index}]", active=active)
                for index, item in enumerate(value)
            ]
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                msg = f"{path}: JSON object keys must be strings"
                raise ValueError(msg)  # ruff: ignore[type-check-without-type-error] Pydantic wraps ValueError.
            json_string(value=key, path=f"{path}.<key>")
            result[key] = _json_value(value=item, path=f"{path}.{key}", active=active)
        return result
    finally:
        active.remove(id(value))


# Pydantic supplies value/info positionally to BeforeValidator callbacks.
def _iso_datetime(value: object, info: ValidationInfo) -> object:
    """Retain Python ISO datetime support, including naive and subminute offsets.

    Returns:
        object: Parsed datetime strings, or the unchanged value for validation.

    Raises:
        ValueError: If the string is not an ISO datetime.
    """
    if info.mode == "json" and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            msg = "expected an ISO 8601 datetime string"
            raise ValueError(msg) from exc
    return value


def validation_message(*, error: ValidationError, path: str) -> str:
    """Render Pydantic errors without including producer data in the message.

    Returns:
        str: Field paths and validation reasons.
    """
    messages: list[str] = []
    for detail in error.errors(include_url=False, include_input=False):
        location = path
        for part in detail["loc"]:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        messages.append(f"{location}: {detail['msg']}")
    return "; ".join(messages)
