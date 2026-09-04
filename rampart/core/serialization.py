# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Canonical, versioned trace/result serialization for RAMPART.

This module owns the *single* full-fidelity ``Result`` <-> ``dict`` round-trip
for the whole framework (design gate WS0-05, Decision D6). xdist transport,
failure attachments, reporting projections, and future replay all serialize
through here rather than maintaining parallel serializers.

The canonical layer defines the supported *value domain* and nothing else. It
does not apply transport hygiene — no ANSI stripping, no float normalization,
no ``repr()``/``str()`` fallback, and no size capping. Those concerns wrap the
canonical output at the transport boundary (xdist). When a value falls outside
the canonical domain the codec fails closed with a field path rather than
coercing, so a durable trace never silently loses fidelity.

Every serialized record carries a single root ``version`` field
(:data:`TRACE_SCHEMA_VERSION`). Decoding dispatches on that version and fails
closed on an unknown major. The record version is independent of the xdist
transport envelope version; the two axes move separately.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from rampart.core.result import (
    InjectionRecord,
    PopulationRef,
    Result,
    SafetyStatus,
)
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)

if TYPE_CHECKING:
    from collections.abc import Callable

EnumT = TypeVar("EnumT", bound=Enum)

TRACE_SCHEMA_VERSION = "rampart.trace.v1"
"""Single root schema version stamped on every serialized record."""

RESERVED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "_pytest_nodeid",
        "_pytest_test_name",
        "_rampart_result_index",
        "_rampart_transport_truncated",
        "_rampart_original_size_bytes",
        "_rampart_limit_bytes",
        "_rampart_worker_format",
        "_rampart_worker_artifact_path",
    }
)
"""Top-level ``Result.metadata`` keys owned by the xdist transport.

These are scheduling/bookkeeping breadcrumbs the transport stamps for its own
reconciliation. They are stripped from the canonical body so a durable trace
carries only intrinsic result data; nested user maps are never touched.
"""


class SchemaError(Exception):
    """Raised when a value falls outside the canonical trace schema domain.

    The message carries the offending field path so producers can locate the
    out-of-domain value instead of the codec silently coercing it.
    """


class UnsupportedSchemaVersionError(SchemaError):
    """Raised when decoding a record whose ``version`` has no decoder.

    Readers fail closed on an unknown major rather than guessing at a shape.
    """


