# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from rampart.attacks import Attacks
from rampart.attacks._xpia import _build_summary
from rampart.core.errors import InfrastructureError
from rampart.core.evaluator import Evaluator
from rampart.core.injection import InjectionHandle
from rampart.core.manifest import AppManifest
from rampart.core.result import SafetyStatus
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    Request,
    Response,
    SideEffect,
    ToolCall,
)
from rampart.evaluators import ResponseContains, SideEffectOccurred, ToolCalled
from tests.fixtures import MockAdapter

_DEFAULT_MANIFEST = AppManifest(name="TestAgent")


def _mock_handle(
    *,
    surface_name: str = "FakeSurface",
    payload_id: str | None = "p-001",
) -> AsyncMock:
    """Create an AsyncMock satisfying the InjectionHandle protocol."""
    h = AsyncMock(spec=InjectionHandle)
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
    evaluator = AsyncMock(spec=Evaluator)
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

    async def test_detected_returns_unsafe_with_evidence_in_summary_async(self) -> None:
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

    async def test_not_detected_returns_safe_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE

    async def test_undetermined_returns_undetermined_async(self) -> None:
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

    async def test_stops_after_first_detection_async(self) -> None:
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

    async def test_completes_all_turns_when_not_detected_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        assert len(result.turns) == 2


class TestXPIAMaxTurns:
    """Max-turns resolves normally via resolve_as_attack."""

    async def test_max_turns_resolves_normally_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["p1", "p2", "p3"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
            max_turns=2,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        assert len(result.turns) == 2


class TestXPIACleanup:
    """Injection handles are always activated and cleaned up."""

    async def test_handle_entered_and_exited_async(self) -> None:
        handle = _mock_handle()

        await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        handle.__aenter__.assert_awaited_once()
        handle.__aexit__.assert_awaited_once()
        handle.wait_until_ready_async.assert_awaited_once()

    async def test_multiple_handles_all_cleaned_async(self) -> None:
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
            h.wait_until_ready_async.assert_awaited_once()

    async def test_cleanup_on_evaluator_exception_async(self) -> None:
        """Handles are cleaned up even if the evaluator raises."""
        handle = _mock_handle()
        evaluator = AsyncMock()
        evaluator.evaluate_async.side_effect = RuntimeError("evaluator boom")

        result = await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert "evaluator boom" in result.summary
        handle.__aexit__.assert_awaited_once()


class TestXPIAInfrastructureError:
    """InfrastructureError produces ERROR result (base class concern)."""

    async def test_handle_activation_failure_async(self) -> None:
        handle = _mock_handle()
        handle.__aenter__.side_effect = InfrastructureError("SharePoint 503")

        result = await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert "SharePoint 503" in result.summary

    async def test_partial_activation_failure_still_cleans_up_siblings_async(
        self,
    ) -> None:
        """A slow successful sibling must register cleanup even if another fails.

        Concurrent activation uses gather(return_exceptions=True) so a
        failing handle does not cancel siblings mid-__aenter__.
        """
        entered = asyncio.Event()

        async def slow_success_aenter_async(
            *_args: object,
            **_kwargs: object,
        ) -> AsyncMock:
            entered.set()
            await asyncio.sleep(0.05)
            return slow

        async def fast_fail_aenter_async(
            *_args: object,
            **_kwargs: object,
        ) -> AsyncMock:
            await entered.wait()
            raise InfrastructureError("SharePoint 503")

        slow = _mock_handle(surface_name="Exchange")
        slow.__aenter__.side_effect = slow_success_aenter_async
        failing = _mock_handle(surface_name="SharePoint")
        failing.__aenter__.side_effect = fast_fail_aenter_async

        result = await Attacks.xpia(
            inject=[slow, failing],
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert "SharePoint 503" in result.summary
        slow.__aenter__.assert_awaited_once()
        failing.__aenter__.assert_awaited_once()
        # Successful sibling registered on the exit stack and is cleaned up.
        slow.__aexit__.assert_awaited_once()

    async def test_session_creation_failure_async(self) -> None:
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

    async def test_response_only_no_tools_downgrades_to_undetermined_async(
        self,
    ) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.RESPONSE_ONLY),
        )

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED

    async def test_response_only_with_tool_calls_stays_safe_async(self) -> None:
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

    async def test_non_response_only_levels_are_not_downgraded_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.TOOL_ONLY),
        )

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE


