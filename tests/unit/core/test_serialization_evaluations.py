# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Canonical policies for terminal and online trace evaluations."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter

from rampart.core.result import Result, SafetyStatus
from rampart.core.serialization import (
    ResultRecord,
    SchemaError,
    _result_adapter,
    deserialize_record,
    serialize_record,
)
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    EvaluationPurpose,
    ObservabilityLevel,
    Request,
    Response,
    TraceEndReason,
    Turn,
)


def _make_result() -> Result:
    return Result(
        status=SafetyStatus.SAFE,
        summary="terminal and online evidence remain independent",
        observability_level=ObservabilityLevel.RESPONSE_ONLY,
        terminal_evaluation=EvalResult(outcome=EvalOutcome.NOT_DETECTED),
        turns=[
            Turn(
                request=Request(prompt="request"),
                response=Response(text="response"),
                eval_result=EvalResult(outcome=EvalOutcome.DETECTED),
                eval_purpose=EvaluationPurpose.STOP_CHECK,
            ),
        ],
        trace_end_reason=TraceEndReason.STOP_CONDITION_MET,
    )


def _evaluation(*, result: Result, terminal: bool) -> EvalResult:
    evaluation = result.terminal_evaluation if terminal else result.turns[0].eval_result
    assert evaluation is not None
    return evaluation


def _wire_evaluation(*, data: dict[str, Any], terminal: bool) -> dict[str, Any]:
    result = data["result"]
    return (
        result["terminal_evaluation"] if terminal else result["turns"][0]["eval_result"]
    )


def _evaluation_path(*, terminal: bool, field: str) -> str:
    placement = r"terminal_evaluation" if terminal else r"turns\[0\]\.eval_result"
    return rf"result.*{placement}\.{field}"


@pytest.mark.parametrize("terminal", [True, False], ids=["terminal", "online"])
class TestEvaluationPlacement:
    @pytest.mark.parametrize(
        ("field", "invalid"),
        [
            ("outcome", "unknown"),
            ("outcome", True),
            ("confidence", True),
            ("confidence", "0.5"),
            ("rationale", 1),
            ("rationale", None),
            ("evidence", [1]),
            ("evidence", "not a list"),
            ("undetermined_operands", [False]),
            ("undetermined_operands", "not a list"),
        ],
    )
    def test_strict_types_apply_to_both_boundaries(
        self, *, terminal: bool, field: str, invalid: object
    ) -> None:
        result = _make_result()
        data = json.loads(serialize_record(record=ResultRecord(result=result)))
        _wire_evaluation(data=data, terminal=terminal)[field] = invalid
        setattr(_evaluation(result=result, terminal=terminal), field, invalid)
        path = _evaluation_path(terminal=terminal, field=field)

        with pytest.raises(SchemaError, match=path):
            serialize_record(record=ResultRecord(result=result))
        with pytest.raises(SchemaError, match=path):
            deserialize_record(data=json.dumps(data))
        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)

    def test_live_outcome_requires_an_enum_instance(self, *, terminal: bool) -> None:
        result = _make_result()
        _evaluation(result=result, terminal=terminal).__dict__["outcome"] = "detected"

        with pytest.raises(
            SchemaError, match=_evaluation_path(terminal=terminal, field="outcome")
        ):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize("confidence", [math.nan, math.inf, -math.inf])
    def test_nonfinite_confidence_is_rejected_before_json_rendering(
        self, *, terminal: bool, confidence: float
    ) -> None:
        result = _make_result()
        _evaluation(result=result, terminal=terminal).confidence = confidence

        with pytest.raises(
            SchemaError, match=_evaluation_path(terminal=terminal, field="confidence")
        ):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize("number", ["1e400", "-1e400"])
    def test_overflowing_json_confidence_is_rejected(
        self, *, terminal: bool, number: str
    ) -> None:
        data = json.loads(serialize_record(record=ResultRecord(result=_make_result())))
        _wire_evaluation(data=data, terminal=terminal)["confidence"] = "overflow"
        encoded = json.dumps(data).replace('"overflow"', number)

        with pytest.raises(
            SchemaError, match=_evaluation_path(terminal=terminal, field="confidence")
        ):
            deserialize_record(data=encoded)

    @pytest.mark.parametrize(
        "field", ["rationale", "evidence", "undetermined_operands"]
    )
    @pytest.mark.parametrize(
        "text", [chr(0xD800), chr(0xDFFF), chr(0xD83D) + chr(0xDE00)]
    )
    def test_surrogate_strings_are_rejected_on_encode(
        self, *, terminal: bool, field: str, text: str
    ) -> None:
        result = _make_result()
        value = text if field == "rationale" else [text]
        setattr(_evaluation(result=result, terminal=terminal), field, value)

        with pytest.raises(
            SchemaError,
            match=_evaluation_path(terminal=terminal, field=field) + ".*surrogate",
        ):
            serialize_record(record=ResultRecord(result=result))

    @pytest.mark.parametrize(
        "field", ["rationale", "evidence", "undetermined_operands"]
    )
    @pytest.mark.parametrize("text", [chr(0xD800), chr(0xDFFF)])
    def test_unpaired_json_surrogates_are_rejected_on_decode(
        self, *, terminal: bool, field: str, text: str
    ) -> None:
        data = json.loads(serialize_record(record=ResultRecord(result=_make_result())))
        _wire_evaluation(data=data, terminal=terminal)[field] = (
            text if field == "rationale" else [text]
        )

        with pytest.raises(
            SchemaError,
            match=_evaluation_path(terminal=terminal, field=field) + ".*surrogate",
        ):
            deserialize_record(data=json.dumps(data))

    @pytest.mark.parametrize("outcome", list(EvalOutcome))
    @pytest.mark.parametrize("confidence", [0.0, 0.75, 1.0])
    def test_unicode_and_enums_round_trip_without_conflating_evaluations(
        self, *, terminal: bool, outcome: EvalOutcome, confidence: float
    ) -> None:
        result = _make_result()
        evaluation = _evaluation(result=result, terminal=terminal)
        evaluation.outcome = outcome
        evaluation.confidence = confidence
        evaluation.rationale = 'Quoted "text"\n\u00e9 \U0001f600'
        evaluation.evidence = [evaluation.rationale]
        evaluation.undetermined_operands = [evaluation.rationale]
        original = deepcopy(result)

        encoded = serialize_record(record=ResultRecord(result=result))
        restored = deserialize_record(data=encoded).result

        assert result == original == restored
        assert _evaluation(result=restored, terminal=terminal).outcome is outcome
        assert restored.terminal_evaluation is not restored.turns[0].eval_result
        Draft202012Validator(ResultRecord.json_schema()).validate(json.loads(encoded))

    def test_independent_eval_adapters_keep_their_own_policies(
        self, *, terminal: bool
    ) -> None:
        _result_adapter.cache_clear()
        regular = TypeAdapter(EvalResult)
        original_schema = regular.json_schema()
        original_core_schema = deepcopy(regular.core_schema)
        result = _make_result()
        evaluation = _evaluation(result=result, terminal=terminal)
        evaluation.rationale = "\ud800"
        evaluation.confidence = math.inf

        with pytest.raises(
            SchemaError, match=_evaluation_path(terminal=terminal, field="confidence")
        ):
            serialize_record(record=ResultRecord(result=result))
        ResultRecord.json_schema()

        data = {"outcome": "detected", "confidence": "0.5", "rationale": "\ud800"}
        for adapter in [regular, TypeAdapter(EvalResult)]:
            assert adapter.validate_python(evaluation) is evaluation
            assert adapter.validate_python(data) == EvalResult(
                outcome=EvalOutcome.DETECTED, confidence=0.5, rationale="\ud800"
            )
            assert adapter.json_schema() == original_schema
        assert regular.core_schema == original_core_schema