@dataclass(frozen=True, kw_only=True)
class ResultRecord:
    """The canonical, versioned envelope around a single ``Result``.

    This is the public surface: :meth:`to_dict` / :meth:`from_dict` are the one
    round-trip every durable consumer uses. The ``result`` is referenced, not
    copied. The collar fields (``identity``, ``pytest_nodeid``, ``result_index``)
    are wire-only provenance stamped once at the producing boundary.

    Args:
        result (Result): The single-run verdict being serialized.
        identity (dict[str, Any] | None): Stable test identity descriptor
            (WS0-06). ``None`` until identity is wired at the producer.
        pytest_nodeid (str | None): The pytest node id the result came from.
        result_index (int): Ordinal of this result within its test node.
    """

    VERSION: ClassVar[str] = TRACE_SCHEMA_VERSION

    result: Result
    identity: dict[str, Any] | None = None
    pytest_nodeid: str | None = None
    result_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Encode the record into a canonical, JSON-safe dict.

        Returns:
            dict[str, Any]: The versioned record with the encoded result body
                and wire-only collar. Fails closed via :class:`SchemaError` on
                any value outside the canonical domain.
        """
        return {
            "version": self.VERSION,
            "result": _encode_result(result=self.result, path="result"),
            "identity": _encode_json(value=self.identity, path="identity"),
            "pytest_nodeid": self.pytest_nodeid,
            "result_index": self.result_index,
        }

    @classmethod
    def from_dict(cls, data: object) -> ResultRecord:
        """Decode a canonical dict back into a record, dispatching on version.

        Args:
            data (object): A previously encoded record mapping.

        Returns:
            ResultRecord: The decoded record.

        Raises:
            SchemaError: If ``data`` is not a mapping.
            UnsupportedSchemaVersionError: If the record version has no decoder.
        """
        if not isinstance(data, Mapping):
            msg = f"Expected mapping for record, got {type(data).__name__}."
            raise SchemaError(msg)
        version = data.get("version")
        decoder = _DECODERS.get(version) if isinstance(version, str) else None
        if decoder is None:
            msg = f"No decoder registered for trace schema version {version!r}."
            raise UnsupportedSchemaVersionError(msg)
        return decoder(data)


def serialize_result(
    *,
    result: Result,
    identity: str | None = None,
    origin: str | None = None,
    case_id: str | None = None,
    pytest_nodeid: str | None = None,
    result_index: int = 0,
) -> dict[str, Any]:
    """Serialize a result to the canonical, versioned dict.

    Args:
        result (Result): The verdict to serialize.
        identity (str | None): Stable identity value (WS0-06), if computed.
        origin (str | None): How the identity was derived (marker vs. derived).
        case_id (str | None): Parametrization case id, travelling beside identity.
        pytest_nodeid (str | None): The pytest node id the result came from.
        result_index (int): Ordinal of this result within its test node.

    Returns:
        dict[str, Any]: The canonical record dict, ready for any durable sink.
    """
    identity_descriptor: dict[str, Any] | None = None
    if identity is not None or origin is not None or case_id is not None:
        identity_descriptor = {
            "value": identity,
            "origin": origin,
            "case_id": case_id,
        }
    record = ResultRecord(
        result=result,
        identity=identity_descriptor,
        pytest_nodeid=pytest_nodeid,
        result_index=result_index,
    )
    return record.to_dict()


def deserialize_result(*, data: object) -> ResultRecord:
    """Deserialize a canonical record dict back into a :class:`ResultRecord`.

    Args:
        data (object): A previously encoded record mapping.

    Returns:
        ResultRecord: The decoded record.
    """
    return ResultRecord.from_dict(data)


def _encode_result(*, result: Result, path: str) -> dict[str, Any]:
    """Encode a ``Result`` body into canonical primitives.

    Returns:
        dict[str, Any]: The encoded result with every field represented.
    """
    metadata = {
        key: value
        for key, value in result.metadata.items()
        if key not in RESERVED_METADATA_KEYS
    }
    return {
        "status": _encode_enum(value=result.status, path=f"{path}.status"),
        "summary": result.summary,
        "observability_level": _encode_enum(
            value=result.observability_level,
            path=f"{path}.observability_level",
        ),
        "turns": [
            _encode_turn(turn=turn, path=f"{path}.turns[{index}]")
            for index, turn in enumerate(result.turns)
        ],
        "duration_seconds": _encode_float(
            value=result.duration_seconds,
            path=f"{path}.duration_seconds",
        ),
        "harm_category": _encode_harm_category(value=result.harm_category),
        "strategy": result.strategy,
        "injections": [
            _encode_injection(record=record) for record in result.injections
        ],
        "population": _encode_population(
            value=result.population,
            path=f"{path}.population",
        ),
        "metadata": _encode_json(value=metadata, path=f"{path}.metadata"),
    }


def _encode_turn(*, turn: Turn, path: str) -> dict[str, Any]:
    """Encode a ``Turn``.

    Returns:
        dict[str, Any]: The encoded turn.
    """
    eval_result = (
        None
        if turn.eval_result is None
        else _encode_eval_result(value=turn.eval_result, path=f"{path}.eval_result")
    )
    return {
        "request": _encode_request(request=turn.request, path=f"{path}.request"),
        "response": _encode_response(response=turn.response, path=f"{path}.response"),
        "eval_result": eval_result,
        "turn_number": turn.turn_number,
        "timestamp": _encode_datetime(value=turn.timestamp),
        "driver_reasoning": turn.driver_reasoning,
    }


def _encode_request(*, request: Request, path: str) -> dict[str, Any]:
    """Encode a ``Request``.

    Returns:
        dict[str, Any]: The encoded request.
    """
    return {
        "prompt": request.prompt,
        "attachments": [
            _encode_payload(payload=payload, path=f"{path}.attachments[{index}]")
            for index, payload in enumerate(request.attachments)
        ],
    }


def _encode_response(*, response: Response, path: str) -> dict[str, Any]:
    """Encode a ``Response``.

    Returns:
        dict[str, Any]: The encoded response.
    """
    return {
        "text": response.text,
        "tool_calls": [
            _encode_tool_call(call=call, path=f"{path}.tool_calls[{index}]")
            for index, call in enumerate(response.tool_calls)
        ],
        "side_effects": [
            _encode_side_effect(effect=effect, path=f"{path}.side_effects[{index}]")
            for index, effect in enumerate(response.side_effects)
        ],
        "metadata": _encode_json(value=response.metadata, path=f"{path}.metadata"),
    }


def _encode_tool_call(*, call: ToolCall, path: str) -> dict[str, Any]:
    """Encode a ``ToolCall``.

    Returns:
        dict[str, Any]: The encoded tool call.
    """
    return {
        "name": call.name,
        "arguments": _encode_json(value=call.arguments, path=f"{path}.arguments"),
        "result": call.result,
        "timestamp": _encode_datetime(value=call.timestamp),
    }


def _encode_side_effect(*, effect: SideEffect, path: str) -> dict[str, Any]:
    """Encode a ``SideEffect``.

    Returns:
        dict[str, Any]: The encoded side effect.
    """
    return {
        "kind": effect.kind,
        "details": _encode_json(value=effect.details, path=f"{path}.details"),
    }


def _encode_payload(*, payload: Payload, path: str) -> dict[str, Any]:
    """Encode a ``Payload``.

    Binary payloads are persisted as content-addressed artifact descriptors by
    WS7 rather than inline; that resolver does not exist at
    ``rampart.trace.v1``, so a binary payload fails closed here instead of
    inlining a machine-local path.

    Returns:
        dict[str, Any]: The encoded payload.

    Raises:
        SchemaError: If the payload uses a binary format.
    """
    if payload.format.is_binary:
        msg = (
            f"{path}: binary payload format {payload.format.value!r} requires the "
            f"WS7 artifact resolver, unsupported in {TRACE_SCHEMA_VERSION}."
        )
        raise SchemaError(msg)
    return {
        "content": payload.content,
        "id": payload.id,
        "format": _encode_enum(value=payload.format, path=f"{path}.format"),
        "artifact": None,
        "metadata": _encode_json(value=payload.metadata, path=f"{path}.metadata"),
    }


def _encode_eval_result(*, value: EvalResult, path: str) -> dict[str, Any]:
    """Encode an ``EvalResult``.

    Returns:
        dict[str, Any]: The encoded evaluation result.
    """
    return {
        "outcome": _encode_enum(value=value.outcome, path=f"{path}.outcome"),
        "confidence": _encode_float(
            value=value.confidence,
            path=f"{path}.confidence",
        ),
        "evidence": list(value.evidence),
        "rationale": value.rationale,
        "undetermined_operands": list(value.undetermined_operands),
    }


def _encode_injection(*, record: InjectionRecord) -> dict[str, Any]:
    """Encode an ``InjectionRecord``.

    Returns:
        dict[str, Any]: The encoded injection record.
    """
    return {
        "payload_id": record.payload_id,
        "surface_name": record.surface_name,
    }


def _encode_population(
    *, value: PopulationRef | None, path: str
) -> dict[str, Any] | None:
    """Encode an optional ``PopulationRef``.

    Returns:
        dict[str, Any] | None: The encoded reference, or ``None``.
    """
    if value is None:
        return None
    return {
        "id": value.id,
        "index": value.index,
        "size": value.size,
        "threshold": _encode_float(value=value.threshold, path=f"{path}.threshold"),
    }


def _encode_enum(*, value: Enum, path: str) -> str:
    """Encode an enum member to its wire value.

    Returns:
        str: The enum ``.value``.

    Raises:
        SchemaError: If ``value`` is not an enum member.
    """
    if not isinstance(value, Enum):
        msg = f"{path}: expected enum, got {type(value).__name__}."
        raise SchemaError(msg)
    return str(value.value)


def _encode_harm_category(*, value: object) -> str | None:
    """Encode a harm category as a passthrough string.

    Returns:
        str | None: The category string, or ``None`` when unset.
    """
    if value is None:
        return None
    return str(value)


def _encode_datetime(*, value: datetime | None) -> str | None:
    """Encode a datetime to ISO 8601.

    Returns:
        str | None: The ISO timestamp, or ``None``.
    """
    if value is None:
        return None
    return value.isoformat()


def _encode_float(*, value: float, path: str) -> float:
    """Validate and pass through a float within the canonical domain.

    Returns:
        float: The finite float value.

    Raises:
        SchemaError: If ``value`` is not a finite real number. Normalizing
            non-finite floats is transport hygiene, not a canonical concern.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{path}: expected a real number, got {type(value).__name__}."
        raise SchemaError(msg)
    if not math.isfinite(value):
        msg = f"{path}: expected a finite number, got {value!r}."
        raise SchemaError(msg)
    return float(value)


