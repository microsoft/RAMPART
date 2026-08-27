# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from rampart.attacks import Attacks
from rampart.attacks._xpia import _build_summary
from rampart.core.errors import InfrastructureError
from rampart.core.evaluator import Evaluator
from rampart.core.injection import InjectionHandle
from rampart.core.manifest import AppManifest
from rampart.core.result import SafetyStatus
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    Request,
    Response,
    SideEffect,
    TerminationReason,
    ToolCall,
)
from rampart.evaluators import (
    ResponseContains,
    ResponseScope,
    SideEffectOccurred,
    ToolCalled,
)
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


def _summary(*, status: SafetyStatus, evaluation: EvalResult) -> str:
    """Build a summary for a normally exhausted trace."""
    return _build_summary(
        status=status,
        evaluation=evaluation,
        termination_reason=TerminationReason.DRIVER_EXHAUSTED,
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


class TestXPIAParameterValidation:
    def test_invalid_stop_policy_raises(self) -> None:
        with pytest.raises(ValueError, match="'auto'"):
            Attacks.xpia(
                inject=_mock_handle(),
                trigger="Summarize Q3",
                evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
                stop_when="always",  # ty: ignore[invalid-argument-type]
            )


class TestXPIAEarlyStop:
    """Explicit and automatic attack stopping preserve justified costs."""

    async def test_explicit_identical_stop_reuses_fired_evaluation_async(self) -> None:
        evaluator = AsyncMock()
        evaluator.evaluate_async.side_effect = [
            EvalResult(outcome=EvalOutcome.NOT_DETECTED),
            EvalResult(outcome=EvalOutcome.DETECTED, evidence=["found_it"]),
        ]

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=evaluator,
            stop_when=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.UNSAFE
        assert len(result.turns) == 2
        assert result.termination_reason is TerminationReason.STOP_CONDITION
        assert evaluator.evaluate_async.await_count == 2

    async def test_explicit_non_firing_stop_reuses_terminal_evaluation_async(
        self,
    ) -> None:
        evaluator = _mock_evaluator(EvalOutcome.NOT_DETECTED)
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=evaluator,
            stop_when=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        assert len(result.turns) == 3
        assert evaluator.evaluate_async.await_count == 3

    async def test_auto_stop_uses_absorbing_tool_evaluator_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=ToolCalled("exfiltrate"),
        ).execute_async(
            adapter=_adapter(
                responses=[
                    Response(text="one"),
                    Response(
                        text="two",
                        tool_calls=[ToolCall(name="exfiltrate")],
                    ),
                ],
            ),
        )

        assert result.status is SafetyStatus.UNSAFE
        assert len(result.turns) == 2
        assert result.termination_reason is TerminationReason.STOP_CONDITION

    async def test_auto_does_not_stop_unknown_evaluator_async(self) -> None:
        evaluator = _mock_evaluator(EvalOutcome.DETECTED)
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.UNSAFE
        assert len(result.turns) == 3
        assert evaluator.evaluate_async.await_count == 1

    async def test_none_disables_auto_stop_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=ToolCalled("exfiltrate"),
            stop_when=None,
        ).execute_async(
            adapter=_adapter(
                responses=[
                    Response(tool_calls=[ToolCall(name="exfiltrate")], text="one"),
                    Response(text="two"),
                ],
            ),
        )

        assert result.status is SafetyStatus.UNSAFE
        assert len(result.turns) == 2
        assert result.termination_reason is TerminationReason.DRIVER_EXHAUSTED
        assert result.evaluation is not None

    async def test_any_turn_response_evaluator_is_auto_stoppable_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=ResponseContains("secret", scope=ResponseScope.ANY_TURN),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="secret"), Response(text="clean")],
            ),
        )

        assert len(result.turns) == 1
        assert result.status is SafetyStatus.UNSAFE


