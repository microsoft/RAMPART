# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Unit tests for the canonical trace/result serializer."""

from __future__ import annotations

import json
import math
import re
from dataclasses import FrozenInstanceError, fields, replace
from datetime import (
    UTC,
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    get_type_hints,
)
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from rampart.core import types as core_types
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
    _result_adapter,
    deserialize_record,
    serialize_record,
)
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    EvaluationPurpose,
    ObservabilityLevel,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    TraceEndReason,
    Turn,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping

_TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
_AdapterType = TypeVar("_AdapterType")


def _regular_adapter(cls: type[_AdapterType]) -> TypeAdapter[_AdapterType]:
    adapter = TypeAdapter(cls)
    adapter.rebuild(_types_namespace={"datetime": datetime, "Path": Path})
    return adapter


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
        eval_purpose=EvaluationPurpose.STOP_CHECK,
        turn_number=3,
        timestamp=_TIMESTAMP,
        driver_reasoning="escalate",
    )


def _make_full_result(*, metadata: dict | None = None) -> Result:
    return Result(
        status=SafetyStatus.UNSAFE,
        summary="a violation was detected",
        observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        final_trace_evaluation=replace(
            _make_eval_result(),
            outcome=EvalOutcome.NOT_DETECTED,
            rationale="the terminal trace differs from the online check",
        ),
        turns=[_make_turn()],
        trace_end_reason=TraceEndReason.STOP_CONDITION_MET,
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


def _record_data(record: ResultRecord) -> dict[str, Any]:
    return json.loads(serialize_record(record=record))


def _freeform_maps(result: Result) -> list[MutableMapping[str, Any]]:
    return [
        result.metadata,
        result.turns[0].request.attachments[0].metadata,
        result.turns[0].response.metadata,
        result.turns[0].response.tool_calls[0].arguments,
        result.turns[0].response.side_effects[0].details,
    ]


def _nested_json_value(*, depth: int, mapping: bool) -> object:
    value: object = "leaf"
    for _ in range(depth):
        value = {"nested": value} if mapping else [value]
    return value


class TestRoundTrip:
    def test_full_result_round_trips_to_equal_value(self) -> None:
        original = ResultRecord(result=_make_full_result())
        encoded = serialize_record(record=original)

        decoded = deserialize_record(data=encoded)

        assert isinstance(encoded, str)
        assert json.loads(encoded)["version"] == TRACE_SCHEMA_VERSION
        assert decoded == original

    def test_encoding_does_not_reconstruct_the_record(self) -> None:
        record = ResultRecord(result=_make_full_result())
        with patch.object(_result_adapter(), "validate_json") as reader:
            encoded = serialize_record(record=record)

        reader.assert_not_called()
        assert deserialize_record(data=encoded) == record

    def test_version_is_stamped_on_the_record(self) -> None:
        encoded = _record_data(ResultRecord(result=_make_full_result()))

        assert encoded["version"] == TRACE_SCHEMA_VERSION
        assert ResultRecord.VERSION == "rampart.trace.v2"

    def test_serialize_record_includes_attribution(self) -> None:
        record = ResultRecord(
            result=_make_full_result(),
            pytest_nodeid="tests/test_x.py::test_x",
            result_index=2,
        )

        encoded = json.loads(serialize_record(record=record))

        assert encoded["pytest_nodeid"] == "tests/test_x.py::test_x"
        assert encoded["result_index"] == 2

    def test_serialize_record_omits_attribution_when_unset(self) -> None:
        record = ResultRecord(result=_make_full_result())

        encoded = json.loads(serialize_record(record=record))

        assert "pytest_nodeid" not in encoded
        assert "result_index" not in encoded

    @pytest.mark.parametrize("index", [None, 0, 2])
    def test_attribution_collar_round_trips(self, index: int | None) -> None:
        record = ResultRecord(
            result=_make_full_result(),
            pytest_nodeid="tests/test_x.py::test_x",
            result_index=index,
        )
        encoded = serialize_record(record=record)

        decoded = deserialize_record(data=encoded)

        assert decoded.pytest_nodeid == "tests/test_x.py::test_x"
        assert decoded.result_index == index

    def test_nested_values_survive_the_round_trip(self) -> None:
        decoded = deserialize_record(
            data=serialize_record(record=ResultRecord(result=_make_full_result()))
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
        assert turn.eval_purpose is EvaluationPurpose.STOP_CHECK
        assert decoded.final_trace_evaluation is not None
        assert decoded.final_trace_evaluation.outcome is EvalOutcome.NOT_DETECTED
        assert decoded.trace_end_reason is TraceEndReason.STOP_CONDITION_MET
        assert decoded.injections[0].surface_name == "SharePoint"
        assert decoded.population == PopulationRef(
            id="pop-1", index=0, size=5, threshold=0.8
        )

    def test_unicode_and_escaped_text_round_trip(self) -> None:
        result = _make_full_result()
        result.summary = (
            'Quoted "text"\nwith backslash \\ and Unicode \u00e9 \U0001f600'
        )
        record = ResultRecord(result=result)

        encoded = serialize_record(record=record)

        assert json.loads(encoded)["result"]["summary"] == result.summary
        assert deserialize_record(data=encoded) == record


class TestPublicApi:
    @pytest.mark.parametrize("cls", [Result, ResultRecord])
    @pytest.mark.parametrize("method", ["to_dict", "from_dict"])
    def test_dictionary_conversion_methods_are_absent(
        self, *, cls: type, method: str
    ) -> None:
        assert not hasattr(cls, method)

    def test_live_result_does_not_expose_a_json_schema(self) -> None:
        assert not hasattr(Result, "json_schema")

    def test_record_is_frozen_but_references_the_live_result(self) -> None:
        result = _make_full_result()
        record = ResultRecord(result=result)

        with pytest.raises(FrozenInstanceError, match="result"):
            record.result = _make_full_result()  # ty: ignore[invalid-assignment]

        result.summary = "updated"
        assert record.result is result
        assert _record_data(record)["result"]["summary"] == "updated"


class TestJsonTextBoundary:
    @pytest.mark.parametrize(
        "data", ["", "{", '{"version":', "{} trailing", "{'key': 1}"]
    )
    def test_malformed_json_raises_schema_error(self, data: str) -> None:
        with pytest.raises(SchemaError, match="record: invalid JSON") as error:
            deserialize_record(data=data)

        assert isinstance(error.value.__cause__, json.JSONDecodeError)

    @pytest.mark.parametrize("data", [{}, [], None, 1, b"{}"])
    def test_deserialization_requires_text(self, data: Any) -> None:
        with pytest.raises(SchemaError, match="record: expected a JSON string"):
            deserialize_record(data=data)

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_nonfinite_json_constants_are_rejected(self, value: float) -> None:
        data = json.dumps({**_minimal_record_dict(), "future": value})

        with pytest.raises(SchemaError, match=r"record: invalid JSON.*non-finite"):
            deserialize_record(data=data)

    @pytest.mark.parametrize(
        "key",
        [
            "_pytest_nodeid",
            "_pytest_test_name",
            "_rampart_result_index",
            "_rampart_source_worker",
            "_rampart_transport_truncated",
            "_rampart_original_size_bytes",
            "_rampart_limit_bytes",
            "_rampart_worker_format",
            "_rampart_worker_artifact_path",
        ],
    )
    @pytest.mark.parametrize("value", [object(), (1, 2), math.nan])
    def test_transport_metadata_uses_the_same_value_domain(
        self, *, key: str, value: object
    ) -> None:
        result = _make_full_result(
            metadata={
                key: value,
                "nested": {"_rampart_source_worker": "keep"},
            }
        )

        with pytest.raises(SchemaError, match=rf"metadata.*{key}"):
            serialize_record(record=ResultRecord(result=result))

        assert result.metadata[key] is value
        assert result.metadata["nested"] == {"_rampart_source_worker": "keep"}

    def test_serialization_rejects_non_json_values(self) -> None:
        record = ResultRecord(result=_make_full_result(metadata={"bad": math.nan}))

        with pytest.raises(SchemaError, match="metadata"):
            serialize_record(record=record)


class TestUnicodeDomain:
    _INVALID_TEXT = (
        pytest.param(chr(0xD800), id="high-surrogate"),
        pytest.param(chr(0xDFFF), id="low-surrogate"),
        pytest.param(chr(0xD83D) + chr(0xDE00), id="surrogate-pair"),
    )

    @pytest.mark.parametrize("text", _INVALID_TEXT)
    @pytest.mark.parametrize("nested", [False, True])
    def test_surrogates_in_typed_text_are_rejected_on_encode(
        self, *, text: str, nested: bool
    ) -> None:
        result = _make_full_result()
        field = "text" if nested else "summary"
        target = result.turns[0].response if nested else result
        setattr(target, field, text)
        with pytest.raises(SchemaError, match=rf"{field}.*surrogate"):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize("text", _INVALID_TEXT)
    @pytest.mark.parametrize("map_index", range(5))
    @pytest.mark.parametrize("as_key", [False, True])
    def test_surrogates_in_freeform_keys_and_values_are_rejected_on_encode(
        self, *, text: str, map_index: int, as_key: bool
    ) -> None:
        result = _make_full_result()
        _freeform_maps(result)[map_index]["nested"] = (
            {text: "value"} if as_key else {"text": text}
        )

        with pytest.raises(SchemaError, match=r"nested.*surrogate") as error:
            serialize_record(record=ResultRecord(result=result))

        assert text not in str(error.value)

    @pytest.mark.parametrize("text", _INVALID_TEXT[:2])
    @pytest.mark.parametrize("map_index", range(5))
    @pytest.mark.parametrize("as_key", [False, True])
    def test_unpaired_json_surrogates_in_freeform_maps_are_rejected(
        self, *, text: str, map_index: int, as_key: bool
    ) -> None:
        result = _make_full_result()
        placeholder = "surrogate-placeholder"
        _freeform_maps(result)[map_index]["nested"] = (
            {placeholder: "value"} if as_key else {"text": placeholder}
        )
        encoded = serialize_record(record=ResultRecord(result=result)).replace(
            json.dumps(placeholder), json.dumps(text)
        )

        with pytest.raises(SchemaError, match=r"nested.*surrogate") as error:
            deserialize_record(data=encoded)

        assert text not in str(error.value)

    @pytest.mark.parametrize("text", _INVALID_TEXT)
    def test_surrogate_attribution_is_rejected(self, text: str) -> None:
        with pytest.raises(SchemaError, match=r"record\.pytest_nodeid.*surrogate"):
            ResultRecord(result=_make_full_result(), pytest_nodeid=text)

    @pytest.mark.parametrize("text", _INVALID_TEXT[:2])
    def test_unpaired_json_surrogate_attribution_is_rejected(self, text: str) -> None:
        data = _minimal_record_dict()
        data["pytest_nodeid"] = text

        with pytest.raises(SchemaError, match=r"record\.pytest_nodeid.*surrogate"):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize("text", _INVALID_TEXT[:2])
    @pytest.mark.parametrize("nested", [False, True])
    def test_unpaired_json_surrogate_escapes_are_rejected(
        self, *, text: str, nested: bool
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        field = "text" if nested else "summary"
        target = data["result"]["turns"][0]["response"] if nested else data["result"]
        target[field] = text

        with pytest.raises(SchemaError, match=rf"{field}.*surrogate"):
            deserialize_record(data=json.dumps(data))

    def test_unicode_scalars_and_valid_json_surrogate_pairs_round_trip(self) -> None:
        text = "\u00e9\U0001f600"
        result = _make_full_result(metadata={text: text})
        result.summary = text
        record = ResultRecord(result=result, pytest_nodeid=text)

        encoded = serialize_record(record=record)

        assert r"\ud83d\ude00" in encoded
        assert deserialize_record(data=encoded) == record


class TestFieldExhaustiveness:
    def test_every_field_of_every_type_is_serialized(self) -> None:
        body = _record_data(ResultRecord(result=_make_full_result()))["result"]
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
            (EvalResult, body["final_trace_evaluation"]),
            (InjectionRecord, body["injections"][0]),
            (PopulationRef, body["population"]),
        ]

        for dataclass_type, encoded in cases:
            expected = {field.name for field in fields(dataclass_type)}
            assert expected == set(encoded), dataclass_type.__name__


class TestVersionDispatch:
    @pytest.mark.parametrize("version", ["rampart.trace.v1", "rampart.trace.v3"])
    def test_unsupported_major_fails_closed(self, version: str) -> None:
        data = {**_minimal_record_dict(), "version": version}

        with pytest.raises(UnsupportedSchemaVersionError, match=re.escape(version)):
            deserialize_record(data=json.dumps(data))

    def test_missing_version_fails_closed(self) -> None:
        with pytest.raises(UnsupportedSchemaVersionError):
            deserialize_record(data='{"result": {}}')

    @pytest.mark.parametrize("data", ["[1, 2, 3]", "null", "1", '"text"'])
    def test_non_mapping_record_fails_closed(self, data: str) -> None:
        with pytest.raises(SchemaError, match="mapping"):
            deserialize_record(data=data)


class TestMigrationTolerance:
    def test_unknown_extra_fields_decode(self) -> None:
        encoded = _record_data(ResultRecord(result=_make_full_result()))
        encoded["future_collar"] = {"anything": True}
        encoded["result"]["future_intrinsic"] = 42

        decoded = deserialize_record(data=json.dumps(encoded)).result

        assert decoded.status is SafetyStatus.UNSAFE

    def test_missing_optional_fields_use_defaults(self) -> None:
        decoded = deserialize_record(data=json.dumps(_minimal_record_dict())).result

        assert decoded.status is SafetyStatus.SAFE
        assert decoded.final_trace_evaluation is None
        assert decoded.trace_end_reason is None
        assert decoded.turns == []
        assert decoded.duration_seconds == pytest.approx(0.0)
        assert decoded.harm_category is None
        assert decoded.injections == []
        assert decoded.population is None
        assert decoded.metadata == {}

    def test_malformed_present_list_fails_closed(self) -> None:
        data = _minimal_record_dict()
        data["result"]["turns"] = "not-a-list"

        with pytest.raises(SchemaError, match=r"result\.turns"):
            deserialize_record(data=json.dumps(data))

    def test_incomplete_population_reference_fails_closed(self) -> None:
        data = _minimal_record_dict()
        data["result"]["population"] = {}

        with pytest.raises(SchemaError, match=r"result\.population\.id"):
            deserialize_record(data=json.dumps(data))


class TestValueDomain:
    def test_transport_metadata_is_preserved(self) -> None:
        result = _make_full_result(
            metadata={
                "_pytest_nodeid": "x::y",
                "_pytest_test_name": "y",
                "_rampart_result_index": 0,
                "_rampart_source_worker": "gw0",
                "_rampart_transport_truncated": True,
                "_rampart_original_size_bytes": 4097,
                "_rampart_limit_bytes": 4096,
                "_rampart_worker_format": "pdf",
                "_rampart_worker_artifact_path": "worker.pdf",
                "note": "keep me",
            },
        )

        encoded = _record_data(ResultRecord(result=result))

        assert encoded["result"]["metadata"] == result.metadata
        assert deserialize_record(data=json.dumps(encoded)).result == result

    def test_harm_category_is_passed_through_as_string(self) -> None:
        result = _make_full_result()
        result.harm_category = "custom_product_risk"

        encoded = _record_data(ResultRecord(result=result))
        decoded = deserialize_record(data=json.dumps(encoded)).result

        assert encoded["result"]["harm_category"] == "custom_product_risk"
        assert decoded.harm_category == "custom_product_risk"

    def test_non_finite_float_fails_closed(self) -> None:
        result = _make_full_result()
        result.duration_seconds = math.inf

        with pytest.raises(SchemaError, match="duration_seconds"):
            serialize_record(record=ResultRecord(result=result))

    def test_non_json_metadata_fails_closed(self) -> None:
        result = _make_full_result(metadata={"blob": object()})

        with pytest.raises(SchemaError, match="metadata"):
            serialize_record(record=ResultRecord(result=result))

    def test_bad_enum_value_fails_closed_on_decode(self) -> None:
        data = _minimal_record_dict()
        data["result"]["status"] = "not_a_status"

        with pytest.raises(SchemaError, match="status"):
            deserialize_record(data=json.dumps(data))

    def test_non_string_harm_category_fails_closed_on_encode(self) -> None:
        result = _make_full_result()
        result.__dict__["harm_category"] = 42

        with pytest.raises(SchemaError, match="harm_category"):
            serialize_record(record=ResultRecord(result=result))

    def test_non_string_harm_category_fails_closed_on_decode(self) -> None:
        data = _minimal_record_dict()
        data["result"]["harm_category"] = {"category": "custom"}

        with pytest.raises(SchemaError, match="harm_category"):
            deserialize_record(data=json.dumps(data))

    def test_boolean_result_index_fails_before_encoding(self) -> None:
        with pytest.raises(SchemaError, match="result_index"):
            ResultRecord(result=_make_full_result(), result_index=True)

    def test_negative_result_index_is_rejected(self) -> None:
        data = _minimal_record_dict()
        data["result_index"] = -1

        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
        with pytest.raises(
            SchemaError, match=r"result_index.*greater than or equal to 0"
        ):
            ResultRecord(result=_make_full_result(), result_index=-1)
        with pytest.raises(
            SchemaError, match=r"result_index.*greater than or equal to 0"
        ):
            deserialize_record(data=json.dumps(data))


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
            serialize_record(record=ResultRecord(result=result))

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
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize("payload_format", ["pdf", "docx", "text"])
    def test_artifact_is_rejected_before_filesystem_access(
        self, payload_format: str
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        payload = data["result"]["turns"][0]["request"]["attachments"][0]
        payload.update(format=payload_format, artifact="untrusted-artifact")

        with (
            patch.object(
                Path, "exists", side_effect=AssertionError("filesystem access")
            ),
            pytest.raises(SchemaError, match="artifact"),
        ):
            deserialize_record(data=json.dumps(data))

    def test_live_binary_payload_is_still_supported(self, tmp_path: Path) -> None:
        artifact = tmp_path / "doc.pdf"
        artifact.write_bytes(b"%PDF-1.4 fake")
        payload = Payload(content="doc", format=PayloadFormat.PDF, artifact=artifact)

        assert _regular_adapter(Payload).validate_python(payload) is payload
        assert payload.artifact == artifact


class TestResultAdapter:
    def test_record_preserves_nested_types_and_wire_values(self) -> None:
        original = ResultRecord(result=_make_full_result())

        encoded = serialize_record(record=original)
        body = json.loads(encoded)["result"]
        restored = deserialize_record(data=encoded)

        assert restored == original
        assert isinstance(restored.result, Result)
        turn = restored.result.turns[0]
        assert isinstance(turn, Turn)
        assert isinstance(turn.request, Request)
        assert isinstance(turn.request.attachments[0], Payload)
        assert isinstance(turn.response, Response)
        assert isinstance(turn.response.tool_calls[0], ToolCall)
        assert isinstance(turn.response.side_effects[0], SideEffect)
        assert isinstance(turn.eval_result, EvalResult)
        assert isinstance(restored.result.final_trace_evaluation, EvalResult)
        assert isinstance(restored.result.injections[0], InjectionRecord)
        assert isinstance(restored.result.population, PopulationRef)
        assert "version" not in body
        assert body["status"] == "unsafe"
        assert body["observability_level"] == "tool_and_side_effects"
        assert body["turns"][0]["request"]["attachments"][0]["format"] == "markdown"
        assert body["turns"][0]["eval_result"]["outcome"] == "detected"
        assert body["final_trace_evaluation"]["outcome"] == "not_detected"
        assert body["turns"][0]["eval_purpose"] == "stop_check"
        assert body["trace_end_reason"] == "stop_condition_met"
        assert body["turns"][0]["timestamp"] == _TIMESTAMP.isoformat()
        assert body["turns"][0]["response"]["tool_calls"][0]["timestamp"] == (
            _TIMESTAMP.isoformat()
        )

    @pytest.mark.parametrize(
        "timestamp",
        [
            _TIMESTAMP,
            _TIMESTAMP.replace(tzinfo=None),
            _TIMESTAMP.replace(tzinfo=timezone(timedelta(seconds=30))),
            _TIMESTAMP.replace(tzinfo=timezone(timedelta(hours=-5))),
        ],
    )
    def test_python_iso_datetimes_preserve_their_wire_text(
        self, timestamp: datetime
    ) -> None:
        result = _make_full_result()
        result.turns[0].__dict__["timestamp"] = timestamp
        result.turns[0].response.tool_calls[0].timestamp = timestamp

        encoded = _record_data(ResultRecord(result=result))

        assert encoded["result"]["turns"][0]["timestamp"] == timestamp.isoformat()
        assert deserialize_record(data=json.dumps(encoded)).result == result
        Draft202012Validator(
            ResultRecord.json_schema(),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(encoded)

    def test_record_preserves_metadata_without_mutation(self) -> None:
        original = _make_full_result(
            metadata={
                "_rampart_source_worker": "gw0",
                "_pytest_nodeid": "test",
                "_rampart_worker_artifact_path": "worker.pdf",
                "user": {"_rampart_source_worker": "keep"},
            }
        )
        record = ResultRecord(result=original)
        original.summary = "updated after wrapping"

        body = _record_data(record)["result"]
        body["metadata"]["user"]["extra"] = True

        assert record.result is original
        assert body["summary"] == original.summary
        assert body["metadata"] == {
            **original.metadata,
            "user": {"_rampart_source_worker": "keep", "extra": True},
        }
        assert original.metadata["user"] == {"_rampart_source_worker": "keep"}
        assert "_rampart_worker_artifact_path" in original.metadata

    def test_decoding_and_reencoding_retain_transport_metadata(self) -> None:
        data = _minimal_record_dict()
        data["result"]["metadata"] = {
            "_rampart_source_worker": "gw0",
            "_rampart_transport_truncated": True,
            "nested": {"_rampart_source_worker": "keep"},
        }

        record = deserialize_record(data=json.dumps(data))

        assert record.result.metadata == data["result"]["metadata"]
        assert _record_data(record)["result"]["metadata"] == data["result"]["metadata"]
        assert record.result.metadata == data["result"]["metadata"]

    @pytest.mark.parametrize("index", [None, 0, 2])
    def test_optional_attribution_is_not_inferred(self, index: int | None) -> None:
        record = ResultRecord(result=_make_full_result(), result_index=index)

        encoded = _record_data(record)

        assert deserialize_record(data=json.dumps(encoded)).result_index == index
        assert ("result_index" in encoded) is (index is not None)

    @pytest.mark.parametrize("nodeid", [False, 1, [], {}])
    def test_invalid_nodeid_is_rejected(self, nodeid: Any) -> None:
        data = _minimal_record_dict()
        data["pytest_nodeid"] = nodeid

        with pytest.raises(SchemaError, match="pytest_nodeid"):
            deserialize_record(data=json.dumps(data))
        with pytest.raises(SchemaError, match="pytest_nodeid"):
            ResultRecord(result=_make_full_result(), pytest_nodeid=nodeid)

    def test_nested_mutations_are_revalidated(self) -> None:
        result = _make_full_result()
        result.turns[0].response.__dict__["text"] = 42

        with pytest.raises(SchemaError, match=r"result\.turns\[0\]\.response\.text"):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize("invalid", [True, 1.5, "1"])
    def test_integer_fields_are_not_coerced(self, invalid: object) -> None:
        result = _make_full_result()
        assert result.population is not None
        result.population.__dict__["index"] = invalid

        with pytest.raises(SchemaError, match=r"result\.population\.index"):
            serialize_record(record=ResultRecord(result=result))

    def test_missing_payload_identity_is_not_generated(self) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        del data["result"]["turns"][0]["request"]["attachments"][0]["id"]

        with pytest.raises(SchemaError, match="id"):
            deserialize_record(data=json.dumps(data))

    def test_invalid_timestamp_is_rejected(self) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        data["result"]["turns"][0]["timestamp"] = "not a date"

        with pytest.raises(SchemaError, match=r"result\.turns\[0\]\.timestamp"):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize(
        "field", ["turns", "injections", "metadata", "duration_seconds"]
    )
    def test_null_is_not_a_default_for_nonnullable_fields(self, field: str) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        data["result"][field] = None

        with pytest.raises(SchemaError, match=field):
            deserialize_record(data=json.dumps(data))


class TestPopulationInvariants:
    @pytest.mark.parametrize(
        ("field", "invalid"),
        [
            ("index", -1),
            ("size", -1),
            ("size", 0),
            ("threshold", -0.1),
            ("threshold", 1.1),
        ],
    )
    def test_numeric_bounds_apply_to_both_boundaries_and_schema(
        self, *, field: str, invalid: float
    ) -> None:
        result = _make_full_result()
        record = ResultRecord(result=result)
        data = _record_data(record)
        data["result"]["population"][field] = invalid
        assert result.population is not None
        result.population.__dict__[field] = invalid

        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
        with pytest.raises(SchemaError, match=rf"population\.{field}") as error:
            serialize_record(record=record)
        assert error.value.__cause__ is not None
        with pytest.raises(SchemaError, match=rf"population\.{field}"):
            deserialize_record(data=json.dumps(data))
        assert getattr(result.population, field) == invalid

    @pytest.mark.parametrize(("index", "size"), [(1, 1), (5, 5), (6, 5)])
    def test_index_must_be_less_than_size(self, *, index: int, size: int) -> None:
        result = _make_full_result()
        data = _record_data(ResultRecord(result=result))
        assert result.population is not None
        result.population.__dict__.update(index=index, size=size)
        data["result"]["population"].update(index=index, size=size)

        Draft202012Validator(ResultRecord.json_schema()).validate(data)
        with pytest.raises(SchemaError, match=r"population.*index.*size"):
            serialize_record(record=ResultRecord(result=result))
        with pytest.raises(SchemaError, match=r"population.*index.*size"):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize(("index", "size"), [(0, 1), (0, 5), (4, 5)])
    @pytest.mark.parametrize("threshold", [0.0, 0.5, 1.0])
    def test_valid_boundaries_round_trip(
        self, *, index: int, size: int, threshold: float
    ) -> None:
        result = _make_full_result()
        result.population = PopulationRef(
            id="pop-1", index=index, size=size, threshold=threshold
        )
        record = ResultRecord(result=result, result_index=0)

        encoded = serialize_record(record=record)

        assert deserialize_record(data=encoded) == record
        Draft202012Validator(ResultRecord.json_schema()).validate(json.loads(encoded))

    def test_schema_publishes_bounds_and_cross_field_caveat(self) -> None:
        schema = ResultRecord.json_schema()
        population = schema["$defs"]["PopulationRef"]

        assert schema["properties"]["result_index"]["minimum"] == 0
        assert population["properties"]["id"]["minLength"] == 1
        assert population["properties"]["index"]["minimum"] == 0
        assert population["properties"]["size"]["minimum"] == 1
        assert population["properties"]["threshold"]["minimum"] == 0
        assert population["properties"]["threshold"]["maximum"] == 1
        assert "index to be less than size" in population["description"]

    def test_empty_id_is_rejected_by_constructor_and_both_boundaries(self) -> None:
        result = _make_full_result()
        data = _record_data(ResultRecord(result=result))
        data["result"]["population"]["id"] = ""

        with pytest.raises(ValueError, match="population id must be non-empty"):
            PopulationRef(id="", index=0, size=1, threshold=0.5)

        assert result.population is not None
        result.population.__dict__["id"] = ""
        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
        with pytest.raises(SchemaError, match=r"population\.id"):
            serialize_record(record=ResultRecord(result=result))
        with pytest.raises(SchemaError, match=r"population\.id"):
            deserialize_record(data=json.dumps(data))


class TestAdapterIsolation:
    def test_regular_adapters_preserve_constructor_valid_population_behavior(
        self,
    ) -> None:
        data = {"id": "pop-1", "index": 0, "size": 1, "threshold": 0.5}
        population = PopulationRef(**data)
        regular = _regular_adapter(PopulationRef)
        original_schema = regular.json_schema()
        assert regular.validate_python(data) == population
        result = _make_full_result()
        result.population = population
        serialize_record(record=ResultRecord(result=result))
        ResultRecord.json_schema()

        assert regular.validate_python(data) == population
        assert _regular_adapter(PopulationRef).validate_python(data) == population
        assert regular.json_schema() == original_schema
        assert _regular_adapter(PopulationRef).json_schema() == original_schema

    def test_canonical_revalidation_does_not_change_regular_instance_validation(
        self,
    ) -> None:
        result = _make_full_result()
        assert result.population is not None
        regular = _regular_adapter(PopulationRef)
        result.population.__dict__["id"] = ""

        with pytest.raises(SchemaError, match=r"population\.id"):
            serialize_record(record=ResultRecord(result=result))

        assert regular.validate_python(result.population) is result.population
        assert (
            _regular_adapter(PopulationRef).validate_python(result.population)
            is result.population
        )

    def test_cold_adapter_resolves_types_without_changing_their_module(self) -> None:
        _result_adapter.cache_clear()

        restored = deserialize_record(data=json.dumps(_minimal_record_dict()))
        serialize_record(record=restored)
        ResultRecord.json_schema()

        assert "datetime" not in vars(core_types)
        assert "Path" not in vars(core_types)

    def test_public_annotations_remain_standard_types(self) -> None:
        namespace = {"datetime": datetime, "Path": Path}
        for cls, name in [
            (Result, "metadata"),
            (Payload, "metadata"),
            (Response, "metadata"),
            (ToolCall, "arguments"),
            (SideEffect, "details"),
        ]:
            assert (
                get_type_hints(cls, localns=namespace, include_extras=True)[name]
                == (dict[str, Any])
            )
        for cls in [ToolCall, Turn]:
            assert (
                get_type_hints(cls, localns=namespace, include_extras=True)["timestamp"]
                == datetime | None
            )
        assert not hasattr(Result, "__pydantic_config__")

    def test_regular_adapters_are_unchanged_before_and_after_canonical_use(
        self,
    ) -> None:
        adapter = _regular_adapter(Result)
        original_schema = adapter.json_schema()
        result = _make_full_result(metadata={"tuple": (1, 2), "opaque": object()})

        with pytest.raises(SchemaError, match="metadata"):
            serialize_record(record=ResultRecord(result=result))
        ResultRecord.json_schema()

        assert adapter.validate_python(result) is result
        assert _regular_adapter(Result).validate_python(result) is result
        assert adapter.json_schema() == original_schema
        assert _regular_adapter(Result).json_schema() == original_schema

    def test_regular_adapter_can_still_generate_payload_ids(self) -> None:
        serialize_record(record=ResultRecord(result=_make_full_result()))

        payload = _regular_adapter(Payload).validate_python(
            {"content": "live", "metadata": {"tuple": (1, 2)}}
        )

        assert payload.id
        assert payload.metadata["tuple"] == (1, 2)

    def test_regular_adapter_retains_pydantic_datetime_behavior(self) -> None:
        result = _make_full_result()

        canonical = _record_data(ResultRecord(result=result))["result"]
        regular = _regular_adapter(Result).dump_python(result, mode="json")

        assert canonical["turns"][0]["timestamp"].endswith("+00:00")
        assert regular["turns"][0]["timestamp"].endswith("Z")

    def test_regular_adapter_can_decode_live_binary_payloads(
        self, tmp_path: Path
    ) -> None:
        artifact = tmp_path / "document.pdf"
        artifact.write_bytes(b"%PDF-1.4 fake")
        serialize_record(record=ResultRecord(result=_make_full_result()))

        payload = _regular_adapter(Payload).validate_python(
            {"content": "doc", "format": "pdf", "artifact": str(artifact)}
        )

        assert payload.format is PayloadFormat.PDF
        assert payload.artifact == artifact

    def test_reused_nested_schemas_still_validate_all_instances(self) -> None:
        result = _make_full_result()
        result.turns.append(_make_turn())
        result.turns[1].request.attachments[0].metadata["bad"] = (1, 2)

        with pytest.raises(SchemaError, match=r"turns\[1\].*metadata"):
            serialize_record(record=ResultRecord(result=result))

    def test_nested_numeric_fields_are_still_finite(self) -> None:
        result = _make_full_result()
        assert result.turns[0].eval_result is not None
        result.turns[0].eval_result.confidence = math.inf

        with pytest.raises(SchemaError, match="confidence"):
            serialize_record(record=ResultRecord(result=result))


class TestTransportPreparationBoundary:
    def test_prepared_copy_does_not_relax_the_original_record(
        self, tmp_path: Path
    ) -> None:
        artifact = tmp_path / "worker.pdf"
        artifact.write_bytes(b"%PDF-1.4 fake")
        original = _make_full_result(metadata={"tuple": (1, 2)})
        binary = Payload(
            content="document text", format=PayloadFormat.PDF, artifact=artifact
        )
        original.turns[0].request.attachments = [binary]
        with pytest.raises(SchemaError):
            serialize_record(record=ResultRecord(result=original))

        display_payload = replace(
            binary,
            format=PayloadFormat.TEXT,
            artifact=None,
            metadata={
                "_rampart_worker_format": "pdf",
                "_rampart_worker_artifact_path": str(artifact),
            },
        )
        prepared = replace(
            original,
            metadata={"tuple": [1, 2]},
            turns=[
                replace(
                    original.turns[0],
                    request=replace(
                        original.turns[0].request, attachments=[display_payload]
                    ),
                )
            ],
        )

        restored = deserialize_record(
            data=serialize_record(record=ResultRecord(result=prepared))
        ).result

        assert restored == prepared
        assert original.metadata["tuple"] == (1, 2)
        assert original.turns[0].request.attachments[0] is binary
        assert binary.format is PayloadFormat.PDF
        assert binary.artifact == artifact
        with pytest.raises(SchemaError):
            serialize_record(record=ResultRecord(result=original))


class TestJsonValueDomain:
    @pytest.mark.parametrize("map_index", range(5))
    @pytest.mark.parametrize(
        "invalid",
        [
            pytest.param((1, 2), id="tuple"),
            pytest.param(b"bytes", id="bytes"),
            pytest.param(Path("file"), id="path"),
            pytest.param(object(), id="opaque"),
            pytest.param(math.inf, id="infinity"),
            pytest.param(-math.inf, id="negative-infinity"),
            pytest.param(math.nan, id="nan"),
            pytest.param({1: "non-string key"}, id="non-string-key"),
        ],
    )
    def test_freeform_values_are_not_lossily_encoded(
        self, *, map_index: int, invalid: object
    ) -> None:
        result = _make_full_result()
        _freeform_maps(result)[map_index]["nested"] = {"bad": invalid}

        with pytest.raises(SchemaError, match="nested"):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize("number", ["1e400", "-1e400"])
    def test_overflowing_json_numbers_are_rejected(self, number: str) -> None:
        data = (
            f'{{"version": "{TRACE_SCHEMA_VERSION}", "result": {{'
            '"status": "safe", "summary": "clean", '
            '"observability_level": "response_only", '
            f'"metadata": {{"bad": {number}}}}}}}'
        )

        with pytest.raises(SchemaError, match="metadata"):
            deserialize_record(data=data)

    def test_cyclic_values_fail_with_a_field_path(self) -> None:
        result = _make_full_result()
        result.metadata["cycle"] = result.metadata

        with pytest.raises(SchemaError, match=r"metadata.*cycle"):
            serialize_record(record=ResultRecord(result=result))

    def test_supported_values_round_trip_without_mutation(self) -> None:
        metadata = {
            "values": [None, True, False, 0, -(2**80), 2**80, 1.25, "text"],
            "nested": {"list": [{"text": "hello"}]},
        }
        result = _make_full_result(metadata=metadata)

        restored = deserialize_record(
            data=serialize_record(record=ResultRecord(result=result))
        ).result
        restored.metadata["nested"]["list"][0]["text"] = "changed"

        assert result.metadata == metadata
        assert metadata["nested"]["list"][0]["text"] == "hello"
        assert restored.metadata["values"] == metadata["values"]


class TestJsonNesting:
    @pytest.mark.parametrize("depth", [2, 10])
    @pytest.mark.parametrize("mapping", [False, True])
    @pytest.mark.parametrize("map_index", range(5))
    def test_supported_nested_values_round_trip(
        self, *, depth: int, mapping: bool, map_index: int
    ) -> None:
        result = _make_full_result()
        _freeform_maps(result)[map_index]["deep"] = _nested_json_value(
            depth=depth, mapping=mapping
        )
        record = ResultRecord(result=result)

        encoded = serialize_record(record=record)
        restored = deserialize_record(data=encoded)

        assert restored == record
        assert serialize_record(record=restored) == encoded

    def test_writer_validation_recursion_error_is_wrapped(self) -> None:
        record = ResultRecord(result=_make_full_result())
        original_error = RecursionError("maximum recursion depth exceeded")
        with (
            patch.object(
                _result_adapter(), "validate_python", side_effect=original_error
            ),
            pytest.raises(
                SchemaError, match=r"cannot serialize.*RecursionError"
            ) as error,
        ):
            serialize_record(record=record)

        assert error.value.__cause__ is original_error

    @pytest.mark.parametrize(
        "original_error",
        [
            ValueError("Circular reference detected (depth exceeded)"),
            RecursionError("maximum recursion depth exceeded"),
        ],
    )
    def test_adapter_serialization_error_is_wrapped(
        self, original_error: Exception
    ) -> None:
        with (
            patch.object(_result_adapter(), "dump_python", side_effect=original_error),
            pytest.raises(
                SchemaError, match=rf"cannot serialize.*{type(original_error).__name__}"
            ) as error,
        ):
            serialize_record(record=ResultRecord(result=_make_full_result()))

        assert error.value.__cause__ is original_error

    def test_writer_json_recursion_error_is_wrapped(self) -> None:
        record = ResultRecord(result=_make_full_result())
        original_error = RecursionError("maximum recursion depth exceeded")
        with (
            patch.object(json, "dumps", side_effect=original_error),
            pytest.raises(SchemaError, match="record: cannot serialize JSON") as error,
        ):
            serialize_record(record=record)

        assert error.value.__cause__ is original_error

    @pytest.mark.parametrize("method", ["loads", "dumps"])
    def test_reader_json_recursion_error_is_wrapped(self, method: str) -> None:
        encoded = json.dumps(_minimal_record_dict())
        original_error = RecursionError("maximum recursion depth exceeded")
        with (
            patch.object(json, method, side_effect=original_error),
            pytest.raises(
                SchemaError, match="maximum recursion depth exceeded"
            ) as error,
        ):
            deserialize_record(data=encoded)

        assert error.value.__cause__ is original_error

    def test_reader_adapter_recursion_error_is_wrapped(self) -> None:
        encoded = json.dumps(_minimal_record_dict())
        original_error = RecursionError("maximum recursion depth exceeded")
        with (
            patch.object(
                _result_adapter(), "validate_json", side_effect=original_error
            ),
            pytest.raises(
                SchemaError, match="maximum recursion depth exceeded"
            ) as error,
        ):
            deserialize_record(data=encoded)

        assert error.value.__cause__ is original_error

    def test_reader_adapter_json_invalid_error_is_wrapped(self) -> None:
        encoded = json.dumps(_minimal_record_dict())
        original_error = ValidationError.from_exception_data(
            "Result",
            [
                {
                    "type": "json_invalid",
                    "loc": (),
                    "input": encoded,
                    "ctx": {"error": "recursion limit exceeded"},
                }
            ],
        )
        with (
            patch.object(
                _result_adapter(), "validate_json", side_effect=original_error
            ),
            pytest.raises(
                SchemaError, match="result: Invalid JSON: recursion limit exceeded"
            ) as error,
        ):
            deserialize_record(data=encoded)

        assert error.value.__cause__ is original_error


class TestGeneratedSchema:
    def test_generated_schema_is_valid(self) -> None:
        schema = ResultRecord.json_schema()

        Draft202012Validator.check_schema(schema)

        assert schema["properties"]["version"]["const"] == TRACE_SCHEMA_VERSION

    def test_schema_omits_runtime_class_documentation(self) -> None:
        schema = ResultRecord.json_schema()

        assert "description" not in schema["properties"]["result"]
        assert "description" not in schema["$defs"]["SafetyStatus"]
        assert "not supported" in schema["$defs"]["Payload"]["description"]
        assert "Args:" not in json.dumps(schema)

    @pytest.mark.parametrize(
        ("path", "value"),
        [
            (("result_index",), 0.0),
            (("result", "population", "index"), 0.0),
            (("result", "turns", 0, "timestamp"), "not-a-date"),
        ],
    )
    def test_structural_validation_does_not_replace_decoder_semantics(
        self, *, path: tuple[str | int, ...], value: object
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        parent: Any = data
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = value
        validator = Draft202012Validator(
            ResultRecord.json_schema(),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )

        validator.validate(data)
        with pytest.raises(SchemaError, match=re.escape(str(path[-1]))):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize("payload_format", list(PayloadFormat))
    def test_schema_and_decoder_agree_on_payload_formats(
        self, payload_format: PayloadFormat
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        data["result"]["turns"][0]["request"]["attachments"][0]["format"] = (
            payload_format.value
        )
        validator = Draft202012Validator(ResultRecord.json_schema())

        assert validator.is_valid(data) is payload_format.is_text
        if payload_format.is_text:
            assert (
                deserialize_record(data=json.dumps(data))
                .result.turns[0]
                .request.attachments
            )
        else:
            with pytest.raises(SchemaError, match="binary payload"):
                deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize("full", [False, True])
    def test_full_and_minimal_records_conform(self, *, full: bool) -> None:
        data = (
            json.loads(
                serialize_record(
                    record=ResultRecord(result=_make_full_result(), result_index=0)
                )
            )
            if full
            else _minimal_record_dict()
        )
        validator = Draft202012Validator(
            ResultRecord.json_schema(),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )

        validator.validate(data)
        validator.validate(_record_data(deserialize_record(data=json.dumps(data))))

    def test_unknown_additive_fields_are_allowed_at_every_level(self) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        body = data["result"]
        turn = body["turns"][0]
        objects = [
            data,
            body,
            turn,
            turn["request"],
            turn["request"]["attachments"][0],
            turn["response"],
            turn["response"]["tool_calls"][0],
            turn["response"]["side_effects"][0],
            turn["eval_result"],
            body["final_trace_evaluation"],
            body["injections"][0],
            body["population"],
        ]
        for item in objects:
            item["future"] = {"recorded": True}

        Draft202012Validator(ResultRecord.json_schema()).validate(data)
        assert deserialize_record(data=json.dumps(data)).result == _make_full_result()

    @pytest.mark.parametrize(
        ("path", "invalid"),
        [
            (("result", "summary"), 123),
            (("result", "population", "index"), True),
            (("result", "population", "threshold"), "0.8"),
            (("result", "turns", 0, "request", "prompt"), 123),
            (("result", "turns", 0, "timestamp"), False),
            (("result", "turns", 0, "response", "text"), None),
            (("result", "turns", 0, "response", "tool_calls", 0, "result"), 123),
            (("result", "turns", 0, "request", "attachments", 0, "artifact"), "file"),
            (("result", "turns", 0, "request", "attachments", 0, "format"), "unknown"),
            (("result", "turns", 0, "eval_result", "outcome"), "unknown"),
            (("result", "final_trace_evaluation", "outcome"), "unknown"),
            (("result", "trace_end_reason"), "unknown"),
            (("result", "turns", 0, "eval_purpose"), "unknown"),
            (("result", "injections", 0, "payload_id"), 123),
            (("pytest_nodeid",), 123),
            (("result_index",), True),
        ],
    )
    def test_schema_and_decoder_reject_malformed_fields(
        self, *, path: tuple[str | int, ...], invalid: object
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        parent: Any = data
        for key in path[:-1]:
            parent = parent[key]
        parent[path[-1]] = invalid

        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
        with pytest.raises(SchemaError, match=re.escape(str(path[-1]))):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize(
        ("prompt", "attachments", "valid"),
        [
            (None, False, False),
            ("", False, True),
            ("text", False, True),
            (None, True, True),
        ],
    )
    def test_request_invariant_is_in_schema(
        self, *, prompt: str | None, attachments: bool, valid: bool
    ) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        request = data["result"]["turns"][0]["request"]
        request["prompt"] = prompt
        if not attachments:
            request["attachments"] = []

        assert Draft202012Validator(ResultRecord.json_schema()).is_valid(data) is valid
        if valid:
            deserialize_record(data=json.dumps(data))
        else:
            with pytest.raises(SchemaError, match="request"):
                deserialize_record(data=json.dumps(data))

    def test_schema_requires_recorded_payload_id(self) -> None:
        data = _record_data(ResultRecord(result=_make_full_result()))
        del data["result"]["turns"][0]["request"]["attachments"][0]["id"]

        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