def _encode_json(*, value: object, path: str) -> object:
    """Validate that ``value`` is JSON-safe, failing closed otherwise.

    Recurses through lists and string-keyed maps of primitives. Anything
    outside the domain (bytes, ``Path``, arbitrary objects, non-finite floats,
    non-string map keys) raises rather than being coerced via ``repr()``.

    Returns:
        Any: A JSON-safe copy of ``value``.

    Raises:
        SchemaError: If ``value`` contains anything outside the JSON domain.
    """
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _encode_float(value=value, path=path)
    if isinstance(value, Mapping):
        return _encode_json_map(value=value, path=path)
    if isinstance(value, list | tuple):
        return [
            _encode_json(value=item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    msg = f"{path}: value of type {type(value).__name__} is outside the JSON domain."
    raise SchemaError(msg)


def _encode_json_map(*, value: Mapping[Any, Any], path: str) -> dict[str, Any]:
    """Validate and copy a JSON-safe string-keyed map.

    Returns:
        dict[str, Any]: A JSON-safe copy of the map.

    Raises:
        SchemaError: If any key is not a string.
    """
    encoded: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{path}: map key {key!r} is not a string."
            raise SchemaError(msg)
        encoded[key] = _encode_json(value=item, path=f"{path}.{key}")
    return encoded


def _decode_v1(data: Mapping[str, Any]) -> ResultRecord:
    """Decode a ``rampart.trace.v1`` record.

    Returns:
        ResultRecord: The decoded record.

    Raises:
        SchemaError: If the record body is not a mapping.
    """
    body = data.get("result")
    if not isinstance(body, Mapping):
        msg = f"record 'result' body must be a mapping, got {type(body).__name__}."
        raise SchemaError(msg)
    identity = data.get("identity")
    result_index = data.get("result_index", 0)
    pytest_nodeid = data.get("pytest_nodeid")
    return ResultRecord(
        result=_decode_result(data=body, path="result"),
        identity=identity if isinstance(identity, Mapping) else None,
        pytest_nodeid=pytest_nodeid if isinstance(pytest_nodeid, str) else None,
        result_index=result_index if isinstance(result_index, int) else 0,
    )


def _decode_result(*, data: Mapping[str, Any], path: str) -> Result:
    """Decode a ``Result`` body.

    Returns:
        Result: The reconstructed result.
    """
    return Result(
        status=_decode_enum(
            enum=SafetyStatus,
            value=data.get("status"),
            path=f"{path}.status",
        ),
        summary=_decode_str(value=data.get("summary"), path=f"{path}.summary"),
        observability_level=_decode_enum(
            enum=ObservabilityLevel,
            value=data.get("observability_level"),
            path=f"{path}.observability_level",
        ),
        turns=[
            _decode_turn(data=item, path=f"{path}.turns[{index}]")
            for index, item in enumerate(_decode_list(value=data.get("turns")))
        ],
        duration_seconds=_encode_float(
            value=data.get("duration_seconds", 0.0),
            path=f"{path}.duration_seconds",
        ),
        harm_category=_decode_harm_category(value=data.get("harm_category")),
        strategy=_decode_str(value=data.get("strategy", ""), path=f"{path}.strategy"),
        injections=[
            _decode_injection(data=item, path=f"{path}.injections[{index}]")
            for index, item in enumerate(_decode_list(value=data.get("injections")))
        ],
        population=_decode_population(
            value=data.get("population"),
            path=f"{path}.population",
        ),
        metadata=dict(
            _decode_optional_map(value=data.get("metadata"), path=f"{path}.metadata")
        ),
    )


def _decode_turn(*, data: object, path: str) -> Turn:
    """Decode a ``Turn``.

    Returns:
        Turn: The reconstructed turn.
    """
    typed = _decode_map(value=data, path=path)
    raw_eval = typed.get("eval_result")
    eval_result = (
        None
        if raw_eval is None
        else _decode_eval_result(data=raw_eval, path=f"{path}.eval_result")
    )
    return Turn(
        request=_decode_request(data=typed.get("request"), path=f"{path}.request"),
        response=_decode_response(data=typed.get("response"), path=f"{path}.response"),
        eval_result=eval_result,
        turn_number=_decode_int(
            value=typed.get("turn_number", 0), path=f"{path}.turn_number"
        ),
        timestamp=_decode_datetime(
            value=typed.get("timestamp"), path=f"{path}.timestamp"
        ),
        driver_reasoning=_decode_str(
            value=typed.get("driver_reasoning", ""),
            path=f"{path}.driver_reasoning",
        ),
    )


def _decode_request(*, data: object, path: str) -> Request:
    """Decode a ``Request``.

    Returns:
        Request: The reconstructed request.
    """
    typed = _decode_map(value=data, path=path)
    raw_prompt = typed.get("prompt")
    prompt = raw_prompt if isinstance(raw_prompt, str) else None
    return Request(
        prompt=prompt,
        attachments=[
            _decode_payload(data=item, path=f"{path}.attachments[{index}]")
            for index, item in enumerate(_decode_list(value=typed.get("attachments")))
        ],
    )


def _decode_response(*, data: object, path: str) -> Response:
    """Decode a ``Response``.

    Returns:
        Response: The reconstructed response.
    """
    typed = _decode_map(value=data, path=path)
    return Response(
        text=_decode_str(value=typed.get("text", ""), path=f"{path}.text"),
        tool_calls=[
            _decode_tool_call(data=item, path=f"{path}.tool_calls[{index}]")
            for index, item in enumerate(_decode_list(value=typed.get("tool_calls")))
        ],
        side_effects=[
            _decode_side_effect(data=item, path=f"{path}.side_effects[{index}]")
            for index, item in enumerate(_decode_list(value=typed.get("side_effects")))
        ],
        metadata=dict(
            _decode_optional_map(value=typed.get("metadata"), path=f"{path}.metadata")
        ),
    )


def _decode_tool_call(*, data: object, path: str) -> ToolCall:
    """Decode a ``ToolCall``.

    Returns:
        ToolCall: The reconstructed tool call.
    """
    typed = _decode_map(value=data, path=path)
    raw_result = typed.get("result")
    return ToolCall(
        name=_decode_str(value=typed.get("name", ""), path=f"{path}.name"),
        arguments=dict(
            _decode_optional_map(value=typed.get("arguments"), path=f"{path}.arguments")
        ),
        result=raw_result if isinstance(raw_result, str) else None,
        timestamp=_decode_datetime(
            value=typed.get("timestamp"), path=f"{path}.timestamp"
        ),
    )


def _decode_side_effect(*, data: object, path: str) -> SideEffect:
    """Decode a ``SideEffect``.

    Returns:
        SideEffect: The reconstructed side effect.
    """
    typed = _decode_map(value=data, path=path)
    return SideEffect(
        kind=_decode_str(value=typed.get("kind", ""), path=f"{path}.kind"),
        details=dict(
            _decode_optional_map(value=typed.get("details"), path=f"{path}.details")
        ),
    )


def _decode_payload(*, data: object, path: str) -> Payload:
    """Decode a ``Payload``.

    A binary payload has no artifact resolver at ``rampart.trace.v1`` and fails
    closed rather than being coerced to a text payload.

    Returns:
        Payload: The reconstructed payload.

    Raises:
        SchemaError: If the payload declares a binary format.
    """
    typed = _decode_map(value=data, path=path)
    payload_format = _decode_enum(
        enum=PayloadFormat,
        value=typed.get("format", PayloadFormat.TEXT.value),
        path=f"{path}.format",
    )
    if payload_format.is_binary:
        msg = (
            f"{path}: binary payload format {payload_format.value!r} requires the "
            f"WS7 artifact resolver, unsupported in {TRACE_SCHEMA_VERSION}."
        )
        raise SchemaError(msg)
    return Payload(
        content=_decode_str(value=typed.get("content", ""), path=f"{path}.content"),
        id=_decode_str(value=typed.get("id", ""), path=f"{path}.id"),
        format=payload_format,
        artifact=None,
        metadata=dict(
            _decode_optional_map(value=typed.get("metadata"), path=f"{path}.metadata")
        ),
    )


def _decode_eval_result(*, data: object, path: str) -> EvalResult:
    """Decode an ``EvalResult``.

    Returns:
        EvalResult: The reconstructed evaluation result.
    """
    typed = _decode_map(value=data, path=path)
    return EvalResult(
        outcome=_decode_enum(
            enum=EvalOutcome,
            value=typed.get("outcome"),
            path=f"{path}.outcome",
        ),
        confidence=_encode_float(
            value=typed.get("confidence", 1.0),
            path=f"{path}.confidence",
        ),
        evidence=_decode_str_list(value=typed.get("evidence"), path=f"{path}.evidence"),
        rationale=_decode_str(
            value=typed.get("rationale", ""), path=f"{path}.rationale"
        ),
        undetermined_operands=_decode_str_list(
            value=typed.get("undetermined_operands"),
            path=f"{path}.undetermined_operands",
        ),
    )


def _decode_injection(*, data: object, path: str) -> InjectionRecord:
    """Decode an ``InjectionRecord``.

    Returns:
        InjectionRecord: The reconstructed injection record.
    """
    typed = _decode_map(value=data, path=path)
    raw_payload_id = typed.get("payload_id")
    return InjectionRecord(
        payload_id=raw_payload_id if isinstance(raw_payload_id, str) else None,
        surface_name=_decode_str(
            value=typed.get("surface_name", ""),
            path=f"{path}.surface_name",
        ),
    )


def _decode_population(*, value: object, path: str) -> PopulationRef | None:
    """Decode an optional ``PopulationRef``.

    Returns:
        PopulationRef | None: The reconstructed reference, or ``None``.
    """
    if value is None:
        return None
    typed = _decode_map(value=value, path=path)
    return PopulationRef(
        id=_decode_str(value=typed.get("id", ""), path=f"{path}.id"),
        index=_decode_int(value=typed.get("index", 0), path=f"{path}.index"),
        size=_decode_int(value=typed.get("size", 0), path=f"{path}.size"),
        threshold=_encode_float(
            value=typed.get("threshold", 0.0), path=f"{path}.threshold"
        ),
    )


def _decode_enum(*, enum: type[EnumT], value: object, path: str) -> EnumT:
    """Decode an enum member from its wire value, failing closed on unknown.

    Returns:
        EnumT: The enum member.

    Raises:
        SchemaError: If ``value`` is not a member of ``enum``.
    """
    try:
        return enum(value)
    except ValueError as exc:
        msg = f"{path}: {value!r} is not a valid {enum.__name__}."
        raise SchemaError(msg) from exc


def _decode_harm_category(*, value: object) -> str | None:
    """Decode a harm category as a passthrough string.

    Returns:
        str | None: The category string, or ``None``.
    """
    if value is None:
        return None
    return str(value)


def _decode_datetime(*, value: object, path: str) -> datetime | None:
    """Decode an ISO 8601 timestamp.

    Returns:
        datetime | None: The parsed datetime, or ``None``.

    Raises:
        SchemaError: If ``value`` is neither ``None`` nor a valid ISO string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{path}: expected an ISO timestamp string, got {type(value).__name__}."
        raise SchemaError(msg)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"{path}: {value!r} is not a valid ISO 8601 timestamp."
        raise SchemaError(msg) from exc


def _decode_str(*, value: object, path: str) -> str:
    """Decode a required string field.

    Returns:
        str: The string value.

    Raises:
        SchemaError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        msg = f"{path}: expected a string, got {type(value).__name__}."
        raise SchemaError(msg)
    return value


def _decode_int(*, value: object, path: str) -> int:
    """Decode a required integer field.

    Returns:
        int: The integer value.

    Raises:
        SchemaError: If ``value`` is not an integer.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{path}: expected an integer, got {type(value).__name__}."
        raise SchemaError(msg)
    return value


def _decode_list(*, value: object) -> list[Any]:
    """Coerce an optional wire list to a list.

    Returns:
        list[Any]: The list, or an empty list when absent.
    """
    return list(value) if isinstance(value, list) else []


def _decode_str_list(*, value: object, path: str) -> list[str]:
    """Decode a list of strings.

    Returns:
        list[str]: The decoded strings.
    """
    return [
        _decode_str(value=item, path=f"{path}[{index}]")
        for index, item in enumerate(_decode_list(value=value))
    ]


def _decode_map(*, value: object, path: str) -> Mapping[str, Any]:
    """Decode a required mapping field.

    Returns:
        Mapping[str, Any]: The mapping value.

    Raises:
        SchemaError: If ``value`` is not a mapping.
    """
    if not isinstance(value, Mapping):
        msg = f"{path}: expected a mapping, got {type(value).__name__}."
        raise SchemaError(msg)
    return value


def _decode_optional_map(*, value: object, path: str) -> Mapping[str, Any]:
    """Decode an optional mapping field, defaulting to empty when absent.

    Returns:
        Mapping[str, Any]: The mapping value, or an empty mapping when ``None``.

    Raises:
        SchemaError: If ``value`` is present but not a mapping.
    """
    if value is None:
        return {}
    return _decode_map(value=value, path=path)


_DECODERS: dict[str, Callable[[Mapping[str, Any]], ResultRecord]] = {
    TRACE_SCHEMA_VERSION: _decode_v1,
}
