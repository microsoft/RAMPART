# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from rampart.attacks import Attacks
from rampart.core.errors import InfrastructureError
from rampart.core.manifest import AppManifest
from rampart.core.result import SafetyStatus
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    Request,
    Response,
    ToolCall,
)
from tests.fixtures import MockAdapter

_DEFAULT_MANIFEST = AppManifest(name="TestAgent")


def _mock_handle(
    *,
    surface_name: str = "FakeSurface",
    payload_id: str | None = "p-001",
) -> AsyncMock:
    """Create an AsyncMock satisfying the InjectionHandle protocol."""
    h = AsyncMock()
    h.surface_name = surface_name
    h.payload_id = payload_id
    h.__aenter__.return_value = h
    return h


def _mock_evaluator(
    outcome: EvalOutcome,
    *,
    confidence: float = 1.0,
    evidence: list[str] | None = None,
    rationale: str = "",
) -> AsyncMock:
    """Create an AsyncMock evaluator returning a fixed EvalResult."""
    evaluator = AsyncMock()
    evaluator.evaluate_async.return_value = EvalResult(
        outcome=outcome,
        confidence=confidence,
        evidence=evidence or [],
        rationale=rationale,
    )
    return evaluator


def _adapter(
    *,
    responses: list[Response] | None = None,
    observability: ObservabilityLevel = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
) -> MockAdapter:
    """Shorthand for MockAdapter with sensible defaults."""
    return MockAdapter(
        responses=responses or [Response(text="ok")],
        manifest=_DEFAULT_MANIFEST,
        observability_profile=observability,
    )


class TestXPIADetection:
    """Attack semantics: DETECTED->UNSAFE, NOT_DETECTED->SAFE."""

    @pytest.mark.asyncio
    async def test_detected_returns_unsafe_with_evidence_in_summary(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(
                EvalOutcome.DETECTED,
                evidence=["exfil_call_found"],
            ),
        ).execute_async(adapter=_adapter())

        assert result.safe is False
        assert result.status is SafetyStatus.UNSAFE
        assert "exfil_call_found" in result.summary

    @pytest.mark.asyncio
    async def test_not_detected_returns_safe(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE

    @pytest.mark.asyncio
    async def test_undetermined_returns_undetermined(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(
                EvalOutcome.UNDETERMINED,
                rationale="Insufficient signal",
            ),
        ).execute_async(adapter=_adapter())

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED


class TestXPIAEarlyStop:
    """Per-turn evaluation stops the conversation on first detection."""

    @pytest.mark.asyncio
    async def test_stops_after_first_detection(self) -> None:
        evaluator = AsyncMock()
        evaluator.evaluate_async.side_effect = [
            EvalResult(outcome=EvalOutcome.NOT_DETECTED),
            EvalResult(outcome=EvalOutcome.DETECTED, evidence=["found_it"]),
        ]

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.UNSAFE
        assert len(result.turns) == 2

    @pytest.mark.asyncio
    async def test_completes_all_turns_when_not_detected(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        assert len(result.turns) == 2


class TestXPIAMaxTurns:
    """Max-turns guard prevents unbounded driver loops."""

    @pytest.mark.asyncio
    async def test_returns_error_when_driver_exceeds_max_turns(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["p1", "p2", "p3"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
            max_turns=2,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert "Max turns" in result.summary
        assert len(result.turns) == 2


class TestXPIACleanup:
    """Injection handles are always activated and cleaned up."""

    @pytest.mark.asyncio
    async def test_handle_entered_and_exited(self) -> None:
        handle = _mock_handle()

        await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        handle.__aenter__.assert_awaited_once()
        handle.__aexit__.assert_awaited_once()
        handle.wait_until_ready.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_handles_all_cleaned(self) -> None:
        h1 = _mock_handle(surface_name="SP")
        h2 = _mock_handle(surface_name="Exchange")

        await Attacks.xpia(
            inject=[h1, h2],
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        for h in (h1, h2):
            h.__aenter__.assert_awaited_once()
            h.__aexit__.assert_awaited_once()
            h.wait_until_ready.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_on_evaluator_exception(self) -> None:
        """Handles are cleaned up even if the evaluator raises."""
        handle = _mock_handle()
        evaluator = AsyncMock()
        evaluator.evaluate_async.side_effect = RuntimeError("evaluator boom")

        with pytest.raises(RuntimeError, match="evaluator boom"):
            await Attacks.xpia(
                inject=handle,
                trigger="Summarize Q3",
                evaluator=evaluator,
            ).execute_async(adapter=_adapter())

        handle.__aexit__.assert_awaited_once()


class TestXPIAInfrastructureError:
    """InfrastructureError produces ERROR result (base class concern)."""

    @pytest.mark.asyncio
    async def test_handle_activation_failure(self) -> None:
        handle = _mock_handle()
        handle.__aenter__.side_effect = InfrastructureError("SharePoint 503")

        result = await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert "SharePoint 503" in result.summary

    @pytest.mark.asyncio
    async def test_session_creation_failure(self) -> None:
        adapter = AsyncMock()
        adapter.create_session_async.side_effect = InfrastructureError(
            "Connection refused",
        )
        adapter.manifest = _DEFAULT_MANIFEST
        adapter.observability_profile = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.DETECTED),
        ).execute_async(adapter=adapter)

        assert result.status is SafetyStatus.ERROR
        assert "Connection refused" in result.summary


class TestXPIAObservabilityAdjustment:
    """SAFE is downgraded to UNDETERMINED when observability is insufficient."""

    @pytest.mark.asyncio
    async def test_response_only_no_tools_downgrades_to_undetermined(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.RESPONSE_ONLY),
        )

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED

    @pytest.mark.asyncio
    async def test_response_only_with_tool_calls_stays_safe(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="ok", tool_calls=[ToolCall(name="search")])],
                observability=ObservabilityLevel.RESPONSE_ONLY,
            ),
        )

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE

    @pytest.mark.asyncio
    async def test_non_response_only_levels_are_not_downgraded(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.TOOL_ONLY),
        )

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE


class TestXPIAInjectionRecords:
    """Result carries injection records for reproduction."""

    @pytest.mark.asyncio
    async def test_single_handle_recorded(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(surface_name="SharePoint", payload_id="px-42"),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert len(result.injections) == 1
        assert result.injections[0].payload_id == "px-42"
        assert result.injections[0].surface_name == "SharePoint"

    @pytest.mark.asyncio
    async def test_multi_handle_records(self) -> None:
        result = await Attacks.xpia(
            inject=[
                _mock_handle(surface_name="SP", payload_id="p1"),
                _mock_handle(surface_name="Exchange", payload_id="p2"),
            ],
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert len(result.injections) == 2
        names = {r.surface_name for r in result.injections}
        assert names == {"SP", "Exchange"}


class TestXPIAAttachments:
    """Inline attachments flow through to turns via Request."""

    @pytest.mark.asyncio
    async def test_attachments_recorded_in_turns(self) -> None:
        attachment = Payload(content="malicious doc", id="att-1")

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=Request(prompt="Open the attached file", attachments=[attachment]),
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.turns[0].request.attachments[0].id == "att-1"


class TestResponseMetadataPropagation:
    """Response.metadata from the adapter flows into Result.metadata."""

    @pytest.mark.asyncio
    async def test_single_turn_metadata_promoted_to_top_level(self) -> None:
        adapter = _adapter(
            responses=[Response(text="ok", metadata={"conversation_id": "c-01"})],
        )
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=adapter)

        assert result.metadata == {"conversation_id": "c-01"}

    @pytest.mark.asyncio
    async def test_empty_response_metadata_produces_empty_result_metadata(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.metadata == {}

    @pytest.mark.asyncio
    async def test_multi_turn_metadata_keyed_by_turn_number(self) -> None:
        adapter = _adapter(
            responses=[
                Response(text="turn0", metadata={"page_url": "url0"}),
                Response(text="turn1", metadata={"page_url": "url1"}),
            ],
        )
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Summarize Q3", "Tell me more"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=adapter)

        assert "turn_0" in result.metadata
        assert result.metadata["turn_0"]["page_url"] == "url0"
        assert result.metadata["turn_1"]["page_url"] == "url1"
