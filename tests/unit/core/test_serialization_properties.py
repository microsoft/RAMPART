# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Generated round-trips over the canonical trace value domain."""

from __future__ import annotations

import json
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
    from datetime import datetime

    from hypothesis.strategies import SearchStrategy


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


def _turns() -> SearchStrategy[Turn]:
    evaluations = st.builds(
        EvalResult,
        outcome=st.sampled_from(EvalOutcome),
        confidence=st.floats(min_value=0, max_value=1),
        evidence=st.lists(st.text(max_size=30), max_size=3),
        rationale=st.text(max_size=50),
        undetermined_operands=st.lists(st.text(max_size=30), max_size=3),
    )
    return st.builds(
        Turn,
        request=_requests(),
        response=_responses(),
        eval_result=st.none() | evaluations,
        turn_number=st.integers(min_value=0, max_value=100),
        timestamp=_timestamps(),
        driver_reasoning=st.text(max_size=50),
    )


def _results() -> SearchStrategy[Result]:
    injections = st.builds(
        InjectionRecord,
        payload_id=st.none() | st.text(max_size=30),
        surface_name=st.text(max_size=30),
    )
    populations = st.builds(
        PopulationRef,
        id=st.text(max_size=30),
        index=st.integers(min_value=0, max_value=9),
        size=st.just(10),
        threshold=st.floats(min_value=0, max_value=1),
    )
    return st.builds(
        Result,
        status=st.sampled_from(SafetyStatus),
        summary=st.text(max_size=100),
        observability_level=st.sampled_from(ObservabilityLevel),
        turns=st.lists(_turns(), max_size=3),
        duration_seconds=st.floats(min_value=0, allow_infinity=False),
        harm_category=st.none() | st.text(max_size=30) | st.sampled_from(HarmCategory),
        strategy=st.text(max_size=30),
        injections=st.lists(injections, max_size=2),
        population=st.none() | populations,
        metadata=_json_maps(),
    )


class TestGeneratedRoundTrips:
    @given(result=_results())
    def test_body_preserves_supported_values(self, result: Result) -> None:
        body = result.to_dict()

        restored = Result.from_dict(json.loads(json.dumps(body, allow_nan=False)))

        assert restored == result
        assert restored.to_dict() == body
        assert result.to_dict() == body

    @given(
        result=_results(),
        nodeid=st.none() | st.text(max_size=40),
        index=st.none() | st.integers(min_value=0, max_value=100),
    )
    def test_record_round_trip_matches_the_structural_schema(
        self, *, result: Result, nodeid: str | None, index: int | None
    ) -> None:
        record = ResultRecord(result=result, pytest_nodeid=nodeid, result_index=index)
        original_body = result.to_dict()
        encoded = serialize_record(record=record)
        body = json.loads(encoded)

        restored = deserialize_record(data=encoded)

        assert restored.result == replace(result, metadata=body["result"]["metadata"])
        assert restored.pytest_nodeid == nodeid
        assert restored.result_index == index
        assert restored.to_dict() == body
        assert record.to_dict() == body
        assert result.to_dict() == original_body
        Draft202012Validator(ResultRecord.json_schema()).validate(body)
