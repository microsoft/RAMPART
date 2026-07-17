# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the RAMPART xdist support module."""

from __future__ import annotations

import json
import logging
import math
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

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
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)
from rampart.pytest_plugin._session import RampartSession, TrialSpec
from rampart.pytest_plugin._xdist import (
    DEFAULT_SIZE_LIMIT_BYTES,
    MAX_METADATA_DEPTH,
    SCHEMA_VERSION,
    SIZE_LIMIT_OPTION,
    WORKEROUTPUT_KEY,
    SchemaVersionError,
    SizeLimitError,
    WorkerOutputError,
    _sanitize,
    _strip_ansi,
    deserialize_trial_specs,
    deserialize_worker_data,
    discover_sinks_from_conftest,
    finalize_worker,
    get_dist_mode,
    get_worker_count,
    handle_testnodedown,
    is_xdist_controller,
    is_xdist_worker,
    serialize_worker_data,
)
from rampart.reporting.sink import ReportSink, TestRunReport


def _make_result(
    *,
    safe: bool = True,
    status: SafetyStatus = SafetyStatus.SAFE,
    summary: str = "summary",
    harm_category: HarmCategory | str | None = None,
    strategy: str = "xpia",
    duration_seconds: float = 1.0,
    metadata: dict[str, Any] | None = None,
    turns: list[Turn] | None = None,
    injections: list[InjectionRecord] | None = None,
    observability_level: ObservabilityLevel = ObservabilityLevel.RESPONSE_ONLY,
) -> Result:
    return Result(
        safe=safe,
        status=status,
        summary=summary,
        turns=turns or [],
        duration_seconds=duration_seconds,
        harm_category=harm_category,
        strategy=strategy,
        observability_level=observability_level,
        injections=injections or [],
        metadata=metadata or {},
    )


def _make_turn(
    *,
    prompt: str = "hi",
    text: str = "ok",
    eval_result: EvalResult | None = None,
    turn_number: int = 0,
    timestamp: datetime | None = None,
    driver_reasoning: str = "",
) -> Turn:
    return Turn(
        request=Request(prompt=prompt),
        response=Response(text=text),
        eval_result=eval_result,
        turn_number=turn_number,
        timestamp=timestamp,
        driver_reasoning=driver_reasoning,
    )


def _make_eval_result(
    *,
    outcome: EvalOutcome = EvalOutcome.DETECTED,
    confidence: float = 0.9,
    evidence: list[str] | None = None,
    rationale: str = "because",
) -> EvalResult:
    return EvalResult(
        outcome=outcome,
        confidence=confidence,
        evidence=evidence or [],
        rationale=rationale,
    )


def _make_config(
    *,
    is_worker: bool = False,
    numprocesses: int | None = None,
    dist: str = "no",
    tx: list[str] | None = None,
    max_bytes: int | None = None,
) -> Any:
    config = MagicMock()
    if is_worker:
        config.workerinput = {"workerid": "gw0"}
    else:
        del config.workerinput
    config.option = MagicMock()
    config.option.numprocesses = numprocesses
    config.option.dist = dist
    config.option.tx = tx

    def _getoption(name: str, default: object = None) -> object:
        return max_bytes if name == SIZE_LIMIT_OPTION else default

    def _getini(name: str) -> None:
        del name

    config.getoption = _getoption
    config.getini = _getini
    return config


def _make_session_with_results(
    *,
    results_by_nodeid: dict[str, list[Result]],
) -> RampartSession:
    session = RampartSession()
    session._results_by_nodeid = dict(results_by_nodeid)
    for results in results_by_nodeid.values():
        session._results.extend(results)
    return session


