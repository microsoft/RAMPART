# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Unit tests for the canonical trace/result serializer."""

from __future__ import annotations

import math
from dataclasses import fields
from datetime import UTC, datetime

import pytest

from rampart.core.result import (
    InjectionRecord,
    PopulationRef,
    Result,
    SafetyStatus,
)
from rampart.core.serialization import (
    TRACE_SCHEMA_VERSION,
    ResultRecord,
    SchemaError,
    UnsupportedSchemaVersionError,
    deserialize_result,
    serialize_result,
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

_TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _make_eval_result() -> EvalResult:
    return EvalResult(
        outcome=EvalOutcome.DETECTED,
        confidence=0.75,
        evidence=["saw the thing", "and another"],
        rationale="because reasons",
        undetermined_operands=["left operand undetermined"],
    )


def _make_turn() -> Turn:
    request = Request(
        prompt="do the thing",
        attachments=[
            Payload(
                content="poisoned doc text",
                id="payload-1",
                format=PayloadFormat.MARKDOWN,
                metadata={"persona": "attacker"},
            ),
        ],
    )
    response = Response(
        text="agent said this",
        tool_calls=[
            ToolCall(
                name="send_email",
                arguments={"to": "a@b.com", "nested": {"count": 2}},
                result="ok",
                timestamp=_TIMESTAMP,
            ),
        ],
        side_effects=[SideEffect(kind="http_request", details={"url": "http://x"})],
        metadata={"latency_ms": 12},
    )
    return Turn(
        request=request,
        response=response,
        eval_result=_make_eval_result(),
        turn_number=3,
        timestamp=_TIMESTAMP,
        driver_reasoning="escalate",
    )


def _make_full_result(*, metadata: dict | None = None) -> Result:
    return Result(
        status=SafetyStatus.UNSAFE,
        summary="a violation was detected",
        observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        turns=[_make_turn()],
        duration_seconds=1.5,
        harm_category="prompt_injection",
        strategy="xpia",
        injections=[InjectionRecord(payload_id="payload-1", surface_name="SharePoint")],
        population=PopulationRef(id="pop-1", index=0, size=5, threshold=0.8),
        metadata={"note": "user data", "nested": {"k": [1, 2]}}
        if metadata is None
        else metadata,
    )


def _minimal_record_dict() -> dict:
    return {
        "version": TRACE_SCHEMA_VERSION,
        "result": {
            "status": "safe",
            "summary": "clean",
            "observability_level": "response_only",
        },
    }


class TestRoundTrip:
    def test_full_result_round_trips_to_equal_value(self) -> None:
        original = _make_full_result()
        encoded = ResultRecord(result=original).to_dict()

        decoded = deserialize_result(data=encoded).result

        assert decoded == original

    def test_version_is_stamped_on_the_record(self) -> None:
        encoded = ResultRecord(result=_make_full_result()).to_dict()

        assert encoded["version"] == TRACE_SCHEMA_VERSION
        assert ResultRecord.VERSION == "rampart.trace.v1"

    def test_serialize_result_builds_identity_collar(self) -> None:
        encoded = serialize_result(
            result=_make_full_result(),
            identity="auto:mod::test",
            origin="derived",
            case_id="case-0",
            pytest_nodeid="tests/test_x.py::test_x",
            result_index=2,
        )

        assert encoded["identity"] == {
            "value": "auto:mod::test",
            "origin": "derived",
            "case_id": "case-0",
        }
        assert encoded["pytest_nodeid"] == "tests/test_x.py::test_x"
        assert encoded["result_index"] == 2

    def test_serialize_result_omits_identity_when_unset(self) -> None:
        encoded = serialize_result(result=_make_full_result())

        assert encoded["identity"] is None

    def test_nested_values_survive_the_round_trip(self) -> None:
        decoded = deserialize_result(
            data=ResultRecord(result=_make_full_result()).to_dict()
        ).result

        turn = decoded.turns[0]
        assert turn.request.attachments[0].format is PayloadFormat.MARKDOWN
        assert turn.response.tool_calls[0].arguments == {
            "to": "a@b.com",
            "nested": {"count": 2},
        }
        assert turn.response.tool_calls[0].timestamp == _TIMESTAMP
        assert turn.response.side_effects[0].kind == "http_request"
        assert turn.eval_result is not None
        assert turn.eval_result.outcome is EvalOutcome.DETECTED
        assert decoded.injections[0].surface_name == "SharePoint"
        assert decoded.population == PopulationRef(
            id="pop-1", index=0, size=5, threshold=0.8
        )


class TestFieldExhaustiveness:
    def test_every_field_of_every_type_is_serialized(self) -> None:
        body = ResultRecord(result=_make_full_result()).to_dict()["result"]
        turn = body["turns"][0]

        cases = [
            (Result, body),
            (Turn, turn),
            (Request, turn["request"]),
            (Payload, turn["request"]["attachments"][0]),
            (Response, turn["response"]),
            (ToolCall, turn["response"]["tool_calls"][0]),
            (SideEffect, turn["response"]["side_effects"][0]),
            (EvalResult, turn["eval_result"]),
            (InjectionRecord, body["injections"][0]),
            (PopulationRef, body["population"]),
        ]

        for dataclass_type, encoded in cases:
            expected = {field.name for field in fields(dataclass_type)}
            assert expected == set(encoded), dataclass_type.__name__


class TestVersionDispatch:
    def test_unknown_major_fails_closed(self) -> None:
        data = {"version": "rampart.trace.v2", "result": {}}

        with pytest.raises(UnsupportedSchemaVersionError, match="v2"):
            deserialize_result(data=data)

    def test_missing_version_fails_closed(self) -> None:
        with pytest.raises(UnsupportedSchemaVersionError):
            deserialize_result(data={"result": {}})

    def test_non_mapping_record_fails_closed(self) -> None:
        with pytest.raises(SchemaError, match="mapping"):
            deserialize_result(data=[1, 2, 3])


class TestMigrationTolerance:
    def test_unknown_extra_fields_decode(self) -> None:
        encoded = ResultRecord(result=_make_full_result()).to_dict()
        encoded["future_collar"] = {"anything": True}
        encoded["result"]["future_intrinsic"] = 42

        decoded = deserialize_result(data=encoded).result

        assert decoded.status is SafetyStatus.UNSAFE

    def test_missing_optional_fields_use_defaults(self) -> None:
        decoded = deserialize_result(data=_minimal_record_dict()).result

        assert decoded.status is SafetyStatus.SAFE
        assert decoded.turns == []
        assert decoded.duration_seconds == pytest.approx(0.0)
        assert decoded.harm_category is None
        assert decoded.injections == []
        assert decoded.population is None
        assert decoded.metadata == {}


class TestValueDomain:
    def test_reserved_metadata_keys_are_stripped(self) -> None:
        result = _make_full_result(
            metadata={"_pytest_nodeid": "x::y", "note": "keep me"},
        )

        encoded = ResultRecord(result=result).to_dict()

        assert encoded["result"]["metadata"] == {"note": "keep me"}

    def test_harm_category_is_passed_through_as_string(self) -> None:
        result = _make_full_result()
        result.harm_category = "custom_product_risk"

        encoded = ResultRecord(result=result).to_dict()
        decoded = deserialize_result(data=encoded).result

        assert encoded["result"]["harm_category"] == "custom_product_risk"
        assert decoded.harm_category == "custom_product_risk"

    def test_non_finite_float_fails_closed(self) -> None:
        result = _make_full_result()
        result.duration_seconds = math.inf

        with pytest.raises(SchemaError, match="duration_seconds"):
            ResultRecord(result=result).to_dict()

    def test_non_json_metadata_fails_closed(self) -> None:
        result = _make_full_result(metadata={"blob": object()})

        with pytest.raises(SchemaError, match="metadata"):
            ResultRecord(result=result).to_dict()

    def test_bad_enum_value_fails_closed_on_decode(self) -> None:
        data = _minimal_record_dict()
        data["result"]["status"] = "not_a_status"

        with pytest.raises(SchemaError, match="status"):
            deserialize_result(data=data)


class TestBinaryPayloadFailsClosed:
    def test_encoding_a_binary_payload_fails_closed(self, tmp_path) -> None:
        artifact = tmp_path / "doc.pdf"
        artifact.write_bytes(b"%PDF-1.4 fake")
        result = _make_full_result()
        result.turns = [
            Turn(
                request=Request(
                    attachments=[
                        Payload(
                            content="binary doc",
                            format=PayloadFormat.PDF,
                            artifact=artifact,
                        ),
                    ],
                ),
                response=Response(text="ok"),
            ),
        ]

        with pytest.raises(SchemaError, match="binary payload"):
            ResultRecord(result=result).to_dict()

    def test_decoding_a_binary_payload_fails_closed(self) -> None:
        data = _minimal_record_dict()
        data["result"]["turns"] = [
            {
                "request": {
                    "prompt": None,
                    "attachments": [{"content": "x", "id": "p", "format": "pdf"}],
                },
                "response": {"text": "ok"},
            },
        ]

        with pytest.raises(SchemaError, match="binary payload"):
            deserialize_result(data=data)