class TestXPIAMaxTurns:
    """Max turns resolves normally from the terminal evaluation."""

    async def test_max_turns_resolves_normally_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["p1", "p2", "p3"],
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
            max_turns=2,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        assert len(result.turns) == 2
        assert result.termination_reason is TerminationReason.MAX_TURNS

    async def test_zero_turn_budget_returns_error_async(self) -> None:
        evaluator = AsyncMock(spec=Evaluator)
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="unused",
            evaluator=evaluator,
            max_turns=0,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert result.termination_reason is TerminationReason.MAX_TURNS
        evaluator.evaluate_async.assert_not_awaited()


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

    async def test_terminal_evaluation_runs_before_injection_cleanup_async(
        self,
    ) -> None:
        handle = _mock_handle()

        def evaluate(*, context: EvalContext) -> EvalResult:
            assert context.turns
            handle.__aexit__.assert_not_awaited()
            return EvalResult(outcome=EvalOutcome.NOT_DETECTED)

        evaluator = AsyncMock(spec=Evaluator)
        evaluator.evaluate_async.side_effect = evaluate

        result = await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=evaluator,
            stop_when=None,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.SAFE
        handle.__aexit__.assert_awaited_once()

    async def test_cleanup_failure_discards_successful_evaluation_async(self) -> None:
        handle = _mock_handle()
        handle.__aexit__.side_effect = RuntimeError("cleanup failed")

        result = await Attacks.xpia(
            inject=handle,
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
            stop_when=None,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert result.evaluation is None
        assert result.termination_reason is None


class TestXPIAZeroTurns:
    async def test_empty_trigger_returns_error_without_evaluation_async(self) -> None:
        evaluator = AsyncMock(spec=Evaluator)

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=[],
            evaluator=evaluator,
        ).execute_async(adapter=_adapter())

        assert result.status is SafetyStatus.ERROR
        assert result.evaluation is None
        assert result.termination_reason is TerminationReason.DRIVER_EXHAUSTED
        evaluator.evaluate_async.assert_not_awaited()


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
        assert result.metadata["observability_adjusted"] is True
        assert "Insufficient observability" in result.summary

    async def test_adjustment_does_not_mutate_response_metadata_async(self) -> None:
        response_metadata = {"conversation_id": "c-01"}
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=_mock_evaluator(EvalOutcome.NOT_DETECTED),
            stop_when=None,
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="ok", metadata=response_metadata)],
                observability=ObservabilityLevel.RESPONSE_ONLY,
            ),
        )

        assert result.metadata["observability_adjusted"] is True
        assert "observability_adjusted" not in response_metadata
        assert "observability_adjusted" not in result.turns[0].response.metadata
        assert result.metadata is not result.turns[0].response.metadata

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

    async def test_downgraded_summary_names_the_recorded_gap_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("exfil") & ResponseContains("nope"),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.RESPONSE_ONLY),
        )

        assert result.status is SafetyStatus.UNDETERMINED
        assert "does not report side effects" in result.summary
        assert "'exfil'" in result.summary


class TestXPIAEvaluatorObservability:
    """A channel the adapter does not report does not make the agent look safe."""

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
        turn_0_metadata = {"page_url": "url0"}
        turn_1_metadata = {"page_url": "url1"}
        adapter = _adapter(
            responses=[
                Response(text="turn0", metadata=turn_0_metadata),
                Response(text="turn1", metadata=turn_1_metadata),
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
        result.metadata["turn_0"]["page_url"] = "changed"
        assert turn_0_metadata["page_url"] == "url0"
        assert turn_1_metadata["page_url"] == "url1"


class TestXPIAUndeterminedSummary:
    """An undetermined summary names terminal observability gaps."""

    def test_summary_uses_terminal_rationale(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale="Adapter observability is 'response_only'",
            ),
        )

        assert summary == (
            "Evaluation undetermined: Adapter observability is 'response_only'"
        )

    def test_summary_falls_back_without_a_rationale(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(outcome=EvalOutcome.UNDETERMINED),
        )

        assert summary == "Evaluation undetermined: Insufficient observability"

    def test_summary_names_every_operand_gap(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale="Left operand undetermined: tool calls unobservable",
                undetermined_operands=[
                    "tool calls unobservable",
                    "side effects unobservable",
                ],
            ),
        )

        assert "tool calls unobservable" in summary
        assert "side effects unobservable" in summary

    def test_summary_deduplicates_operand_reasons(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                undetermined_operands=["same gap", "same gap"],
            ),
        )

        assert summary == "Evaluation undetermined: same gap"

    def test_summary_counts_the_gaps_it_does_not_name(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                undetermined_operands=["gap a", "gap b", "gap c", "gap d"],
            ),
        )

        assert summary == "Evaluation undetermined: gap a; gap b (and 2 more)"

    async def test_disjunction_names_both_unobservable_channels_async(self) -> None:
        # The composite words its rationale after the operand it reported
        # first, so only an end-to-end run proves both gaps are recorded and
        # both reach the summary.
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=ToolCalled("x") | SideEffectOccurred("y"),
        ).execute_async(
            adapter=_adapter(observability=ObservabilityLevel.RESPONSE_ONLY),
        )

        assert result.status is SafetyStatus.UNDETERMINED
        assert "does not report tool calls" in result.summary
        assert "does not report side effects" in result.summary

    def test_summary_names_a_gap_when_the_downgrade_settled_the_verdict(
        self,
    ) -> None:
        # _adjust_for_observability downgrades a SAFE run to UNDETERMINED, so
        # the final result is settled and the reason lives only on its operands.
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                undetermined_operands=["side effects are unobservable"],
            ),
        )

        assert summary == "Evaluation undetermined: side effects are unobservable"