class TestDetection:
    def test_is_xdist_worker_true_when_workerinput_present(self) -> None:
        config = _make_config(is_worker=True)
        assert is_xdist_worker(config=config) is True

    def test_is_xdist_worker_false_when_workerinput_absent(self) -> None:
        config = _make_config(is_worker=False)
        assert is_xdist_worker(config=config) is False

    def test_is_xdist_controller_true_with_numprocesses(self) -> None:
        config = _make_config(numprocesses=2, dist="load")
        assert is_xdist_controller(config=config) is True

    def test_is_xdist_controller_true_with_tx_without_numprocesses(self) -> None:
        config = _make_config(dist="load", tx=["popen", "popen"])
        assert is_xdist_controller(config=config) is True

    def test_is_xdist_controller_false_when_dist_without_endpoints(self) -> None:
        config = _make_config(dist="load")
        assert is_xdist_controller(config=config) is False

    def test_is_xdist_controller_false_with_zero_numprocesses(self) -> None:
        config = _make_config(numprocesses=0, dist="no")
        assert is_xdist_controller(config=config) is False

    def test_is_xdist_controller_false_when_no_numprocesses(self) -> None:
        config = _make_config(numprocesses=None)
        assert is_xdist_controller(config=config) is False

    def test_is_xdist_controller_false_for_worker(self) -> None:
        config = _make_config(is_worker=True, numprocesses=2)
        assert is_xdist_controller(config=config) is False

    def test_get_dist_mode_default(self) -> None:
        config = _make_config()
        assert get_dist_mode(config=config) == "no"

    def test_get_dist_mode_loadgroup(self) -> None:
        config = _make_config(dist="loadgroup")
        assert get_dist_mode(config=config) == "loadgroup"

    def test_get_worker_count_returns_numprocesses(self) -> None:
        config = _make_config(numprocesses=4)
        assert get_worker_count(config=config) == 4

    def test_get_worker_count_zero_when_inactive(self) -> None:
        config = _make_config()
        assert get_worker_count(config=config) == 0


class TestSanitize:
    def test_passes_primitives_unchanged(self) -> None:
        assert _sanitize(value=42) == 42
        assert _sanitize(value="hello") == "hello"
        assert _sanitize(value=True) is True
        assert _sanitize(value=None) is None
        assert _sanitize(value=31.4) == pytest.approx(31.4)

    def test_nan_coerced_to_none(self) -> None:
        assert _sanitize(value=float("nan")) is None

    def test_inf_coerced_to_none(self) -> None:
        assert _sanitize(value=float("inf")) is None
        assert _sanitize(value=float("-inf")) is None

    def test_dict_recursed(self) -> None:
        result = _sanitize(value={"a": 1, "b": {"c": "x"}})
        assert result == {"a": 1, "b": {"c": "x"}}

    def test_list_recursed(self) -> None:
        result = _sanitize(value=[1, "two", [3]])
        assert result == [1, "two", [3]]

    def test_tuple_becomes_list(self) -> None:
        result = _sanitize(value=(1, 2, 3))
        assert result == [1, 2, 3]

    def test_custom_object_coerced_via_repr(self) -> None:
        class Obj:
            def __repr__(self) -> str:
                return "<Obj>"

        assert _sanitize(value=Obj()) == "<Obj>"

    def test_depth_limit_coerces_to_repr(self) -> None:
        nested: dict[str, Any] = {"v": "leaf"}
        for _ in range(MAX_METADATA_DEPTH + 2):
            nested = {"v": nested}
        result = _sanitize(value=nested)
        json.dumps(result)  # must be JSON-safe


class TestStripAnsi:
    def test_removes_color_codes(self) -> None:
        text = "\x1b[31mred\x1b[0m"
        assert _strip_ansi(text=text) == "red"

    def test_preserves_plain_text(self) -> None:
        assert _strip_ansi(text="hello world") == "hello world"

    def test_strips_multiple_sequences(self) -> None:
        text = "\x1b[1m\x1b[31mbold red\x1b[0m\x1b[0m"
        assert _strip_ansi(text=text) == "bold red"

    def test_strips_osc_hyperlink_via_shared_sanitizer(self) -> None:
        text = "\x1b]8;;http://example.com\x07link\x1b]8;;\x07"
        assert _strip_ansi(text=text) == "link"


