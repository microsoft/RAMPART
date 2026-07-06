# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""xdist support for RAMPART's pytest plugin.

Provides serialization, deserialization, and controller-side merge
logic for running RAMPART under pytest-xdist. Workers serialize their
``Result`` objects into ``config.workeroutput``; the controller merges
worker payloads in ``pytest_testnodedown`` and emits a single unified
report at session end.

Trust boundary: worker payloads may contain attacker-controlled
content (agent responses, payload text). Serialization is strictly
JSON-safe primitives; deserialization validates schema version,
enum values, and metadata depth; ANSI escapes are stripped from free
text as defense-in-depth.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from rampart.common.text import strip_ansi as _strip_ansi_impl
from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
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
from rampart.pytest_plugin._session import TrialSpec
from rampart.reporting.sink import ReportSink

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest
    from _typeshed import ConvertibleToInt

    from rampart.pytest_plugin._session import RampartSession

logger = logging.getLogger(__name__)

SCHEMA_VERSION: str = "rampart.xdist.v1"
WORKEROUTPUT_KEY: str = "rampart_xdist_v1"
SIZE_LIMIT_OPTION: str = "rampart_xdist_max_bytes"
DEFAULT_SIZE_LIMIT_BYTES: int = 64 * 1024 * 1024
MAX_METADATA_DEPTH: int = 6

_TRUNCATED_MARKER: str = "rampart_truncated"


class WorkerOutputError(Exception):
    """Base error for xdist worker output processing failures."""


class SchemaVersionError(WorkerOutputError):
    """Raised when a worker payload has missing or unknown schema version."""


class SizeLimitError(WorkerOutputError):
    """Raised when a worker payload exceeds the configured size cap."""


def is_xdist_worker(*, config: pytest.Config) -> bool:
    """Return True when this process is a pytest-xdist worker.

    Detection is attribute-based; no xdist import required, so this
    function is safe to call when pytest-xdist is not installed.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        bool: True if running in an xdist worker process.
    """
    return hasattr(config, "workerinput")


def is_xdist_controller(*, config: pytest.Config) -> bool:
    """Return True when this process is the pytest-xdist controller.

    The controller is the non-worker process that owns an active
    distribution: a ``--dist`` mode other than ``"no"`` plus at least one
    way of spawning execution endpoints (``--numprocesses`` workers or
    explicit ``--tx`` gateways). Keying off distribution rather than the
    worker count alone keeps ``-d``/``--tx`` runs (no ``-n``) on the
    controller path while excluding a bare ``--dist`` with no endpoints.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        bool: True if running in the xdist controller process.
    """
    if is_xdist_worker(config=config):
        return False
    if get_dist_mode(config=config) == "no":
        return False
    numprocesses = getattr(config.option, "numprocesses", None)
    tx = getattr(config.option, "tx", None)
    return bool(numprocesses) or bool(tx)


def get_dist_mode(*, config: pytest.Config) -> str:
    """Return the active ``--dist`` mode string.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        str: The dist mode (e.g., ``"load"``, ``"loadgroup"``, ``"no"``).
    """
    return cast("str", getattr(config.option, "dist", "no"))


def get_worker_count(*, config: pytest.Config) -> int:
    """Return the number of xdist workers configured.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        int: Number of workers (0 when xdist is not active).
    """
    numprocesses = getattr(config.option, "numprocesses", 0)
    return int(numprocesses) if numprocesses else 0


def _size_limit(*, config: pytest.Config) -> int:
    """Resolve the worker payload size cap from pytest config or default.

    Reads from the ``--rampart-xdist-max-bytes`` CLI option first, then
    the ``rampart_xdist_max_bytes`` ini option, then falls back to
    ``DEFAULT_SIZE_LIMIT_BYTES``.

    Returns:
        int: The resolved size cap in bytes.
    """
    raw: Any = config.getoption(SIZE_LIMIT_OPTION, default=None)
    if raw is None:
        try:
            raw = config.getini(SIZE_LIMIT_OPTION)
        except (ValueError, KeyError):
            raw = None
    if raw in {None, ""}:
        return DEFAULT_SIZE_LIMIT_BYTES
    try:
        # fallible cast, so catch TypeError/ValueError and log a warning
        parsed = int(cast("ConvertibleToInt", raw))
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%r; falling back to default %d bytes.",
            SIZE_LIMIT_OPTION,
            raw,
            DEFAULT_SIZE_LIMIT_BYTES,
        )
        return DEFAULT_SIZE_LIMIT_BYTES
    if parsed <= 0:
        logger.warning(
            "%s=%d must be > 0; falling back to default %d bytes.",
            SIZE_LIMIT_OPTION,
            parsed,
            DEFAULT_SIZE_LIMIT_BYTES,
        )
        return DEFAULT_SIZE_LIMIT_BYTES
    return parsed


def _strip_ansi(*, text: str) -> str:
    """Remove ANSI escape sequences and control bytes from free-form text.

    Delegates to :func:`rampart.common.text.strip_ansi` so the xdist
    transport and the terminal summary share one hardened sanitizer.

    Args:
        text (str): The text to sanitize.

    Returns:
        str: Text with escape sequences and control bytes removed.
    """
    return _strip_ansi_impl(text)


