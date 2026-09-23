# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Canonical, versioned JSON serialization for ResultRecord envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
)

from pydantic import (
    GetPydanticSchema,
    TypeAdapter,
    ValidationError,
)
from pydantic.json_schema import GenerateJsonSchema

from rampart.core._schema import (
    json_string,
    json_value,
    trace_schema,
    validation_message,
)
from rampart.core.errors import SchemaError, UnsupportedSchemaVersionError
from rampart.core.result import Result
from rampart.core.types import Payload, PayloadFormat, Request

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Never

    from pydantic.json_schema import JsonSchemaMode, JsonSchemaValue
    from pydantic_core import core_schema


# Single root schema version stamped on every serialized record.
TRACE_SCHEMA_VERSION = "rampart.trace.v1"


@dataclass(frozen=True, kw_only=True)
class ResultRecord:
    """A versioned envelope referencing one Result and optional attribution.

    Args:
        result (Result): The referenced result; its fields are not copied.
        pytest_nodeid (str | None): Producing test location, when recorded.
        result_index (int | None): Within-node ordinal, when recorded.
    """

    VERSION: ClassVar[str] = TRACE_SCHEMA_VERSION

    result: Result
    pytest_nodeid: str | None = None
    result_index: int | None = None

    def __post_init__(self) -> None:
        """Validate attribution without copying or revalidating the live result.

        Raises:
            SchemaError: If attribution has invalid types.
        """
        if self.pytest_nodeid is not None and not isinstance(self.pytest_nodeid, str):
            msg = "record.pytest_nodeid: expected a string or null"
            raise SchemaError(msg)
        if self.pytest_nodeid is not None:
            try:
                json_string(value=self.pytest_nodeid, path="record.pytest_nodeid")
            except ValueError as exc:
                raise SchemaError(str(exc)) from exc
        if self.result_index is not None and type(self.result_index) is not int:
            msg = "record.result_index: expected an integer or null"
            raise SchemaError(msg)

    @classmethod
    def json_schema(cls) -> JsonSchemaValue:
        """Compose the versioned contract with the adapter-generated body schema.

        Returns:
            JsonSchemaValue: An open Draft 2020-12 schema.
        """
        body = _result_adapter().json_schema(schema_generator=_ResultJsonSchema)
        definitions = body.pop("$defs", {})
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:rampart:trace:{TRACE_SCHEMA_VERSION.rsplit('.', 1)[-1]}",
            "$defs": definitions,
            "title": "ResultRecord",
            "description": (
                "Structural trace contract. The record decoder additionally "
                "requires parseable Python ISO datetimes, finite numbers, "
                "Unicode scalar strings, "
                "and integer fields without floating-point notation."
            ),
            "type": "object",
            "additionalProperties": True,
            "required": ["version", "result"],
            "properties": {
                "version": {"type": "string", "const": TRACE_SCHEMA_VERSION},
                "result": body,
                "pytest_nodeid": {"type": ["string", "null"]},
                "result_index": {"type": ["integer", "null"]},
            },
        }


def serialize_record(*, record: ResultRecord) -> str:
    """Serialize a canonical record to JSON text.

    Args:
        record (ResultRecord): The result and its optional attribution.

    Returns:
        str: JSON text containing the versioned record.

    Raises:
        SchemaError: If the record cannot be represented as canonical JSON.
    """
    adapter = _result_adapter()
    try:
        validated = adapter.validate_python(record.result, strict=True)
        body = adapter.dump_python(validated, mode="json", warnings="error")
    except ValidationError as exc:
        raise SchemaError(validation_message(error=exc, path="result")) from exc
    except (ValueError, RecursionError) as exc:
        msg = f"result: cannot serialize canonical body ({type(exc).__name__})"
        raise SchemaError(msg) from exc
    data: dict[str, Any] = {"version": record.VERSION, "result": body}
    if record.pytest_nodeid is not None:
        data["pytest_nodeid"] = record.pytest_nodeid
    if record.result_index is not None:
        data["result_index"] = record.result_index
    try:
        return json.dumps(data, allow_nan=False)
    except (ValueError, RecursionError) as exc:
        msg = f"record: cannot serialize JSON ({exc})"
        raise SchemaError(msg) from exc