class TestTraceProvenance:
    @pytest.mark.parametrize("reason", [None, *TraceEndReason])
    @pytest.mark.parametrize("purpose", [None, *EvaluationPurpose])
    def test_trace_enums_round_trip(
        self, *, reason: TraceEndReason | None, purpose: EvaluationPurpose | None
    ) -> None:
        result = _make_result()
        result.trace_end_reason = reason
        result.turns[0] = replace(result.turns[0], eval_purpose=purpose)

        encoded = serialize_record(record=ResultRecord(result=result))
        restored = deserialize_record(data=encoded).result

        assert restored == result
        assert restored.trace_end_reason is reason
        assert restored.turns[0].eval_purpose is purpose
        Draft202012Validator(ResultRecord.json_schema()).validate(json.loads(encoded))

    @pytest.mark.parametrize("field", ["trace_end_reason", "eval_purpose"])
    @pytest.mark.parametrize("invalid", ["unknown", 1, True, {}])
    def test_trace_enums_fail_closed_at_both_boundaries(
        self, *, field: str, invalid: object
    ) -> None:
        result = _make_result()
        data = json.loads(serialize_record(record=ResultRecord(result=result)))
        target = result if field == "trace_end_reason" else result.turns[0]
        wire = (
            data["result"]
            if field == "trace_end_reason"
            else data["result"]["turns"][0]
        )
        target.__dict__[field] = invalid
        wire[field] = invalid

        with pytest.raises(SchemaError, match=field):
            serialize_record(record=ResultRecord(result=result))
        with pytest.raises(SchemaError, match=field):
            deserialize_record(data=json.dumps(data))
        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)

    @pytest.mark.parametrize("omit", [True, False], ids=["missing", "null"])
    def test_unrecorded_provenance_is_not_inferred(self, *, omit: bool) -> None:
        data = json.loads(serialize_record(record=ResultRecord(result=_make_result())))
        for target, names in [
            (data["result"], ["terminal_evaluation", "trace_end_reason"]),
            (data["result"]["turns"][0], ["eval_purpose"]),
        ]:
            for name in names:
                if omit:
                    del target[name]
                else:
                    target[name] = None

        restored = deserialize_record(data=json.dumps(data)).result

        assert restored.terminal_evaluation is None
        assert restored.trace_end_reason is None
        assert restored.turns[0].eval_purpose is None
        assert restored.turns[0].eval_result is not None

    @pytest.mark.parametrize("omit", [True, False], ids=["missing", "null"])
    def test_purpose_without_evaluation_is_rejected_at_both_boundaries(
        self, *, omit: bool
    ) -> None:
        result = _make_result()
        data = json.loads(serialize_record(record=ResultRecord(result=result)))
        turn = data["result"]["turns"][0]
        if omit:
            del turn["eval_result"]
        else:
            turn["eval_result"] = None
        result.turns[0].__dict__["eval_result"] = None

        with pytest.raises(SchemaError, match="eval_purpose requires eval_result"):
            serialize_record(record=ResultRecord(result=result))
        with pytest.raises(SchemaError, match="eval_purpose requires eval_result"):
            deserialize_record(data=json.dumps(data))
        assert not Draft202012Validator(ResultRecord.json_schema()).is_valid(data)