def _sanitize(  # noqa: PLR0911
    *,
    value: Any,  # noqa: ANN401
    depth: int = 0,
    strip_ansi: bool = False,
) -> Any:  # noqa: ANN401
    """Coerce a value to a JSON-safe form.

    Walks dicts and lists up to ``MAX_METADATA_DEPTH``. Values not in
    (str, int, bool, NoneType, finite float, dict, list, tuple) are
    coerced via ``repr()``. NaN/Inf floats are coerced to ``None``.

    When ``strip_ansi=True`` (set on the deserialization path), ANSI
    escape sequences are removed from every nested string value so
    that attacker-controlled escapes inside ``arguments``, ``details``,
    and ``metadata`` cannot reach terminal renderers.

    Args:
        value (Any): The value to sanitize.
        depth (int): Current recursion depth (internal).
        strip_ansi (bool): If True, strip ANSI escapes from strings.

    Returns:
        Any: A JSON-safe representation.
    """
    if depth > MAX_METADATA_DEPTH:
        return repr(value)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _strip_ansi(text=value) if strip_ansi else value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(k): _sanitize(value=v, depth=depth + 1, strip_ansi=strip_ansi)
            for k, v in cast("dict[Any, Any]", value).items()
        }
    if isinstance(value, list | tuple):
        return [
            _sanitize(value=v, depth=depth + 1, strip_ansi=strip_ansi)
            for v in cast("list[Any]", value)
        ]
    return repr(value)


def _is_json_passthrough(value: Any) -> bool:  # noqa: ANN401
    """True if a value would pass through ``_sanitize`` unchanged.

    Returns:
        bool: True if ``value`` is JSON-safe as-is.
    """
    if value is None or isinstance(value, str | bool):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return False


def _sanitize_metadata(
    *,
    metadata: dict[str, Any],
    nodeid: str,
    context: str,
) -> dict[str, Any]:
    """Sanitize a metadata dict; log keys that required coercion.

    Logs at warning level with the originating nodeid and the list of
    keys whose values were coerced so users can diagnose lossy fields
    without polluting the user-visible metadata payload.

    Args:
        metadata (dict[str, Any]): The metadata to sanitize.
        nodeid (str): Originating test nodeid (for log context).
        context (str): Source context (e.g., ``"result"``, ``"payload"``).

    Returns:
        dict[str, Any]: Sanitized metadata dict.
    """
    sanitized: dict[str, Any] = {}
    coerced: list[str] = []
    for key, value in metadata.items():
        key_str = str(key)
        sanitized[key_str] = _sanitize(value=value)
        passthrough = _is_json_passthrough(value)
        collection = isinstance(value, dict | list | tuple)
        if not passthrough and not collection:
            coerced.append(key_str)
    if coerced:
        logger.warning(
            "Sanitized %d non-serializable metadata key(s) for %s in %s: %s",
            len(coerced),
            nodeid,
            context,
            coerced,
        )
    return sanitized


def _safe_float(*, value: float) -> float | None:
    """Coerce non-finite floats to None for JSON safety.

    Returns:
        float | None: ``value`` when finite, else ``None``.
    """
    return value if math.isfinite(value) else None


def _isoformat(*, timestamp: datetime | None) -> str | None:
    """Convert a datetime to ISO 8601 string, or None.

    Returns:
        str | None: The ISO 8601 string, or ``None`` when ``timestamp`` is None.
    """
    return timestamp.isoformat() if timestamp is not None else None


def _serialize_eval_result(*, eval_result: EvalResult) -> dict[str, Any]:
    """Serialize an EvalResult to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "outcome": eval_result.outcome.value,
        "confidence": _safe_float(value=eval_result.confidence),
        "evidence": [str(e) for e in eval_result.evidence],
        "rationale": eval_result.rationale,
    }


def _serialize_tool_call(*, tool_call: ToolCall, nodeid: str) -> dict[str, Any]:
    """Serialize a ToolCall to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "name": tool_call.name,
        "arguments": _sanitize_metadata(
            metadata=tool_call.arguments,
            nodeid=nodeid,
            context="tool_call.arguments",
        ),
        "result": tool_call.result,
        "timestamp": _isoformat(timestamp=tool_call.timestamp),
    }


def _serialize_side_effect(
    *,
    side_effect: SideEffect,
    nodeid: str,
) -> dict[str, Any]:
    """Serialize a SideEffect to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "kind": side_effect.kind,
        "details": _sanitize_metadata(
            metadata=side_effect.details,
            nodeid=nodeid,
            context="side_effect.details",
        ),
    }


def _serialize_payload(*, payload: Payload, nodeid: str) -> dict[str, Any]:
    """Serialize a Payload to a JSON-safe dict.

    The artifact path (if any) is converted to a string for display
    only; the controller never accesses worker-local files.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "content": payload.content,
        "id": payload.id,
        "format": payload.format.value,
        "artifact": str(payload.artifact) if payload.artifact is not None else None,
        "metadata": _sanitize_metadata(
            metadata=payload.metadata,
            nodeid=nodeid,
            context="payload.metadata",
        ),
    }


