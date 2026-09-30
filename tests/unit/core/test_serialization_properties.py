# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Generated round-trips over the canonical trace value domain."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta, timezone
from typing import TYPE_CHECKING, Any

from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
    PopulationRef,
    Result,
    SafetyStatus,
)
from rampart.core.serialization import (
    ResultRecord,
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
    from datetime import datetime

    from hypothesis.strategies import DrawFn, SearchStrategy


def _json_maps() -> SearchStrategy[dict[str, Any]]:
    values = st.recursive(
        st.none()
        | st.booleans()
        | st.integers(min_value=-(2**128), max_value=2**128)
        | st.floats(allow_nan=False, allow_infinity=False)
        | st.text(max_size=40),
        lambda children: (
            st.lists(children, max_size=4)
            | st.dictionaries(st.text(max_size=20), children, max_size=4)
        ),
        max_leaves=10,
    )
    return st.dictionaries(st.text(max_size=20), values, max_size=4)


def _timestamps() -> SearchStrategy[datetime | None]:
    zones = st.none() | st.integers(-86399, 86399).map(
        lambda seconds: timezone(timedelta(seconds=seconds))
    )
    return st.none() | st.datetimes(timezones=zones)


def _payloads() -> SearchStrategy[Payload]:
    return st.builds(
        Payload,
        content=st.text(max_size=100),
        id=st.text(max_size=30),
        format=st.sampled_from([value for value in PayloadFormat if value.is_text]),
        metadata=_json_maps(),
    )


def _requests() -> SearchStrategy[Request]:
    return st.one_of(
        st.builds(
            Request,
            prompt=st.text(max_size=100),
            attachments=st.lists(_payloads(), max_size=2),
        ),
        st.builds(
            Request,
            prompt=st.none(),
            attachments=st.lists(_payloads(), min_size=1, max_size=2),
        ),
    )


def _responses() -> SearchStrategy[Response]:
    calls = st.builds(
        ToolCall,
        name=st.text(max_size=30),
        arguments=_json_maps(),
        result=st.none() | st.text(max_size=100),
        timestamp=_timestamps(),
    )
    effects = st.builds(SideEffect, kind=st.text(max_size=30), details=_json_maps())
    return st.builds(
        Response,
        text=st.text(max_size=100),
        tool_calls=st.lists(calls, max_size=2),
        side_effects=st.lists(effects, max_size=2),
        metadata=_json_maps(),
    )


def _evaluations() -> SearchStrategy[EvalResult]:
    return st.builds(
        EvalResult,
        outcome=st.sampled_from(EvalOutcome),
        confidence=st.floats(min_value=0, max_value=1),
        evidence=st.lists(st.text(max_size=30), max_size=3),
        rationale=st.text(max_size=50),
        undetermined_operands=st.lists(st.text(max_size=30), max_size=3),
    )


@st.composite
def _turns(draw: DrawFn) -> Turn:
    evaluation = draw(st.none() | _evaluations())
    purpose = st.none() | st.sampled_from(EvaluationPurpose)
    return draw(
        st.builds(
            Turn,
            request=_requests(),
            response=_responses(),
            eval_result=st.just(evaluation),
            eval_purpose=st.none() if evaluation is None else purpose,
            turn_number=st.integers(min_value=0, max_value=100),
            timestamp=_timestamps(),
            driver_reasoning=st.text(max_size=50),
        )
    )


def _results() -> SearchStrategy[Result]:
    injections = st.builds(
        InjectionRecord,
        payload_id=st.none() | st.text(max_size=30),
        surface_name=st.text(max_size=30),
    )
    populations = st.builds(
        PopulationRef,
        id=st.text(min_size=1, max_size=30),
        index=st.integers(min_value=0, max_value=9),
        size=st.just(10),
        threshold=st.floats(min_value=0, max_value=1),
    )
    return st.builds(
        Result,
        status=st.sampled_from(SafetyStatus),
        summary=st.text(max_size=100),
        observability_level=st.sampled_from(ObservabilityLevel),
        final_trace_evaluation=st.none() | _evaluations(),
        turns=st.lists(_turns(), max_size=3),
        trace_end_reason=st.none() | st.sampled_from(TraceEndReason),
        duration_seconds=st.floats(min_value=0, allow_infinity=False),
        harm_category=st.none() | st.text(max_size=30) | st.sampled_from(HarmCategory),
        strategy=st.text(max_size=30),
        injections=st.lists(injections, max_size=2),
        population=st.none() | populations,
        metadata=_json_maps(),
    )


class TestGeneratedRoundTrips:
    @given(
        terminal=_evaluations(),
        online=_evaluations(),
        reason=st.sampled_from(TraceEndReason),
        purpose=st.none() | st.sampled_from(EvaluationPurpose),
    )
    def test_both_evaluation_placements_and_provenance_round_trip(
        self,
        *,
        terminal: EvalResult,
        online: EvalResult,
        reason: TraceEndReason,
        purpose: EvaluationPurpose | None,
    ) -> None:
        record = ResultRecord(
            result=Result(
                status=SafetyStatus.SAFE,
                summary="recorded trace",
                observability_level=ObservabilityLevel.RESPONSE_ONLY,
                final_trace_evaluation=terminal,
                trace_end_reason=reason,
                turns=[
                    Turn(
                        request=Request(prompt="request"),
                        response=Response(text="response"),
                        eval_result=online,
                        eval_purpose=purpose,
                    )
                ],
            )
        )

        encoded = serialize_record(record=record)
        restored = deserialize_record(data=encoded)

        assert restored == record
        assert restored.result.final_trace_evaluation == terminal
        assert restored.result.turns[0].eval_result == online
        assert restored.result.trace_end_reason is reason
        assert restored.result.turns[0].eval_purpose is purpose
        assert serialize_record(record=restored) == encoded
        Draft202012Validator(ResultRecord.json_schema()).validate(json.loads(encoded))

    @given(
        result=_results(),
        nodeid=st.none() | st.text(max_size=40),
        index=st.none() | st.integers(min_value=0, max_value=100),
    )
    def test_record_round_trip_matches_the_structural_schema(
        self, *, result: Result, nodeid: str | None, index: int | None
    ) -> None:
        result = replace(
            result,
            metadata={
                **result.metadata,
                "_rampart_source_worker": "gw0",
                "_pytest_nodeid": "private",
                "_rampart_transport_truncated": True,
            },
        )
        record = ResultRecord(result=result, pytest_nodeid=nodeid, result_index=index)
        original = deepcopy(record)
        encoded = serialize_record(record=record)
        body = json.loads(encoded)

        restored = deserialize_record(data=encoded)

        assert restored.result == result
        assert restored.pytest_nodeid == nodeid
        assert restored.result_index == index
        assert serialize_record(record=restored) == encoded
        assert serialize_record(record=record) == encoded
        assert record == original
        Draft202012Validator(ResultRecord.json_schema()).validate(body)