class TestSerializationRoundTrip:
    def test_simple_result_round_trip(self) -> None:
        result = _make_result(summary="hi", harm_category=HarmCategory.JAILBREAK)
        session = _make_session_with_results(
            results_by_nodeid={"test::a": [result]},
        )
        payload = serialize_worker_data(session=session)
        json.dumps(payload, default=str)
        recovered = deserialize_worker_data(data=payload)
        assert "test::a" in recovered
        assert recovered["test::a"][0].safe is True
        assert recovered["test::a"][0].status is SafetyStatus.SAFE
        assert recovered["test::a"][0].harm_category is HarmCategory.JAILBREAK

    def test_status_enum_round_trip(self) -> None:
        for status in SafetyStatus:
            result = _make_result(status=status, safe=status is SafetyStatus.SAFE)
            session = _make_session_with_results(
                results_by_nodeid={"n": [result]},
            )
            payload = serialize_worker_data(session=session)
            recovered = deserialize_worker_data(data=payload)
            assert recovered["n"][0].status is status

    def test_observability_level_round_trip(self) -> None:
        for level in ObservabilityLevel:
            result = _make_result(observability_level=level)
            session = _make_session_with_results(
                results_by_nodeid={"n": [result]},
            )
            payload = serialize_worker_data(session=session)
            recovered = deserialize_worker_data(data=payload)
            assert recovered["n"][0].observability_level is level

    def test_harm_category_plain_string_round_trip(self) -> None:
        result = _make_result(harm_category="custom_product_risk")
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].harm_category == "custom_product_risk"

    def test_turns_with_eval_result_round_trip(self) -> None:
        eval_result = _make_eval_result(
            outcome=EvalOutcome.NOT_DETECTED,
            confidence=0.7,
            evidence=["e1", "e2"],
            rationale="r",
        )
        turn = _make_turn(eval_result=eval_result, turn_number=1)
        result = _make_result(turns=[turn])
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].turns[0].eval_result is not None
        outcome = recovered["n"][0].turns[0].eval_result.outcome
        assert outcome is EvalOutcome.NOT_DETECTED
        assert recovered["n"][0].turns[0].eval_result.evidence == ["e1", "e2"]

    def test_datetime_round_trip(self) -> None:
        when = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        turn = _make_turn(timestamp=when)
        result = _make_result(turns=[turn])
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].turns[0].timestamp == when

    def test_injections_round_trip(self) -> None:
        injection = InjectionRecord(payload_id="p1", surface_name="OneDrive")
        result = _make_result(injections=[injection])
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].injections[0].payload_id == "p1"
        assert recovered["n"][0].injections[0].surface_name == "OneDrive"

    def test_response_with_tool_calls_round_trip(self) -> None:
        tool_call = ToolCall(name="send_email", arguments={"to": "a@b.c"})
        response = Response(text="ok", tool_calls=[tool_call])
        turn = Turn(request=Request(prompt="hi"), response=response)
        result = _make_result(turns=[turn])
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].turns[0].response.tool_calls[0].name == "send_email"
        assert recovered["n"][0].turns[0].response.tool_calls[0].arguments == {
            "to": "a@b.c",
        }

    def test_response_with_side_effects_round_trip(self) -> None:
        side_effect = SideEffect(kind="http", details={"url": "http://x"})
        response = Response(text="ok", side_effects=[side_effect])
        turn = Turn(request=Request(prompt="hi"), response=response)
        result = _make_result(turns=[turn])
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].turns[0].response.side_effects[0].kind == "http"

    def test_metadata_round_trip(self) -> None:
        result = _make_result(metadata={"test_name": "t1", "tries": 3})
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["n"][0].metadata["test_name"] == "t1"
        assert recovered["n"][0].metadata["tries"] == 3