def _serialize_request(*, request: Request, nodeid: str) -> dict[str, Any]:
    """Serialize a Request to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "prompt": request.prompt,
        "attachments": [
            _serialize_payload(payload=p, nodeid=nodeid) for p in request.attachments
        ],
    }


def _serialize_response(*, response: Response, nodeid: str) -> dict[str, Any]:
    """Serialize a Response to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "text": response.text,
        "tool_calls": [
            _serialize_tool_call(tool_call=tc, nodeid=nodeid)
            for tc in response.tool_calls
        ],
        "side_effects": [
            _serialize_side_effect(side_effect=se, nodeid=nodeid)
            for se in response.side_effects
        ],
        "metadata": _sanitize_metadata(
            metadata=response.metadata,
            nodeid=nodeid,
            context="response.metadata",
        ),
    }


def _serialize_turn(*, turn: Turn, nodeid: str) -> dict[str, Any]:
    """Serialize a Turn to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "request": _serialize_request(request=turn.request, nodeid=nodeid),
        "response": _serialize_response(response=turn.response, nodeid=nodeid),
        "eval_result": (
            _serialize_eval_result(eval_result=turn.eval_result)
            if turn.eval_result is not None
            else None
        ),
        "turn_number": turn.turn_number,
        "timestamp": _isoformat(timestamp=turn.timestamp),
        "driver_reasoning": turn.driver_reasoning,
    }


def _serialize_injection_record(*, injection: InjectionRecord) -> dict[str, Any]:
    """Serialize an InjectionRecord to a JSON-safe dict.

    Returns:
        dict[str, Any]: The JSON-safe representation.
    """
    return {
        "payload_id": injection.payload_id,
        "surface_name": injection.surface_name,
    }


def _serialize_result(*, result: Result, nodeid: str) -> dict[str, Any]:
    """Serialize a Result to a JSON-safe dict for the xdist transport.

    This is the full-fidelity transport projection: it round-trips back
    to a ``Result`` via :func:`_deserialize_result`, and intentionally
    differs from the flatter public report shape produced by
    ``JsonFileReportSink._serialize_result``. The two projections are
    deliberately separate (different fields, sanitization, and size
    handling) and must not be naively merged into one serializer.

    Returns:
        dict[str, Any]: The full-fidelity JSON-safe representation.
    """
    return {
        "safe": result.safe,
        "status": result.status.value,
        "summary": result.summary,
        "turns": [_serialize_turn(turn=t, nodeid=nodeid) for t in result.turns],
        "duration_seconds": _safe_float(value=result.duration_seconds),
        "harm_category": (
            str(result.harm_category) if result.harm_category is not None else None
        ),
        "strategy": result.strategy,
        "observability_level": result.observability_level.value,
        "injections": [
            _serialize_injection_record(injection=i) for i in result.injections
        ],
        "metadata": _sanitize_metadata(
            metadata=result.metadata,
            nodeid=nodeid,
            context="result.metadata",
        ),
    }


def serialize_worker_data(*, session: RampartSession) -> dict[str, Any]:
    """Serialize a worker's RampartSession state for transport to the controller.

    Produces a JSON-safe dict containing the schema version, the
    package version (for cross-version diagnostics), the worker's
    ``_results_by_nodeid`` mapping serialized to primitive types,
    and trial specs registered during collection.

    Args:
        session (RampartSession): The worker's session state.

    Returns:
        dict[str, Any]: A JSON-safe payload ready to write to
            ``config.workeroutput``.
    """
    serialized: dict[str, list[dict[str, Any]]] = {}
    for nodeid, results in session.results_by_nodeid.items():
        serialized[nodeid] = [
            _serialize_result(result=r, nodeid=nodeid) for r in results
        ]
    return {
        "schema": SCHEMA_VERSION,
        "results_by_nodeid": serialized,
        "trial_specs": [
            {
                "clone_nodeid": clone_nodeid,
                "base_nodeid": spec.base_nodeid,
                "threshold": _safe_float(value=spec.threshold) or 0.0,
            }
            for clone_nodeid, spec in session.trial_specs.items()
        ],
    }


def _validate_schema(*, data: object) -> dict[str, Any]:
    """Validate that ``data`` is a worker payload of the expected schema.

    Returns:
        dict[str, Any]: The validated payload as a typed dict.

    Raises:
        SchemaVersionError: If the ``schema`` key is missing or unknown.
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict worker payload, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    schema = typed.get("schema")
    if schema is None:
        msg = "Worker payload missing required 'schema' key."
        raise SchemaVersionError(msg)
    if schema != SCHEMA_VERSION:
        msg = (
            f"Worker payload schema {schema!r} does not match "
            f"controller schema {SCHEMA_VERSION!r}; rejecting to avoid "
            "best-effort parsing of an unknown format."
        )
        raise SchemaVersionError(msg)
    return typed


