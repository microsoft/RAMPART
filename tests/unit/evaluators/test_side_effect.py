# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.side_effect — SideEffectOccurred evaluator."""

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    ObservabilityLevel,
    Request,
    Response,
    SideEffect,
    Turn,
)
from rampart.evaluators import ResponseContains, SideEffectOccurred


def _ctx_with_side_effects(
    *effects: SideEffect,
    observability: ObservabilityLevel = ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
) -> EvalContext:
    """Build a single-turn EvalContext with the given side effects."""
    return EvalContext(
        turns=[
            Turn(
                request=Request(prompt="test"),
                response=Response(text="ok", side_effects=list(effects)),
            ),
        ],
        observability_level=observability,
    )


class TestSideEffectOccurredDetection:
    async def test_detects_by_kind_async(self) -> None:
        ctx = _ctx_with_side_effects(SideEffect(kind="http_request"))
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_wrong_kind_async(self) -> None:
        ctx = _ctx_with_side_effects(SideEffect(kind="file_write"))
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_not_detected_no_effects_async(self) -> None:
        ctx = _ctx_with_side_effects()
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestSideEffectOccurredDetailPredicates:
    async def test_exact_detail_match_async(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://evil.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url="https://evil.com",
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_exact_detail_mismatch_async(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://safe.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url="https://evil.com",
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_predicate_detail_match_async(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://evil.com/data"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url=lambda u: "evil.com" in str(u),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED

    async def test_predicate_detail_mismatch_async(self) -> None:
        se = SideEffect(kind="http_request", details={"url": "https://safe.com"})
        ctx = _ctx_with_side_effects(se)
        result = await SideEffectOccurred(
            "http_request",
            url=lambda u: "evil.com" in str(u),
        ).evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestSideEffectOccurredObservability:
    """A missing side effect is only evidence when the adapter reports them."""

    async def test_undetermined_when_side_effects_not_reported_async(self) -> None:
        ctx = _ctx_with_side_effects(observability=ObservabilityLevel.TOOL_ONLY)
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_undetermined_for_response_only_async(self) -> None:
        ctx = _ctx_with_side_effects(observability=ObservabilityLevel.RESPONSE_ONLY)
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_undetermined_rationale_names_level_and_kind_async(self) -> None:
        ctx = _ctx_with_side_effects(observability=ObservabilityLevel.TOOL_ONLY)
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert "tool_only" in result.rationale
        assert "http_request" in result.rationale

    async def test_not_detected_when_side_effects_are_reported_async(self) -> None:
        ctx = _ctx_with_side_effects()
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_reported_effect_detected_below_declared_level_async(self) -> None:
        ctx = _ctx_with_side_effects(
            SideEffect(kind="http_request"),
            observability=ObservabilityLevel.TOOL_ONLY,
        )
        result = await SideEffectOccurred("http_request").evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED


class TestSideEffectOccurredComposedWhenUnobserved:
    """How an unobserved side-effect check combines with an observable one.

    The two operators answer different questions, and the difference only
    shows up when one operand cannot be observed. These pin that difference
    so a change to it has to be deliberate.
    """

    async def test_and_is_settled_by_the_observable_operand_async(self) -> None:
        ctx = _ctx_with_side_effects(observability=ObservabilityLevel.TOOL_ONLY)
        unobserved = SideEffectOccurred("http_request")
        text = ResponseContains("id_rsa")

        forward = await (unobserved & text).evaluate_async(context=ctx)
        flipped = await (text & unobserved).evaluate_async(context=ctx)

        assert forward.outcome is EvalOutcome.NOT_DETECTED
        assert flipped.outcome is EvalOutcome.NOT_DETECTED

    async def test_or_stays_undetermined_when_one_side_unobserved_async(self) -> None:
        ctx = _ctx_with_side_effects(observability=ObservabilityLevel.TOOL_ONLY)
        unobserved = SideEffectOccurred("http_request")
        text = ResponseContains("id_rsa")

        forward = await (unobserved | text).evaluate_async(context=ctx)
        flipped = await (text | unobserved).evaluate_async(context=ctx)

        assert forward.outcome is EvalOutcome.UNDETERMINED
        assert flipped.outcome is EvalOutcome.UNDETERMINED