class TestDeserializationValidation:
    def test_rejects_non_dict_payload(self) -> None:
        with pytest.raises(WorkerOutputError, match="Expected dict"):
            deserialize_worker_data(data="not-a-dict")

    def test_rejects_missing_schema_key(self) -> None:
        with pytest.raises(SchemaVersionError, match="missing required 'schema'"):
            deserialize_worker_data(data={"results_by_nodeid": {}})

    def test_rejects_unknown_schema_version(self) -> None:
        payload: dict[str, Any] = {
            "schema": "rampart.xdist.v999",
            "results_by_nodeid": {},
        }
        with pytest.raises(SchemaVersionError, match="does not match"):
            deserialize_worker_data(data=payload)

    def test_rejects_malformed_safety_status(self) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {
                "n": [
                    {
                        "safe": True,
                        "status": "not-a-status",
                        "summary": "x",
                        "observability_level": "response_only",
                    },
                ],
            },
        }
        with pytest.raises(WorkerOutputError, match="Unknown SafetyStatus"):
            deserialize_worker_data(data=payload)

    def test_rejects_malformed_observability_level(self) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {
                "n": [
                    {
                        "safe": True,
                        "status": "safe",
                        "summary": "x",
                        "observability_level": "not-a-level",
                    },
                ],
            },
        }
        with pytest.raises(WorkerOutputError, match="Unknown ObservabilityLevel"):
            deserialize_worker_data(data=payload)


class TestDeserializationSecurity:
    def test_strips_ansi_from_summary(self) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {
                "n": [
                    {
                        "safe": False,
                        "status": "unsafe",
                        "summary": "\x1b[31mDANGER\x1b[0m",
                        "observability_level": "response_only",
                    },
                ],
            },
        }
        result = deserialize_worker_data(data=payload)["n"][0]
        assert result.summary == "DANGER"
        assert "\x1b" not in result.summary

    def test_strips_ansi_from_response_text(self) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {
                "n": [
                    {
                        "safe": True,
                        "status": "safe",
                        "summary": "x",
                        "observability_level": "response_only",
                        "turns": [
                            {
                                "request": {"prompt": "p"},
                                "response": {"text": "\x1b[31mDANGER\x1b[0m"},
                            },
                        ],
                    },
                ],
            },
        }
        result = deserialize_worker_data(data=payload)["n"][0]
        assert result.turns[0].response.text == "DANGER"

    def test_nan_inf_in_duration_coerced_to_zero(self) -> None:
        session = _make_session_with_results(
            results_by_nodeid={
                "n": [_make_result(duration_seconds=float("nan"))],
            },
        )
        payload = serialize_worker_data(session=session)
        encoded = json.dumps(payload, default=str)
        assert "NaN" not in encoded
        recovered = deserialize_worker_data(data=payload)
        assert math.isfinite(recovered["n"][0].duration_seconds)

    def test_payload_artifact_path_preserved_in_metadata(self) -> None:
        payload: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {
                "n": [
                    {
                        "safe": True,
                        "status": "safe",
                        "summary": "x",
                        "observability_level": "response_only",
                        "turns": [
                            {
                                "request": {
                                    "prompt": None,
                                    "attachments": [
                                        {
                                            "content": "c",
                                            "id": "p1",
                                            "format": "pdf",
                                            "artifact": "/worker/local/path.pdf",
                                            "metadata": {},
                                        },
                                    ],
                                },
                                "response": {"text": "ok"},
                            },
                        ],
                    },
                ],
            },
        }
        result = deserialize_worker_data(data=payload)["n"][0]
        attachment = result.turns[0].request.attachments[0]
        assert attachment.format is PayloadFormat.TEXT
        assert attachment.artifact is None
        assert (
            attachment.metadata["_rampart_worker_artifact_path"]
            == "/worker/local/path.pdf"
        )
        assert attachment.metadata["_rampart_worker_format"] == "pdf"

    def test_serialized_payload_is_pure_json(self) -> None:
        result = _make_result(
            metadata={"obj": object()},
            harm_category=HarmCategory.JAILBREAK,
        )
        session = _make_session_with_results(
            results_by_nodeid={"n": [result]},
        )
        payload = serialize_worker_data(session=session)
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded["schema"] == SCHEMA_VERSION

    def test_non_serializable_metadata_coerced_with_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class Obj:
            def __repr__(self) -> str:
                return "<Obj>"

        result = _make_result(metadata={"obj": Obj()})
        session = _make_session_with_results(
            results_by_nodeid={"my::node": [result]},
        )
        with caplog.at_level(logging.WARNING):
            payload = serialize_worker_data(session=session)
        recovered = deserialize_worker_data(data=payload)
        assert recovered["my::node"][0].metadata["obj"] == "<Obj>"
        assert any(
            "my::node" in record.getMessage() and "obj" in record.getMessage()
            for record in caplog.records
        )