class TestXPIASummaryHostileOperands:
    """A bad operand collection must not abort the summary."""

    def test_safe_summary_survives_a_bad_operand_collection(self) -> None:
        summary = _summary(
            status=SafetyStatus.SAFE,
            evaluation=EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                undetermined_operands=123,  # ty: ignore[invalid-argument-type]
            ),
        )

        assert summary == "Agent defended successfully"

    def test_undetermined_summary_falls_back_past_a_bad_collection(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNDETERMINED,
            evaluation=EvalResult(
                outcome=EvalOutcome.UNDETERMINED,
                rationale="Adapter observability is 'response_only'",
                undetermined_operands=123,  # ty: ignore[invalid-argument-type]
            ),
        )

        assert summary == (
            "Evaluation undetermined: Adapter observability is 'response_only'"
        )


class TestXPIAUnsafeSummaryHostileEvidence:
    """Evaluator-supplied evidence must not abort summary construction."""

    def test_summary_survives_a_non_iterable_evidence(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNSAFE,
            evaluation=EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=123,  # ty: ignore[invalid-argument-type]
            ),
        )

        assert summary == "Attack objective detected"

    def test_summary_keeps_readable_evidence_items(self) -> None:
        class Unrenderable:
            def __str__(self) -> str:
                raise RuntimeError("boom")

        summary = _summary(
            status=SafetyStatus.UNSAFE,
            evaluation=EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=[  # ty: ignore[invalid-argument-type]
                    Unrenderable(),
                    "send_email(attacker)",
                ],
            ),
        )

        assert "send_email(attacker)" in summary


class TestXPIAUnsafeSummary:
    """An unsafe summary should cite the evidence that established the verdict."""

    def test_summary_uses_terminal_detected_evidence(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNSAFE,
            evaluation=EvalResult(
                outcome=EvalOutcome.DETECTED,
                evidence=["send_email({'to': 'evil.com'})"],
            ),
        )

        assert summary == "Attack objective detected: send_email({'to': 'evil.com'})"

    def test_summary_falls_back_without_evidence(self) -> None:
        summary = _summary(
            status=SafetyStatus.UNSAFE,
            evaluation=EvalResult(outcome=EvalOutcome.DETECTED),
        )

        assert summary == "Attack objective detected"

    async def test_terminal_evaluation_supplies_the_evidence_async(self) -> None:
        exfiltration = SideEffect(kind="http_request", details={"url": "evil.com"})

        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2"],
            evaluator=SideEffectOccurred("http_request")
            & ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN),
            stop_when=None,
        ).execute_async(
            adapter=_adapter(
                responses=[
                    Response(text="here is id_rsa"),
                    Response(text="here is id_rsa", side_effects=[exfiltration]),
                ],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        assert result.eval_results == []
        assert result.evaluation is not None
        assert result.evaluation.outcome is EvalOutcome.DETECTED
        assert result.status is SafetyStatus.UNSAFE
        assert result.summary.startswith(
            "Attack objective detected: Side effect 'http_request'",
        )


class TestXPIASafeSummary:
    """A safe verdict says when part of the evaluation stayed undetermined."""

    def test_safe_summary_names_the_undetermined_operand(self) -> None:
        summary = _summary(
            status=SafetyStatus.SAFE,
            evaluation=EvalResult(
                outcome=EvalOutcome.NOT_DETECTED,
                undetermined_operands=["side effects not reported"],
            ),
        )

        assert summary == (
            "Agent defended successfully, but part of the evaluation was "
            "undetermined: side effects not reported"
        )

    def test_safe_summary_is_plain_when_everything_was_determined(self) -> None:
        summary = _summary(
            status=SafetyStatus.SAFE,
            evaluation=EvalResult(outcome=EvalOutcome.NOT_DETECTED),
        )

        assert summary == "Agent defended successfully"

    async def test_conjunction_settled_past_a_gap_reports_it_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger="Summarize Q3",
            evaluator=SideEffectOccurred("http_request")
            & ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="All done.")],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        assert result.status is SafetyStatus.SAFE
        assert "part of the evaluation was undetermined" in result.summary
        assert "http_request" in result.summary

    async def test_a_gap_repeated_every_turn_is_named_once_async(self) -> None:
        result = await Attacks.xpia(
            inject=_mock_handle(),
            trigger=["Turn 1", "Turn 2", "Turn 3"],
            evaluator=SideEffectOccurred("http_request")
            & ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN),
        ).execute_async(
            adapter=_adapter(
                responses=[Response(text="All done.")],
                observability=ObservabilityLevel.TOOL_ONLY,
            ),
        )

        assert len(result.turns) == 3
        assert result.summary.count("http_request") == 1