def deserialize_record(*, data: str) -> ResultRecord:
    """Deserialize a canonical record from JSON text.

    Args:
        data (str): JSON text containing a versioned record.

    Returns:
        ResultRecord: The result and its attribution.

    Raises:
        SchemaError: If the input is not JSON text or the record is malformed.
        UnsupportedSchemaVersionError: If the version is unsupported.
    """
    if not isinstance(data, str):
        msg = "record: expected a JSON string"
        raise SchemaError(msg)
    try:
        decoded = json.loads(data, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        msg = f"record: invalid JSON ({exc})"
        raise SchemaError(msg) from exc
    if not isinstance(decoded, Mapping):
        msg = "record: expected a mapping"
        raise SchemaError(msg)
    version = decoded.get("version")
    decoder = _DECODERS.get(version) if isinstance(version, str) else None
    if decoder is None:
        msg = f"No decoder registered for trace schema version {version!r}."
        raise UnsupportedSchemaVersionError(msg)
    return decoder(decoded)


def _validate_body(data: object) -> Result:
    """Validate a JSON body and reconstruct its Result.

    Returns:
        Result: The reconstructed result.

    Raises:
        SchemaError: If the body is malformed or outside the trace domain.
    """
    try:
        # JSON-mode strict validation accepts wire enums/dates, not coercions.
        encoded = json.dumps(json_value(data), allow_nan=False)
        return _result_adapter().validate_json(encoded, strict=True)
    except ValidationError as exc:
        raise SchemaError(validation_message(error=exc, path="result")) from exc
    except (ValueError, RecursionError) as exc:
        msg = f"result: {exc}"
        raise SchemaError(msg) from exc


def _reject_json_constant(value: str) -> Never:
    """Reject the non-finite constants accepted by Python's JSON parser.

    Raises:
        ValueError: Always, because these constants are not valid JSON numbers.
    """
    msg = f"non-finite number {value}"
    raise ValueError(msg)


def _decode_v1(data: Mapping[str, Any]) -> ResultRecord:
    """Reconstruct a v1 envelope through the current body codec.

    Returns:
        ResultRecord: The reconstructed record.
    """
    return ResultRecord(
        result=_validate_body(data.get("result")),
        pytest_nodeid=data.get("pytest_nodeid"),
        result_index=data.get("result_index"),
    )


_DECODERS: dict[str, Callable[[Mapping[str, Any]], ResultRecord]] = {
    TRACE_SCHEMA_VERSION: _decode_v1,
}


@cache
def _result_adapter() -> TypeAdapter[Result]:
    """Build the recursive adapter once, on first serialization use.

    Returns:
        TypeAdapter[Result]: The cached adapter.
    """
    adapter = TypeAdapter[Result](Annotated[Result, GetPydanticSchema(trace_schema)])
    # Nested dataclasses keep these imports under TYPE_CHECKING.
    adapter.rebuild(_types_namespace={"datetime": datetime, "Path": Path})
    return adapter


class _ResultJsonSchema(GenerateJsonSchema):
    """Describe trace-only restrictions alongside the dataclass field schemas."""

    def generate(
        self, schema: core_schema.CoreSchema, mode: JsonSchemaMode = "validation"
    ) -> JsonSchemaValue:
        """Omit runtime class documentation from the published wire contract.

        Returns:
            JsonSchemaValue: A schema with only trace-specific descriptions.
        """
        result = super().generate(schema, mode=mode)
        result.pop("description", None)
        definitions = result.get("$defs", {})
        for definition in definitions.values():
            definition.pop("description", None)
        if "Payload" in definitions:
            definitions["Payload"]["description"] = (
                "Recorded text payload. Binary formats and file artifacts "
                "are not supported by this trace schema."
            )
        return result

    def dataclass_schema(self, schema: core_schema.DataclassSchema) -> JsonSchemaValue:
        """Add trace policies that do not restrict live dataclass construction.

        Returns:
            JsonSchemaValue: An open object schema matching the trace validators.
        """
        result = super().dataclass_schema(schema)
        result["additionalProperties"] = True
        if schema["cls"] is Payload:
            result["properties"]["format"] = {
                "type": "string",
                "enum": [value.value for value in PayloadFormat if value.is_text],
                "default": PayloadFormat.TEXT.value,
            }
            result["properties"]["artifact"] = {"type": "null", "default": None}
            result["required"] = [*result["required"], "id"]
        elif schema["cls"] is Request:
            result["anyOf"] = [
                {"required": ["prompt"], "properties": {"prompt": {"type": "string"}}},
                {
                    "required": ["attachments"],
                    "properties": {"attachments": {"type": "array", "minItems": 1}},
                },
            ]
        return result

    def datetime_schema(self, schema: core_schema.DatetimeSchema) -> JsonSchemaValue:
        """Describe Python datetimes without claiming RFC 3339 validation.

        Returns:
            JsonSchemaValue: A string with decoder-enforced datetime semantics.
        """
        result = super().datetime_schema(schema)
        result.pop("format", None)
        result["description"] = (
            "Python ISO 8601 datetime; UTC offset is optional. "
            "Parseability is enforced by the record decoder, not this schema."
        )
        return result