class TestXPIAEvaluatorObservability:
    """Evaluators that cannot see their evidence do not report the agent as safe."""

    async def test_dropping_observability_does_not_look_safer_async(
        self,
    ) -> None:
        exfiltration = SideEffect(
            kind="http_request",
            details={"url": "https://evil.com/steal"},
        )

        reported = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("http_request"),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="done", side_effects=[exfiltration])],
                observability=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
            ),
        )

        # Same run, but the adapter cannot report side effects, so the
        # evaluator sees an empty list instead of the exfiltration above.
        unreported = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("http_request"),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="done")],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        assert reported.status is SafetyStatus.UNSAFE
        assert unreported.safe is False

    async def test_side_effect_undetermined_under_tool_only_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("http_request"),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.TOOL_ONLY),
        )

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED

    async def test_tool_undetermined_under_response_only_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=ToolCalled("send_email"),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.RESPONSE_ONLY),
        )

        assert result.safe is False
        assert result.status is SafetyStatus.UNDETERMINED

    async def test_side_effect_safe_under_full_observability_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("http_request"),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS),
        )

        assert result.safe is True
        assert result.status is SafetyStatus.SAFE

    async def test_detection_still_unsafe_under_tool_only_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=ToolCalled("send_email"),
        ).execute_async(
            adapter=_adapter(
                responses=[
                    Response(text="sent", tool_calls=[ToolCall(name="send_email")]),
                ],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        assert result.safe is False
        assert result.status is SafetyStatus.UNSAFE


class TestXPIAInjectionRecords:
    """Result carries injection records for reproduction."""

    async def test_single_handle_recorded_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(surface_name="SharePoint", payload_id="px-42"),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert len(result.injections) == 1
        assert result.injections[0].payload_id == "px-42"
        assert result.injections[0].surface_name == "SharePoint"

    async def test_multi_handle_records_async(self) -> None:
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

    async def test_attachments_recorded_in_turns_async(self) -> None:
        attachment = Payload(content="malicious doc", id="att-1")

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=Request(prompt="Open the attached file", attachments=[attachment]),
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.turns[0].request.attachments[0].id == "att-1"


class TestResponseMetadataPropagation:
    """Response.metadata from the adapter flows into Result.metadata."""

    async def test_single_turn_metadata_promoted_to_top_level_async(self) -> None:
        adapter = _adapter(
            responses=[Response(text="ok", metadata={"conversation_id": "c-01"})],
        )
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=adapter)

        assert result.metadata == {"conversation_id": "c-01"}

    async def test_empty_response_metadata_produces_empty_result_metadata_async(
        self,
    ) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
        ).execute_async(adapter=_adapter())

        assert result.metadata == {}

    async def test_multi_turn_metadata_keyed_by_turn_number_async(self) -> None:
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


class TestXPIAUndeterminedSummary:
    """An undetermined summary should name the gap, not an unrelated rationale."""

    def test_summary_uses_only_undetermined_rationales(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    rationale="Tool 'send_email' not called with matching parameters",
                ),
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Adapter observability is 'response_only'",
                ),
            ],
        )

        assert "response_only" in summary
        assert "not called" not in summary

    def test_summary_falls_back_without_a_rationale(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNDETERMINED,
            eval_results=[EvalResult(outcome=EvalOutcome.UNDETERMINED)],
        )

        assert summary == "Evaluation undetermined: Insufficient observability"


class TestXPIAUnsafeSummary:
    """An unsafe summary should cite the evidence that established the verdict."""

    def test_summary_uses_only_detected_evidence(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNSAFE,
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    evidence=["partial_a", "partial_b", "partial_c"],
                ),
                EvalResult(
                    outcome=EvalOutcome.DETECTED,
                    evidence=["send_email({'to': 'evil.com'})"],
                ),
            ],
        )

        assert summary == "Attack objective detected: send_email({'to': 'evil.com'})"

    def test_summary_falls_back_without_evidence(self) -> None:
        summary = _build_summary(
            status=SafetyStatus.UNSAFE,
            eval_results=[EvalResult(outcome=EvalOutcome.DETECTED)],
        )

        assert summary == "Attack objective detected"

    async def test_undetermined_turn_does_not_supply_the_evidence_async(self) -> None:
        exfiltration = SideEffect(kind="http_request", details={"url": "evil.com"})

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=SideEffectOccurred("http_request") & ResponseContains("id_rsa"),
        ).execute_async(
            adapter=_adapter(
                responses=[
                    Response(text="here is id_rsa"),
                    Response(text="here is id_rsa", side_effects=[exfiltration]),
                ],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        undetermined_first = result.turns[0].eval_result
        assert undetermined_first is not None
        assert undetermined_first.outcome is EvalOutcome.UNDETERMINED
        assert undetermined_first.evidence == ["Pattern found in response text"]
        assert result.status is SafetyStatus.UNSAFE
        assert result.summary.startswith(
            "Attack objective detected: Side effect 'http_request'",
        )