class TestMerge:
    def test_merge_extends_results(self) -> None:
        session = RampartSession()
        session.merge_worker_results(
            results_by_nodeid={
                "n1": [_make_result(summary="r1")],
            },
        )
        session.merge_worker_results(
            results_by_nodeid={
                "n2": [_make_result(summary="r2")],
            },
        )
        assert len(session._results) == 2
        assert "n1" in session._results_by_nodeid
        assert "n2" in session._results_by_nodeid

    def test_merge_invalidates_cached_report(self) -> None:
        session = RampartSession()
        session.merge_worker_results(
            results_by_nodeid={"n1": [_make_result()]},
        )
        first = session.build_report()
        session.merge_worker_results(
            results_by_nodeid={"n2": [_make_result()]},
        )
        second = session.build_report()
        assert first is not second
        assert second.total_runs == 2

    def test_build_report_orders_results_by_test_name(self) -> None:
        session = RampartSession()
        session.merge_worker_results(
            results_by_nodeid={
                "z": [
                    _make_result(summary="z", metadata={"_pytest_test_name": "z_test"}),
                ],
                "a": [
                    _make_result(summary="a", metadata={"_pytest_test_name": "a_test"}),
                ],
            },
        )
        report = session.build_report()
        names = [r.metadata["_pytest_test_name"] for r in report.results]
        assert names == sorted(names)

    def test_mark_incomplete_surfaces_in_report_metadata(self) -> None:
        session = RampartSession()
        session.merge_worker_results(
            results_by_nodeid={"n": [_make_result()]},
        )
        session.mark_incomplete(reason="worker gw0 crashed")
        report = session.build_report()
        assert report.metadata["incomplete"] is True
        assert "worker gw0 crashed" in report.metadata["incomplete_reasons"]

    def test_emitted_idempotency_flag(self) -> None:
        session = RampartSession()
        assert session.is_emitted is False
        session.mark_emitted()
        assert session.is_emitted is True


class TestHandleTestnodedown:
    def test_records_incomplete_on_error(self) -> None:
        session = RampartSession()
        node = MagicMock()
        node.gateway.id = "gw1"
        handle_testnodedown(
            session=session,
            node=node,
            error="boom",
        )
        assert session.is_incomplete is True

    def test_records_incomplete_on_missing_workeroutput(self) -> None:
        session = RampartSession()
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = None
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is True

    def test_records_incomplete_on_missing_rampart_key(self) -> None:
        session = RampartSession()
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = {}
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is True

    def test_records_incomplete_on_deserialization_failure(self) -> None:
        session = RampartSession()
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = {WORKEROUTPUT_KEY: {"schema": "wrong-version"}}
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is True

    def test_records_incomplete_on_truncated_payload(self) -> None:
        session = RampartSession()
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = {
            WORKEROUTPUT_KEY: {
                "schema": SCHEMA_VERSION,
                "rampart_truncated": True,
            },
        }
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is True

    def test_merges_results_on_success(self) -> None:
        session = RampartSession()
        worker_session = _make_session_with_results(
            results_by_nodeid={"n": [_make_result(summary="from-worker")]},
        )
        payload = serialize_worker_data(session=worker_session)
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = {WORKEROUTPUT_KEY: payload}
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is False
        assert len(session._results) == 1
        assert session._results[0].summary == "from-worker"

    def test_merges_trial_specs_on_success(self) -> None:
        session = RampartSession()
        worker_session = RampartSession()
        worker_session.register_trial_spec(
            clone_nodeid="test.py::test_x[trial-0]",
            base_nodeid="test.py::test_x",
            threshold=0.8,
        )
        worker_session.register_trial_spec(
            clone_nodeid="test.py::test_x[trial-1]",
            base_nodeid="test.py::test_x",
            threshold=0.8,
        )
        payload = serialize_worker_data(session=worker_session)
        node = MagicMock()
        node.gateway.id = "gw1"
        node.workeroutput = {WORKEROUTPUT_KEY: payload}
        handle_testnodedown(session=session, node=node, error=None)
        assert session.is_incomplete is False
        assert set(session.trial_specs) == {
            "test.py::test_x[trial-0]",
            "test.py::test_x[trial-1]",
        }
        assert (
            session.trial_specs["test.py::test_x[trial-0]"].base_nodeid
            == "test.py::test_x"
        )
        assert session.trial_specs[
            "test.py::test_x[trial-0]"
        ].threshold == pytest.approx(0.8)