def _deserialize_safety_status(*, value: object) -> SafetyStatus:
    """Deserialize a SafetyStatus enum value.

    Returns:
        SafetyStatus: The deserialized enum member.

    Raises:
        WorkerOutputError: If ``value`` is not a valid SafetyStatus.
    """
    if not isinstance(value, str):
        msg = f"Expected string for SafetyStatus, got {type(value).__name__}."
        raise WorkerOutputError(msg)
    try:
        return SafetyStatus(value)
    except ValueError as exc:
        msg = f"Unknown SafetyStatus value: {value!r}."
        raise WorkerOutputError(msg) from exc


def _deserialize_observability_level(*, value: object) -> ObservabilityLevel:
    """Deserialize an ObservabilityLevel enum value.

    Returns:
        ObservabilityLevel: The deserialized enum member.

    Raises:
        WorkerOutputError: If ``value`` is not a valid ObservabilityLevel.
    """
    if not isinstance(value, str):
        msg = f"Expected string for ObservabilityLevel, got {type(value).__name__}."
        raise WorkerOutputError(msg)
    try:
        return ObservabilityLevel(value)
    except ValueError as exc:
        msg = f"Unknown ObservabilityLevel value: {value!r}."
        raise WorkerOutputError(msg) from exc


def _deserialize_eval_outcome(*, value: object) -> EvalOutcome:
    """Deserialize an EvalOutcome enum value.

    Returns:
        EvalOutcome: The deserialized enum member.

    Raises:
        WorkerOutputError: If ``value`` is not a valid EvalOutcome.
    """
    if not isinstance(value, str):
        msg = f"Expected string for EvalOutcome, got {type(value).__name__}."
        raise WorkerOutputError(msg)
    try:
        return EvalOutcome(value)
    except ValueError as exc:
        msg = f"Unknown EvalOutcome value: {value!r}."
        raise WorkerOutputError(msg) from exc


def _deserialize_harm_category(*, value: object) -> HarmCategory | str | None:
    """Deserialize a HarmCategory enum value, plain string, or None.

    Returns:
        HarmCategory | str | None: The category, raw string, or None.

    Raises:
        WorkerOutputError: If ``value`` is neither a string nor None.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"Expected string for harm_category, got {type(value).__name__}."
        raise WorkerOutputError(msg)
    try:
        return HarmCategory(value)
    except ValueError:
        return value


def _deserialize_datetime(*, value: object) -> datetime | None:
    """Deserialize an ISO 8601 datetime string, or None.

    Returns:
        datetime | None: The parsed datetime, or None.

    Raises:
        WorkerOutputError: If ``value`` is not a valid ISO 8601 string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"Expected string for datetime, got {type(value).__name__}."
        raise WorkerOutputError(msg)
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid ISO 8601 datetime: {value!r}."
        raise WorkerOutputError(msg) from exc


def _deserialize_eval_result(*, data: object) -> EvalResult | None:
    """Deserialize an EvalResult, or None when input is None.

    Returns:
        EvalResult | None: The deserialized result, or None.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        msg = f"Expected dict for EvalResult, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    outcome = _deserialize_eval_outcome(value=typed.get("outcome"))
    raw_confidence = typed.get("confidence")
    confidence = (
        float(raw_confidence) if isinstance(raw_confidence, int | float) else 1.0
    )
    raw_evidence = typed.get("evidence", [])
    evidence_items = cast(
        "list[Any]",
        raw_evidence if isinstance(raw_evidence, list) else [],
    )
    evidence: list[str] = [_strip_ansi(text=str(e)) for e in evidence_items]
    rationale = _strip_ansi(text=str(typed.get("rationale", "")))
    return EvalResult(
        outcome=outcome,
        confidence=confidence,
        evidence=evidence,
        rationale=rationale,
    )


def _deserialize_tool_call(*, data: object) -> ToolCall:
    """Deserialize a ToolCall.

    Returns:
        ToolCall: The deserialized tool call.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for ToolCall, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_args = typed.get("arguments", {})
    arguments = _sanitize(
        value=raw_args if isinstance(raw_args, dict) else {},
        strip_ansi=True,
    )
    raw_result = typed.get("result")
    return ToolCall(
        name=str(typed.get("name", "")),
        arguments=cast("dict[str, Any]", arguments),
        result=_strip_ansi(text=str(raw_result)) if raw_result is not None else None,
        timestamp=_deserialize_datetime(value=typed.get("timestamp")),
    )


