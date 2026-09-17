# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Versioned ResultRecord envelopes around the canonical Result body codec."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
)

from rampart.core._schema import json_string
from rampart.core.errors import SchemaError, UnsupportedSchemaVersionError
from rampart.core.result import Result

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Never

    from pydantic.json_schema import JsonSchemaValue


# Single root schema version stamped on every serialized record.
TRACE_SCHEMA_VERSION = "rampart.trace.v1"

# Strip only top-level transport bookkeeping, never matching nested user keys.
_RESERVED_METADATA_KEYS = frozenset(
    {
        "_pytest_nodeid",
        "_pytest_test_name",
        "_rampart_result_index",
        "_rampart_source_worker",
        "_rampart_transport_truncated",
        "_rampart_original_size_bytes",
        "_rampart_limit_bytes",
        "_rampart_worker_format",
        "_rampart_worker_artifact_path",
    }
)


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

    def to_dict(self) -> dict[str, Any]:
        """Convert the envelope to a dict using the single Result body codec.

        Returns:
            dict[str, Any]: A versioned, JSON-safe record.

        Raises:
            SchemaError: If the referenced result is outside the trace domain.
        """
        if not isinstance(self.result.metadata, Mapping):
            msg = "result.metadata: expected a mapping"
            raise SchemaError(msg)
        metadata = {
            key: value
            for key, value in self.result.metadata.items()
            if key not in _RESERVED_METADATA_KEYS
        }
        body = replace(self.result, metadata=metadata).to_dict()
        encoded: dict[str, Any] = {"version": self.VERSION, "result": body}
        if self.pytest_nodeid is not None:
            encoded["pytest_nodeid"] = self.pytest_nodeid
        if self.result_index is not None:
            encoded["result_index"] = self.result_index
        return encoded

    @classmethod
    def from_dict(cls, data: object) -> ResultRecord:
        """Dispatch a record to its version-specific decoder.

        Returns:
            ResultRecord: The reconstructed body and attribution.

        Raises:
            SchemaError: If the record is not a mapping.
            UnsupportedSchemaVersionError: If the version is unsupported.
        """
        if not isinstance(data, Mapping):
            msg = "record: expected a mapping"
            raise SchemaError(msg)
        version = data.get("version")
        decoder = _DECODERS.get(version) if isinstance(version, str) else None
        if decoder is None:
            msg = f"No decoder registered for trace schema version {version!r}."
            raise UnsupportedSchemaVersionError(msg)
        return decoder(data)

    @classmethod
    def json_schema(cls) -> JsonSchemaValue:
        """Compose the versioned contract with the adapter-generated body schema.

        Returns:
            JsonSchemaValue: An open Draft 2020-12 schema.
        """
        body = Result.json_schema()
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
    data = record.to_dict()
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
    return ResultRecord.from_dict(decoded)


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
        result=Result.from_dict(data.get("result")),
        pytest_nodeid=data.get("pytest_nodeid"),
        result_index=data.get("result_index"),
    )


_DECODERS: dict[str, Callable[[Mapping[str, Any]], ResultRecord]] = {
    TRACE_SCHEMA_VERSION: _decode_v1,
}