class TestOrderingDeterminism:
    def _payload_node(
        self,
        *,
        worker_id: str,
        nodeid: str,
        summary: str,
    ) -> MagicMock:
        worker_session = _make_session_with_results(
            results_by_nodeid={nodeid: [_make_result(summary=summary)]},
        )
        payload = serialize_worker_data(session=worker_session)
        node = MagicMock()
        node.gateway.id = worker_id
        node.workeroutput = {WORKEROUTPUT_KEY: payload}
        return node

    def _merge_order(self, nodes: list[MagicMock]) -> list[str]:
        session = RampartSession()
        for node in nodes:
            handle_testnodedown(session=session, node=node, error=None)
        return [r.metadata["_pytest_nodeid"] for r in session.build_report().results]

    def test_report_order_independent_of_worker_completion_order(self) -> None:
        node_a = self._payload_node(
            worker_id="gw0",
            nodeid="pkg/test_a.py::test_a",
            summary="a",
        )
        node_z = self._payload_node(
            worker_id="gw1",
            nodeid="pkg/test_z.py::test_z",
            summary="z",
        )
        forward = self._merge_order([node_a, node_z])
        reverse = self._merge_order([node_z, node_a])
        assert forward == reverse
        assert forward == ["pkg/test_a.py::test_a", "pkg/test_z.py::test_z"]

    def test_deserialize_sets_authoritative_nodeid_and_index(self) -> None:
        worker_session = _make_session_with_results(
            results_by_nodeid={
                "pkg::t": [_make_result(summary="a"), _make_result(summary="b")],
            },
        )
        payload = serialize_worker_data(session=worker_session)
        results = deserialize_worker_data(data=payload)["pkg::t"]
        assert [r.metadata["_pytest_nodeid"] for r in results] == ["pkg::t", "pkg::t"]
        assert [r.metadata["_rampart_result_index"] for r in results] == [0, 1]

    def test_handle_testnodedown_tags_source_worker(self) -> None:
        worker_session = _make_session_with_results(
            results_by_nodeid={"n": [_make_result(summary="x")]},
        )
        payload = serialize_worker_data(session=worker_session)
        node = MagicMock()
        node.gateway.id = "gw3"
        node.workeroutput = {WORKEROUTPUT_KEY: payload}
        session = RampartSession()
        handle_testnodedown(session=session, node=node, error=None)
        assert session._results[0].metadata["_rampart_source_worker"] == "gw3"