def _deserialize_side_effect(*, data: object) -> SideEffect:
    """Deserialize a SideEffect.

    Returns:
        SideEffect: The deserialized side effect.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for SideEffect, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_details = typed.get("details", {})
    details = _sanitize(
        value=raw_details if isinstance(raw_details, dict) else {},
        strip_ansi=True,
    )
    return SideEffect(
        kind=str(typed.get("kind", "")),
        details=cast("dict[str, Any]", details),
    )


def _deserialize_payload(*, data: object) -> Payload:
    """Deserialize a Payload.

    The controller never sees worker-local artifacts. Reconstructed
    payloads always use ``format=TEXT`` and ``artifact=None``; the
    original format and artifact path are preserved under namespaced
    keys in metadata for debugging.

    Returns:
        Payload: The deserialized payload.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for Payload, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_metadata = typed.get("metadata", {})
    metadata = _sanitize(
        value=raw_metadata if isinstance(raw_metadata, dict) else {},
        strip_ansi=True,
    )
    metadata_dict = cast("dict[str, Any]", metadata)
    original_format = str(typed.get("format", PayloadFormat.TEXT.value))
    if original_format != PayloadFormat.TEXT.value:
        metadata_dict.setdefault("_rampart_worker_format", original_format)
    original_artifact = typed.get("artifact")
    if original_artifact is not None:
        metadata_dict.setdefault(
            "_rampart_worker_artifact_path",
            str(original_artifact),
        )
    return Payload(
        content=_strip_ansi(text=str(typed.get("content", ""))),
        id=str(typed.get("id", "")),
        format=PayloadFormat.TEXT,
        artifact=None,
        metadata=metadata_dict,
    )


def _deserialize_request(*, data: object) -> Request:
    """Deserialize a Request, providing a fallback prompt when empty.

    Returns:
        Request: The deserialized request.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for Request, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_prompt = typed.get("prompt")
    prompt: str | None = (
        _strip_ansi(text=str(raw_prompt)) if raw_prompt is not None else None
    )
    raw_attachments = typed.get("attachments", [])
    attachment_items = cast(
        "list[Any]",
        raw_attachments if isinstance(raw_attachments, list) else [],
    )
    attachments: list[Payload] = [
        _deserialize_payload(data=p) for p in attachment_items
    ]
    if prompt is None and not attachments:
        prompt = ""
    return Request(prompt=prompt, attachments=attachments)


def _deserialize_response(*, data: object) -> Response:
    """Deserialize a Response.

    Returns:
        Response: The deserialized response.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for Response, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_tcs = typed.get("tool_calls", [])
    raw_ses = typed.get("side_effects", [])
    raw_metadata = typed.get("metadata", {})
    metadata = _sanitize(
        value=raw_metadata if isinstance(raw_metadata, dict) else {},
        strip_ansi=True,
    )
    return Response(
        text=_strip_ansi(text=str(typed.get("text", ""))),
        tool_calls=[
            _deserialize_tool_call(data=tc)
            for tc in cast("list[Any]", raw_tcs if isinstance(raw_tcs, list) else [])
        ],
        side_effects=[
            _deserialize_side_effect(data=se)
            for se in cast("list[Any]", raw_ses if isinstance(raw_ses, list) else [])
        ],
        metadata=cast("dict[str, Any]", metadata),
    )


def _deserialize_turn(*, data: object) -> Turn:
    """Deserialize a Turn.

    Returns:
        Turn: The deserialized turn.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for Turn, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_turn_number = typed.get("turn_number", 0)
    return Turn(
        request=_deserialize_request(data=typed.get("request")),
        response=_deserialize_response(data=typed.get("response")),
        eval_result=_deserialize_eval_result(data=typed.get("eval_result")),
        turn_number=int(raw_turn_number) if isinstance(raw_turn_number, int) else 0,
        timestamp=_deserialize_datetime(value=typed.get("timestamp")),
        driver_reasoning=_strip_ansi(text=str(typed.get("driver_reasoning", ""))),
    )


def _deserialize_injection_record(*, data: object) -> InjectionRecord:
    """Deserialize an InjectionRecord.

    Returns:
        InjectionRecord: The deserialized injection record.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for InjectionRecord, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_payload_id = typed.get("payload_id")
    return InjectionRecord(
        payload_id=str(raw_payload_id) if raw_payload_id is not None else None,
        surface_name=str(typed.get("surface_name", "")),
    )


def _deserialize_result(*, data: object) -> Result:
    """Deserialize a Result.

    Returns:
        Result: The deserialized result.

    Raises:
        WorkerOutputError: If ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        msg = f"Expected dict for Result, got {type(data).__name__}."
        raise WorkerOutputError(msg)
    typed = cast("dict[str, Any]", data)
    raw_turns = typed.get("turns", [])
    raw_injections = typed.get("injections", [])
    raw_metadata = typed.get("metadata", {})
    metadata = _sanitize(
        value=raw_metadata if isinstance(raw_metadata, dict) else {},
        strip_ansi=True,
    )
    raw_duration = typed.get("duration_seconds", 0.0)
    duration = (
        float(raw_duration)
        if isinstance(raw_duration, int | float) and math.isfinite(float(raw_duration))
        else 0.0
    )
    return Result(
        safe=bool(typed.get("safe", False)),
        status=_deserialize_safety_status(value=typed.get("status")),
        summary=_strip_ansi(text=str(typed.get("summary", ""))),
        turns=[
            _deserialize_turn(data=t)
            for t in cast("list[Any]", raw_turns if isinstance(raw_turns, list) else [])
        ],
        duration_seconds=duration,
        harm_category=_deserialize_harm_category(value=typed.get("harm_category")),
        strategy=str(typed.get("strategy", "")),
        observability_level=_deserialize_observability_level(
            value=typed.get("observability_level"),
        ),
        injections=[
            _deserialize_injection_record(data=i)
            for i in cast(
                "list[Any]",
                raw_injections if isinstance(raw_injections, list) else [],
            )
        ],
        metadata=cast("dict[str, Any]", metadata),
    )


def deserialize_worker_data(*, data: object) -> dict[str, list[Result]]:
    """Deserialize a worker payload back into a ``results_by_nodeid`` mapping.

    Performs strict schema validation: missing ``schema`` key, unknown
    versions, and malformed enum values all raise ``WorkerOutputError``
    (or subclass). Caller should catch and mark the run incomplete
    rather than letting the exception propagate to pytest.

    Each result's ``metadata["_pytest_nodeid"]`` and
    ``metadata["_rampart_result_index"]`` are set authoritatively from the
    outer mapping key and list position so cross-worker ordering is total
    and independent of any (untrusted) serialized values.

    Args:
        data (object): The deserialized JSON object from
            ``node.workeroutput``.

    Returns:
        dict[str, list[Result]]: Results grouped by nodeid.

    Raises:
        SchemaVersionError: Missing or unknown schema version.
        WorkerOutputError: Malformed payload (type errors, bad enums).
    """
    typed = _validate_schema(data=data)
    raw_results = typed.get("results_by_nodeid", {})
    if not isinstance(raw_results, dict):
        msg = f"Expected dict for results_by_nodeid, got {type(raw_results).__name__}."
        raise WorkerOutputError(msg)
    out: dict[str, list[Result]] = {}
    for nodeid, results_data in cast("dict[Any, Any]", raw_results).items():
        if not isinstance(results_data, list):
            continue
        nodeid_str = str(nodeid)
        deserialized: list[Result] = []
        for index, raw_result in enumerate(cast("list[Any]", results_data)):
            result = _deserialize_result(data=raw_result)
            result.metadata["_pytest_nodeid"] = nodeid_str
            result.metadata["_rampart_result_index"] = index
            deserialized.append(result)
        out[nodeid_str] = deserialized
    return out


def deserialize_trial_specs(*, data: object) -> dict[str, TrialSpec]:
    """Deserialize the ``trial_specs`` section of a worker payload.

    Missing or malformed entries are skipped rather than raised so
    that a partially-corrupt payload still merges results. The
    ``trial_specs`` field is optional: payloads without trials emit
    an empty list and this function returns an empty dict.

    Args:
        data (object): The deserialized JSON object from
            ``node.workeroutput``.

    Returns:
        dict[str, TrialSpec]: Trial specs keyed by clone node ID.

    Raises:
        SchemaVersionError: Missing or unknown schema version.
        WorkerOutputError: ``data`` is not a dict payload.
    """
    typed = _validate_schema(data=data)
    raw_specs = typed.get("trial_specs", [])
    if not isinstance(raw_specs, list):
        return {}
    out: dict[str, TrialSpec] = {}
    for spec in cast("list[Any]", raw_specs):
        if not isinstance(spec, dict):
            continue
        spec_dict = cast("dict[str, Any]", spec)
        clone_nodeid = spec_dict.get("clone_nodeid")
        base_nodeid = spec_dict.get("base_nodeid")
        if not isinstance(clone_nodeid, str) or not isinstance(base_nodeid, str):
            continue
        if not clone_nodeid or not base_nodeid:
            continue
        raw_threshold = spec_dict.get("threshold", 0.0)
        try:
            threshold = (
                float(raw_threshold)
                if isinstance(
                    raw_threshold,
                    int | float,
                )
                else 0.0
            )
        except (TypeError, ValueError):
            threshold = 0.0
        if not math.isfinite(threshold):
            threshold = 0.0
        out[clone_nodeid] = TrialSpec(
            base_nodeid=base_nodeid,
            threshold=threshold,
        )
    return out


def finalize_worker(*, config: pytest.Config, session: RampartSession) -> None:
    """Serialize the worker's session state into ``config.workeroutput``.

    Called from ``pytest_sessionfinish`` on each xdist worker. The
    worker skips sink emission entirely; the controller is responsible
    for the final report.

    Args:
        config (pytest.Config): The pytest configuration object.
        session (RampartSession): The worker's session state.

    Raises:
        SizeLimitError: If the serialized payload exceeds the
            configured cap. The truncation marker is still written to
            ``workeroutput`` before the exception is raised so the
            controller can record the run as incomplete.
    """
    if not is_xdist_worker(config=config):
        return
    payload = serialize_worker_data(session=session)
    encoded = json.dumps(payload, default=str)
    size = len(encoded.encode("utf-8"))
    limit = _size_limit(config=config)
    workeroutput = cast(
        "dict[str, Any]",
        config.workeroutput,  # ty: ignore[unresolved-attribute]
    )
    if size > limit:
        workeroutput[WORKEROUTPUT_KEY] = {
            "schema": SCHEMA_VERSION,
            _TRUNCATED_MARKER: True,
            "size_bytes": size,
            "limit_bytes": limit,
        }
        msg = (
            f"Worker payload size {size} bytes exceeds cap of {limit}; "
            f"truncated. Increase --{SIZE_LIMIT_OPTION.replace('_', '-')} "
            f"(or the {SIZE_LIMIT_OPTION} ini option) to raise the cap."
        )
        raise SizeLimitError(msg)
    logger.debug("Worker payload size: %d bytes", size)
    workeroutput[WORKEROUTPUT_KEY] = payload


def _safe_deserialize_trial_specs(
    *,
    payload: object,
    worker_id_str: str,
) -> dict[str, TrialSpec]:
    """Deserialize trial specs from a worker payload without raising.

    Trial specs are optional metadata: a corrupt or absent block must
    never block result merging. Errors are logged at warning level and
    return an empty dict.

    Args:
        payload (object): The deserialized worker payload.
        worker_id_str (str): Worker identifier for logging.

    Returns:
        dict[str, TrialSpec]: Specs keyed by clone nodeid (possibly empty).
    """
    try:
        return deserialize_trial_specs(data=payload)
    except WorkerOutputError as exc:
        logger.warning(
            "Failed to deserialize trial specs from worker %s: %s",
            worker_id_str,
            exc,
        )
        return {}


def _tag_source_worker(
    *,
    results_by_nodeid: dict[str, list[Result]],
    worker_id_str: str,
) -> None:
    """Tag each merged result with the worker it came from.

    Used as the final ordering tie-breaker so the same nodeid arriving
    from multiple workers (e.g. ``--dist=each``) stays totally ordered.

    Args:
        results_by_nodeid (dict[str, list[Result]]): The deserialized
            worker results to tag in place.
        worker_id_str (str): The originating worker identifier.
    """
    for results in results_by_nodeid.values():
        for result in results:
            result.metadata["_rampart_source_worker"] = worker_id_str


def handle_testnodedown(
    *,
    session: RampartSession,
    node: object,
    error: object,
) -> None:
    """Merge a finished worker's results into the controller session.

    Called from ``pytest_testnodedown`` on the controller for each
    worker that completes. Failures (missing payload, deserialization
    errors, worker crashes) are recorded via ``mark_incomplete`` rather
    than raised, so a single bad worker does not abort report emission.

    Args:
        session (RampartSession): The controller's session state.
        node: The xdist node object (has ``workeroutput`` attribute).
        error: The shutdown error from xdist, or None on clean exit.
    """
    worker_id = getattr(node, "gateway", None)
    worker_id_str = str(getattr(worker_id, "id", node)) if worker_id else str(node)
    if error is not None:
        logger.warning(
            "Worker %s reported shutdown error; report will be incomplete: %s",
            worker_id_str,
            error,
        )
        session.mark_incomplete(reason=f"worker {worker_id_str} error: {error}")
        return
    workeroutput = getattr(node, "workeroutput", None)
    if not isinstance(workeroutput, dict):
        logger.warning(
            "Worker %s exited without workeroutput; report will be incomplete.",
            worker_id_str,
        )
        session.mark_incomplete(reason=f"worker {worker_id_str} missing workeroutput")
        return
    payload: Any = cast("dict[str, Any]", workeroutput).get(WORKEROUTPUT_KEY)
    if payload is None:
        logger.warning(
            "Worker %s did not produce RAMPART output; report will be incomplete.",
            worker_id_str,
        )
        session.mark_incomplete(reason=f"worker {worker_id_str} missing RAMPART output")
        return
    typed_payload_dict: dict[str, Any] | None = (
        cast("dict[str, Any]", payload) if isinstance(payload, dict) else None
    )
    if typed_payload_dict is not None and typed_payload_dict.get(_TRUNCATED_MARKER):
        logger.error(
            "Worker %s payload was truncated due to size cap; "
            "report will be incomplete.",
            worker_id_str,
        )
        session.mark_incomplete(
            reason=f"worker {worker_id_str} payload truncated (size cap)",
        )
        return
    try:
        results_by_nodeid = deserialize_worker_data(data=cast("object", payload))
    except WorkerOutputError as exc:
        logger.exception(
            "Failed to deserialize worker %s output; report will be incomplete.",
            worker_id_str,
        )
        session.mark_incomplete(
            reason=f"worker {worker_id_str} deserialization failed: {exc}",
        )
        return
    trial_specs = _safe_deserialize_trial_specs(
        payload=cast("object", payload),
        worker_id_str=worker_id_str,
    )
    _tag_source_worker(
        results_by_nodeid=results_by_nodeid,
        worker_id_str=worker_id_str,
    )
    session.merge_worker_results(results_by_nodeid=results_by_nodeid)
    if trial_specs:
        session.merge_trial_specs(trial_specs=trial_specs)
    logger.info(
        "Merged %d result group(s) from worker %s.",
        len(results_by_nodeid),
        worker_id_str,
    )


def discover_sinks_from_conftest(*, config: pytest.Config) -> list[ReportSink]:
    """Discover ``rampart_sinks`` definitions from registered conftest modules.

    Workers run the standard ``_rampart_sink_bootstrap`` fixture to
    register sinks via pytest's fixture machinery. The controller has
    no test execution, so fixtures do not run. This function scans
    registered plugins for a module-level ``rampart_sinks`` attribute
    and resolves it:

    - If callable with zero arguments, invoke it and use the return.
    - If a list, use it directly.
    - Otherwise, log a warning and skip.

    Sinks that depend on other fixtures cannot be discovered this way.
    Such configurations should register sinks via the
    ``pytest_rampart_sinks`` hook, which is resolved identically on the
    controller and in every worker.

    Args:
        config (pytest.Config): The pytest configuration object.

    Returns:
        list[ReportSink]: Discovered sinks (may be empty).
    """
    discovered: list[ReportSink] = []
    seen: set[int] = set()
    for plugin in config.pluginmanager.get_plugins():
        if plugin is None or id(plugin) in seen:
            continue
        seen.add(id(plugin))
        candidate = getattr(plugin, "rampart_sinks", None)
        if candidate is None:
            continue
        resolved = _resolve_sink_candidate(candidate=candidate, plugin=plugin)
        if resolved is None:
            continue
        for sink in resolved:
            if isinstance(sink, ReportSink):
                discovered.append(sink)
            else:
                logger.warning(
                    "rampart_sinks in %s yielded a non-ReportSink: %r",
                    getattr(plugin, "__name__", repr(plugin)),
                    sink,
                )
    return discovered


def _unwrap_fixture_function(candidate: object) -> Callable[..., object] | None:
    """Return the underlying function of a ``@pytest.fixture``-wrapped object.

    pytest >= 8.4 wraps fixtures in a ``FixtureFunctionDefinition`` whose
    ``inspect.isfunction`` is False; the real function is reachable via
    ``_get_wrapped_function()`` (with ``_fixture_function`` / ``__wrapped__``
    as fallbacks). Returns the recovered function, or None when
    ``candidate`` is not a fixture wrapper we can unwrap.
    """
    import inspect  # noqa: PLC0415

    getter = getattr(candidate, "_get_wrapped_function", None)
    if callable(getter):
        try:
            wrapped = getter()
        except Exception:  # noqa: BLE001 — defensive across pytest versions
            wrapped = None
        if inspect.isfunction(wrapped):
            return wrapped
    for attr in ("_fixture_function", "__wrapped__"):
        wrapped = getattr(candidate, attr, None)
        if inspect.isfunction(wrapped):
            return wrapped
    return None


def _resolve_sink_candidate(
    *,
    candidate: object,
    plugin: object,
) -> list[object] | None:
    """Resolve a module-level ``rampart_sinks`` attribute into a list of sinks.

    Handles three shapes:

    - A list — used directly.
    - A zero-argument plain function — called, and its list return used.
    - A ``@pytest.fixture``-wrapped *parameterless* function — unwrapped to
      its underlying function and called directly (no pytest fixture
      machinery), so the documented session-fixture fallback keeps working
      on the xdist controller.

    Any other shape — a fixture that depends on other fixtures, a callable
    requiring arguments, or a non-list return — is skipped with a warning
    pointing at the ``pytest_rampart_sinks`` hook, which works identically
    on the controller and in every worker.

    Returns:
        None on failure (logged) so the caller can continue scanning other plugins.

    Raises:
        KeyboardInterrupt: If the function is interrupted by the user.
        SystemExit: If the function attempts to exit the program.
    """
    import inspect  # noqa: PLC0415

    plugin_name = getattr(plugin, "__name__", repr(plugin))
    if isinstance(candidate, list):
        return cast("list[object]", candidate)

    func: Callable[..., object] | None
    if inspect.isfunction(candidate):
        func = candidate
    else:
        func = _unwrap_fixture_function(candidate)
    if func is None:
        logger.warning(
            "rampart_sinks in %s is %s, which controller-side discovery "
            "cannot resolve. Register sinks via the pytest_rampart_sinks "
            "hook instead.",
            plugin_name,
            type(candidate).__name__,
        )
        return None

    sig = inspect.signature(func)
    if len(sig.parameters) > 0:
        logger.warning(
            "rampart_sinks in %s requires arguments (%s); controller-side "
            "discovery cannot satisfy those. Use the pytest_rampart_sinks "
            "hook, or provide a parameterless function or a list.",
            plugin_name,
            list(sig.parameters),
        )
        return None

    try:
        value = func()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001 — broad on purpose: user code
        logger.warning(
            "rampart_sinks in %s raised during controller-side discovery: %s",
            plugin_name,
            exc,
        )
        return None

    if isinstance(value, list):
        return cast("list[object]", value)
    logger.warning(
        "rampart_sinks in %s returned %s instead of list[ReportSink].",
        plugin_name,
        type(value).__name__,
    )
    return None