class TestTrialSpecs:
    def test_serialize_round_trip(self) -> None:
        session = RampartSession()
        session.register_trial_spec(
            clone_nodeid="t.py::a[trial-0]",
            base_nodeid="t.py::a",
            threshold=0.75,
        )
        session.register_trial_spec(
            clone_nodeid="t.py::a[trial-1]",
            base_nodeid="t.py::a",
            threshold=0.75,
        )
        payload = serialize_worker_data(session=session)

        # Payload must survive a JSON round-trip (xdist transports JSON).
        decoded = json.loads(json.dumps(payload))
        specs = deserialize_trial_specs(data=decoded)

        assert specs == {
            "t.py::a[trial-0]": TrialSpec(base_nodeid="t.py::a", threshold=0.75),
            "t.py::a[trial-1]": TrialSpec(base_nodeid="t.py::a", threshold=0.75),
        }

    def test_payload_without_trials_returns_empty_dict(self) -> None:
        session = RampartSession()
        payload = serialize_worker_data(session=session)
        assert deserialize_trial_specs(data=payload) == {}

    def test_skips_malformed_entries(self) -> None:
        data: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {},
            "trial_specs": [
                {"clone_nodeid": "ok", "base_nodeid": "b", "threshold": 0.5},
                "not-a-dict",
                {"clone_nodeid": "", "base_nodeid": "b", "threshold": 0.5},
                {"clone_nodeid": "x", "base_nodeid": 123, "threshold": 0.5},
                {"clone_nodeid": "y", "base_nodeid": "b"},
            ],
        }
        specs = deserialize_trial_specs(data=data)
        assert set(specs) == {"ok", "y"}
        assert specs["y"].threshold == pytest.approx(0.0)

    def test_clamps_non_finite_threshold(self) -> None:
        data: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "results_by_nodeid": {},
            "trial_specs": [
                {"clone_nodeid": "a", "base_nodeid": "b", "threshold": float("inf")},
                {"clone_nodeid": "c", "base_nodeid": "d", "threshold": float("nan")},
            ],
        }
        specs = deserialize_trial_specs(data=data)
        assert specs["a"].threshold == pytest.approx(0.0)
        assert specs["c"].threshold == pytest.approx(0.0)

    def test_merge_is_idempotent(self) -> None:
        session = RampartSession()
        spec = TrialSpec(base_nodeid="b", threshold=0.5)
        session.merge_trial_specs(trial_specs={"k": spec})
        session.merge_trial_specs(trial_specs={"k": spec})
        assert session.trial_specs == {"k": spec}

    def test_merge_first_writer_wins(self) -> None:
        session = RampartSession()
        original = TrialSpec(base_nodeid="b1", threshold=0.5)
        replacement = TrialSpec(base_nodeid="b2", threshold=0.9)
        session.merge_trial_specs(trial_specs={"k": original})
        session.merge_trial_specs(trial_specs={"k": replacement})
        # Defensive: the first registered spec wins so a worker can't
        # silently override what the controller already saw at collection.
        assert session.trial_specs["k"] == original

    def test_invalid_payload_raises(self) -> None:
        with pytest.raises(WorkerOutputError):
            deserialize_trial_specs(data="not a dict")


class TestFinalizeWorker:
    def test_no_op_on_controller(self) -> None:
        config = _make_config(is_worker=False, numprocesses=2)
        workeroutput: dict[str, Any] = {}
        config.workeroutput = workeroutput
        session = RampartSession()
        finalize_worker(config=config, session=session)
        assert WORKEROUTPUT_KEY not in workeroutput

    def test_writes_workeroutput_on_worker(self) -> None:
        config = _make_config(is_worker=True)
        workeroutput: dict[str, Any] = {}
        config.workeroutput = workeroutput
        session = _make_session_with_results(
            results_by_nodeid={"n": [_make_result(summary="x")]},
        )
        finalize_worker(config=config, session=session)
        assert WORKEROUTPUT_KEY in workeroutput
        payload: dict[str, Any] = workeroutput[WORKEROUTPUT_KEY]
        assert payload["schema"] == SCHEMA_VERSION
        assert "results_by_nodeid" in payload

    def test_truncates_oversize_payload(
        self,
    ) -> None:
        config = _make_config(is_worker=True, max_bytes=1)
        workeroutput: dict[str, Any] = {}
        config.workeroutput = workeroutput
        session = _make_session_with_results(
            results_by_nodeid={"n": [_make_result()]},
        )
        with pytest.raises(SizeLimitError):
            finalize_worker(config=config, session=session)
        payload: dict[str, Any] = workeroutput[WORKEROUTPUT_KEY]
        assert payload.get("rampart_truncated") is True


class TestSinkDiscovery:
    def test_finds_callable_rampart_sinks(self) -> None:
        sink = MagicMock(spec=ReportSink)
        plugin = MagicMock(
            spec=["rampart_sinks", "__name__"],
            rampart_sinks=lambda: [sink],
            __name__="mod",
        )
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        result = discover_sinks_from_conftest(config=config)
        assert sink in result

    def test_finds_list_rampart_sinks(self) -> None:
        sink = MagicMock(spec=ReportSink)
        plugin = MagicMock(
            spec=["rampart_sinks", "__name__"],
            rampart_sinks=[sink],
            __name__="mod",
        )
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        result = discover_sinks_from_conftest(config=config)
        assert sink in result

    def test_returns_empty_when_no_rampart_sinks(self) -> None:
        plugin = MagicMock(spec=["__name__"], __name__="mod")
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        result = discover_sinks_from_conftest(config=config)
        assert result == []

    def test_warns_on_callable_with_required_args(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def needs_arg(other: object) -> list[ReportSink]:
            return []

        plugin = MagicMock(
            spec=["rampart_sinks", "__name__"],
            rampart_sinks=needs_arg,
            __name__="mod",
        )
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        with caplog.at_level(logging.WARNING):
            result = discover_sinks_from_conftest(config=config)
        assert result == []
        assert any("requires arguments" in r.getMessage() for r in caplog.records)

    def test_resolves_parameterless_fixture_form(self) -> None:
        sink = MagicMock(spec=ReportSink)

        @pytest.fixture
        def rampart_sinks() -> list[ReportSink]:
            return [sink]

        plugin = MagicMock(
            spec=["rampart_sinks", "__name__"],
            rampart_sinks=rampart_sinks,
            __name__="mod",
        )
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        result = discover_sinks_from_conftest(config=config)
        assert sink in result

    def test_warns_and_skips_fixture_with_dependencies(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        @pytest.fixture
        def rampart_sinks(tmp_path: object) -> list[ReportSink]:
            return []

        plugin = MagicMock(
            spec=["rampart_sinks", "__name__"],
            rampart_sinks=rampart_sinks,
            __name__="mod",
        )
        config = MagicMock()
        config.pluginmanager.get_plugins.return_value = [plugin]
        with caplog.at_level(logging.WARNING):
            result = discover_sinks_from_conftest(config=config)
        assert result == []
        assert any("requires arguments" in r.getMessage() for r in caplog.records)
        assert any("pytest_rampart_sinks" in r.getMessage() for r in caplog.records)


class TestReportTestRunMetadata:
    def test_set_report_metadata_appears_in_report(self) -> None:
        session = RampartSession()
        session.set_report_metadata(
            metadata={"xdist_active": True, "worker_count": 2},
        )
        session.merge_worker_results(
            results_by_nodeid={"n": [_make_result()]},
        )
        report = session.build_report()
        assert report.metadata["xdist_active"] is True
        assert report.metadata["worker_count"] == 2

    def test_metadata_merges_across_calls(self) -> None:
        session = RampartSession()
        session.set_report_metadata(metadata={"a": 1})
        session.set_report_metadata(metadata={"b": 2})
        session.merge_worker_results(
            results_by_nodeid={"n": [_make_result()]},
        )
        report = session.build_report()
        assert report.metadata["a"] == 1
        assert report.metadata["b"] == 2


class TestConstants:
    def test_default_size_limit_is_64mb(self) -> None:
        assert DEFAULT_SIZE_LIMIT_BYTES == 64 * 1024 * 1024

    def test_schema_version_is_v1(self) -> None:
        assert SCHEMA_VERSION == "rampart.xdist.v1"

    def test_workeroutput_key_namespaced(self) -> None:
        assert WORKEROUTPUT_KEY.startswith("rampart_xdist")


class TestTestRunReportTestable:
    def test_test_run_report_excluded_from_collection(self) -> None:
        assert TestRunReport.__test__ is False
