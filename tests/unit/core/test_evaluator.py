# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.evaluator — Evaluator protocol, BaseEvaluator, composition."""

import pytest

from rampart.core.evaluator import BaseEvaluator, Evaluator, detected_is_absorbing
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Request,
    Response,
    Turn,
)
from rampart.evaluators import (
    ResponseContains,
    ResponseScope,
    SideEffectOccurred,
    ToolCalled,
)


class _StubEvaluator(BaseEvaluator):
    """Test helper that returns a fixed outcome."""

    def __init__(self, *, outcome: EvalOutcome, rationale: str = "stub") -> None:
        self._outcome = outcome
        self._rationale = rationale
        self.call_count = 0

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a fixed result and track call count."""
        self.call_count += 1
        return EvalResult(
            outcome=self._outcome,
            evidence=[f"stub:{self._outcome.value}"],
            rationale=self._rationale,
        )


class _OperandCarrier(BaseEvaluator):
    """Test helper that returns a chosen ``undetermined_operands`` collection."""

    def __init__(
        self,
        *,
        outcome: EvalOutcome,
        undetermined_operands: list[str],
    ) -> None:
        self._outcome = outcome
        self._undetermined_operands = undetermined_operands

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a fixed result carrying the chosen operand reasons."""
        return EvalResult(
            outcome=self._outcome,
            rationale="carrier",
            undetermined_operands=self._undetermined_operands,
        )


def _ctx() -> EvalContext:
    """Build a minimal EvalContext for testing."""
    return EvalContext(
        observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        turns=[Turn(request=Request(prompt="p"), response=Response(text="r"))],
    )


_OUTCOMES = (
    EvalOutcome.DETECTED,
    EvalOutcome.NOT_DETECTED,
    EvalOutcome.UNDETERMINED,
)


class TestEvaluatorProtocol:
    def test_is_runtime_checkable(self) -> None:
        class MyEvaluator:
            async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
                return EvalResult(outcome=EvalOutcome.DETECTED)

        assert isinstance(MyEvaluator(), Evaluator)

    def test_base_evaluator_satisfies_protocol(self) -> None:
        stub = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        assert isinstance(stub, Evaluator)


class TestAbsorbingDetectionClassification:
    def test_known_existential_evaluators_are_absorbing(self) -> None:
        assert detected_is_absorbing(ToolCalled("send")) is True
        assert detected_is_absorbing(SideEffectOccurred("write")) is True
        assert (
            detected_is_absorbing(
                ResponseContains("secret", scope=ResponseScope.ANY_TURN),
            )
            is True
        )

    def test_current_and_all_turn_response_scopes_are_not_detected_absorbing(
        self,
    ) -> None:
        assert (
            detected_is_absorbing(
                ResponseContains("secret", scope=ResponseScope.CURRENT_TURN),
            )
            is False
        )
        assert (
            detected_is_absorbing(
                ResponseContains("secret", scope=ResponseScope.ALL_TURNS),
            )
            is False
        )

    def test_composition_is_conservative(self) -> None:
        absorbing = ToolCalled("a") | SideEffectOccurred("b")
        mixed = ToolCalled("a") | _StubEvaluator(
            outcome=EvalOutcome.DETECTED,
        )
        absorbing_and = ToolCalled("a") & SideEffectOccurred("b")
        mixed_and = ToolCalled("a") & _StubEvaluator(
            outcome=EvalOutcome.DETECTED,
        )

        assert detected_is_absorbing(absorbing) is True
        assert detected_is_absorbing(mixed) is False
        assert detected_is_absorbing(absorbing_and) is True
        assert detected_is_absorbing(mixed_and) is False
        assert detected_is_absorbing(~absorbing) is False

    def test_negation_swaps_absorbing_outcomes(self) -> None:
        any_turn = ResponseContains("secret", scope=ResponseScope.ANY_TURN)
        all_turns = ResponseContains("secret", scope=ResponseScope.ALL_TURNS)

        assert detected_is_absorbing(~any_turn) is False
        assert detected_is_absorbing(~all_turns) is True

    def test_unknown_structural_evaluator_is_not_absorbing(self) -> None:
        class StructuralEvaluator:
            async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
                return EvalResult(outcome=EvalOutcome.DETECTED)

        assert detected_is_absorbing(StructuralEvaluator()) is False

    def test_unspecified_response_scope_is_not_absorbing(self) -> None:
        assert detected_is_absorbing(ResponseContains("secret")) is False


class TestOrComposition:
    async def test_left_detected_short_circuits_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert left.call_count == 1
        assert right.call_count == 0

    async def test_right_detected_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert left.call_count == 1
        assert right.call_count == 1

    async def test_neither_detected_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_undetermined_propagates_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_undetermined_names_operand_and_keeps_evidence_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED, rationale="cannot see")
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left | right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert "cannot see" in result.rationale
        assert result.evidence == ["stub:undetermined", "stub:not_detected"]


class TestAndComposition:
    async def test_left_not_detected_short_circuits_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert left.call_count == 1
        assert right.call_count == 0

    async def test_left_undetermined_evaluates_right_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert right.call_count == 1

    async def test_left_undetermined_right_not_detected_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_both_undetermined_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_undetermined_keeps_evidence_from_both_operands_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert result.evidence == ["stub:undetermined", "stub:detected"]

    async def test_both_detected_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED, rationale="L")
        right = _StubEvaluator(outcome=EvalOutcome.DETECTED, rationale="R")
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert len(result.evidence) == 2

    async def test_right_not_detected_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_right_undetermined_async(self) -> None:
        left = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = left & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED


class TestNotComposition:
    async def test_flips_detected_to_not_detected_async(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_flips_not_detected_to_detected_async(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED

    async def test_preserves_undetermined_async(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_preserves_confidence_and_evidence_async(self) -> None:
        inner = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = ~inner

        result = await composed.evaluate_async(context=_ctx())

        assert result.evidence == ["stub:detected"]
        assert "NOT" in result.rationale


class TestCompositionAlgebra:
    """The operators must behave as three-valued logic, whatever the order."""

    async def test_and_outcome_table_async(self) -> None:
        detected = EvalOutcome.DETECTED
        not_detected = EvalOutcome.NOT_DETECTED
        undetermined = EvalOutcome.UNDETERMINED
        expected = {
            (detected, detected): detected,
            (detected, not_detected): not_detected,
            (detected, undetermined): undetermined,
            (not_detected, detected): not_detected,
            (not_detected, not_detected): not_detected,
            (not_detected, undetermined): not_detected,
            (undetermined, detected): undetermined,
            (undetermined, not_detected): not_detected,
            (undetermined, undetermined): undetermined,
        }

        for (left, right), outcome in expected.items():
            composed = _StubEvaluator(outcome=left) & _StubEvaluator(outcome=right)

            result = await composed.evaluate_async(context=_ctx())

            assert result.outcome is outcome, f"{left} & {right}"

    async def test_or_outcome_table_async(self) -> None:
        detected = EvalOutcome.DETECTED
        not_detected = EvalOutcome.NOT_DETECTED
        undetermined = EvalOutcome.UNDETERMINED
        expected = {
            (detected, detected): detected,
            (detected, not_detected): detected,
            (detected, undetermined): detected,
            (not_detected, detected): detected,
            (not_detected, not_detected): not_detected,
            (not_detected, undetermined): undetermined,
            (undetermined, detected): detected,
            (undetermined, not_detected): undetermined,
            (undetermined, undetermined): undetermined,
        }

        for (left, right), outcome in expected.items():
            composed = _StubEvaluator(outcome=left) | _StubEvaluator(outcome=right)

            result = await composed.evaluate_async(context=_ctx())

            assert result.outcome is outcome, f"{left} | {right}"

    async def test_and_is_commutative_async(self) -> None:
        for left in _OUTCOMES:
            for right in _OUTCOMES:
                forward = _StubEvaluator(outcome=left) & _StubEvaluator(outcome=right)
                flipped = _StubEvaluator(outcome=right) & _StubEvaluator(outcome=left)

                forward_result = await forward.evaluate_async(context=_ctx())
                flipped_result = await flipped.evaluate_async(context=_ctx())

                assert forward_result.outcome is flipped_result.outcome, (
                    f"{left} & {right}"
                )

    async def test_or_is_commutative_async(self) -> None:
        for left in _OUTCOMES:
            for right in _OUTCOMES:
                forward = _StubEvaluator(outcome=left) | _StubEvaluator(outcome=right)
                flipped = _StubEvaluator(outcome=right) | _StubEvaluator(outcome=left)

                forward_result = await forward.evaluate_async(context=_ctx())
                flipped_result = await flipped.evaluate_async(context=_ctx())

                assert forward_result.outcome is flipped_result.outcome, (
                    f"{left} | {right}"
                )

    async def test_de_morgan_negated_and_async(self) -> None:
        for left in _OUTCOMES:
            for right in _OUTCOMES:
                negated_and = ~(
                    _StubEvaluator(outcome=left) & _StubEvaluator(outcome=right)
                )
                or_of_negations = ~_StubEvaluator(outcome=left) | ~_StubEvaluator(
                    outcome=right,
                )

                negated_result = await negated_and.evaluate_async(context=_ctx())
                or_result = await or_of_negations.evaluate_async(context=_ctx())

                assert negated_result.outcome is or_result.outcome, (
                    f"NOT ({left} & {right})"
                )

    async def test_de_morgan_negated_or_async(self) -> None:
        for left in _OUTCOMES:
            for right in _OUTCOMES:
                negated_or = ~(
                    _StubEvaluator(outcome=left) | _StubEvaluator(outcome=right)
                )
                and_of_negations = ~_StubEvaluator(outcome=left) & ~_StubEvaluator(
                    outcome=right,
                )

                negated_result = await negated_or.evaluate_async(context=_ctx())
                and_result = await and_of_negations.evaluate_async(context=_ctx())

                assert negated_result.outcome is and_result.outcome, (
                    f"NOT ({left} | {right})"
                )

    async def test_and_is_associative_async(self) -> None:
        for first in _OUTCOMES:
            for second in _OUTCOMES:
                for third in _OUTCOMES:
                    left_grouped = (
                        _StubEvaluator(outcome=first) & _StubEvaluator(outcome=second)
                    ) & _StubEvaluator(outcome=third)
                    right_grouped = _StubEvaluator(outcome=first) & (
                        _StubEvaluator(outcome=second) & _StubEvaluator(outcome=third)
                    )

                    left_result = await left_grouped.evaluate_async(context=_ctx())
                    right_result = await right_grouped.evaluate_async(context=_ctx())

                    assert left_result.outcome is right_result.outcome, (
                        f"{first} & {second} & {third}"
                    )

    async def test_or_is_associative_async(self) -> None:
        for first in _OUTCOMES:
            for second in _OUTCOMES:
                for third in _OUTCOMES:
                    left_grouped = (
                        _StubEvaluator(outcome=first) | _StubEvaluator(outcome=second)
                    ) | _StubEvaluator(outcome=third)
                    right_grouped = _StubEvaluator(outcome=first) | (
                        _StubEvaluator(outcome=second) | _StubEvaluator(outcome=third)
                    )

                    left_result = await left_grouped.evaluate_async(context=_ctx())
                    right_result = await right_grouped.evaluate_async(context=_ctx())

                    assert left_result.outcome is right_result.outcome, (
                        f"{first} | {second} | {third}"
                    )


class TestCompositionChaining:
    async def test_or_and_not_chain_async(self) -> None:
        a = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        b = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        c = _StubEvaluator(outcome=EvalOutcome.DETECTED)

        composed = (a | b) & ~c

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_composed_evaluators_are_composable_async(self) -> None:
        a = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        b = _StubEvaluator(outcome=EvalOutcome.DETECTED)

        first = a | b
        second = ~first

        assert isinstance(first, BaseEvaluator)
        assert isinstance(second, BaseEvaluator)

        result = await second.evaluate_async(context=_ctx())
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestUndeterminedOperands:
    """A settled outcome still says which operand was never determined."""

    async def test_and_records_the_operand_it_settled_past_async(self) -> None:
        left = _StubEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
            rationale="side effects not reported",
        )
        composed = left & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.undetermined_operands == ["side effects not reported"]

    async def test_or_records_the_operand_it_settled_past_async(self) -> None:
        left = _StubEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
            rationale="tool calls not reported",
        )
        composed = left | _StubEvaluator(outcome=EvalOutcome.DETECTED)

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert result.undetermined_operands == ["tool calls not reported"]

    async def test_records_every_operand_that_ran_undetermined_async(self) -> None:
        detected = EvalOutcome.DETECTED
        not_detected = EvalOutcome.NOT_DETECTED
        undetermined = EvalOutcome.UNDETERMINED
        expected = {
            ("&", detected, detected): [],
            ("&", detected, not_detected): [],
            ("&", detected, undetermined): ["right"],
            ("&", not_detected, detected): [],
            ("&", not_detected, not_detected): [],
            ("&", not_detected, undetermined): [],
            ("&", undetermined, detected): ["left"],
            ("&", undetermined, not_detected): ["left"],
            ("&", undetermined, undetermined): ["left", "right"],
            ("|", detected, detected): [],
            ("|", detected, not_detected): [],
            ("|", detected, undetermined): [],
            ("|", not_detected, detected): [],
            ("|", not_detected, not_detected): [],
            ("|", not_detected, undetermined): ["right"],
            ("|", undetermined, detected): ["left"],
            ("|", undetermined, not_detected): ["left"],
            ("|", undetermined, undetermined): ["left", "right"],
        }

        for (operator, left, right), reasons in expected.items():
            operands = (
                _StubEvaluator(outcome=left, rationale="left"),
                _StubEvaluator(outcome=right, rationale="right"),
            )
            composed = (
                operands[0] & operands[1]
                if operator == "&"
                else operands[0] | operands[1]
            )

            result = await composed.evaluate_async(context=_ctx())

            assert result.undetermined_operands == reasons, f"{left} {operator} {right}"

    async def test_a_nested_gap_is_named_not_restated_async(self) -> None:
        channels = ["first", "second", "third", "fourth"]
        either = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED, rationale=channels[0])
        for channel in channels[1:]:
            either |= _StubEvaluator(
                outcome=EvalOutcome.UNDETERMINED,
                rationale=channel,
            )
        composed = either & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.undetermined_operands == channels

    async def test_a_gap_reached_by_two_paths_is_recorded_once_async(self) -> None:
        gap = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED, rationale="cannot look")
        composed = gap & (gap & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED))

        result = await composed.evaluate_async(context=_ctx())

        assert result.undetermined_operands == ["cannot look"]

    async def test_short_circuit_cannot_record_an_operand_it_skipped_async(
        self,
    ) -> None:
        right = _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)
        composed = _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED) & right

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert right.call_count == 0
        assert result.undetermined_operands == []

    async def test_survives_another_level_of_composition_async(self) -> None:
        inner = _StubEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
            rationale="cannot look",
        ) & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)
        expected = ["cannot look"]

        for composed in (
            inner | _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED),
            inner & _StubEvaluator(outcome=EvalOutcome.DETECTED),
            _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED) | inner,
        ):
            result = await composed.evaluate_async(context=_ctx())

            assert result.undetermined_operands == expected

    async def test_the_same_gap_reached_twice_is_recorded_once_async(self) -> None:
        gap = _StubEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
            rationale="cannot look",
        ) & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)

        result = await (gap | gap).evaluate_async(context=_ctx())

        assert result.undetermined_operands == ["cannot look"]

    async def test_an_operand_without_a_reason_is_still_recorded_async(self) -> None:
        for rationale in ("", "   ", "\t"):
            silent = _StubEvaluator(
                outcome=EvalOutcome.UNDETERMINED,
                rationale=rationale,
            )

            for composed in (
                silent & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED),
                silent | _StubEvaluator(outcome=EvalOutcome.DETECTED),
            ):
                result = await composed.evaluate_async(context=_ctx())

                assert result.undetermined_operands == ["an operand gave no reason"]

    async def test_a_settled_three_operand_tree_names_every_gap_once_async(
        self,
    ) -> None:
        for first in _OUTCOMES:
            for second in _OUTCOMES:
                for third in _OUTCOMES:
                    outcomes = (first, second, third)
                    operands = [
                        _StubEvaluator(outcome=outcome, rationale=f"g{index}")
                        for index, outcome in enumerate(outcomes)
                    ]
                    for composed in (
                        (operands[0] & operands[1]) | operands[2],
                        (operands[0] | operands[1]) & operands[2],
                        operands[0] & (operands[1] | operands[2]),
                        operands[0] | (operands[1] & operands[2]),
                    ):
                        for operand in operands:
                            operand.call_count = 0

                        result = await composed.evaluate_async(context=_ctx())

                        ran_undetermined = [
                            f"g{index}"
                            for index, operand in enumerate(operands)
                            if operand.call_count
                            and outcomes[index] is EvalOutcome.UNDETERMINED
                        ]
                        recorded = result.undetermined_operands
                        assert recorded == ran_undetermined

    async def test_not_carries_it_through_the_flip_async(self) -> None:
        inner = _StubEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
            rationale="cannot look",
        ) & _StubEvaluator(outcome=EvalOutcome.NOT_DETECTED)

        result = await (~inner).evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert result.undetermined_operands == ["cannot look"]

    async def test_carried_operands_are_stripped_before_dedup_async(self) -> None:
        # A padded reason and its bare form name the same gap, so the merge
        # must strip before deduping rather than keep both as distinct entries.
        left = _OperandCarrier(
            outcome=EvalOutcome.DETECTED,
            undetermined_operands=["gap"],
        )
        right = _OperandCarrier(
            outcome=EvalOutcome.DETECTED,
            undetermined_operands=[" gap ", "gap", "other"],
        )

        result = await (left & right).evaluate_async(context=_ctx())

        assert result.undetermined_operands == ["gap", "other"]


class _HostileEvidenceEvaluator(BaseEvaluator):
    """Returns an evidence collection that cannot be iterated."""

    def __init__(self, *, outcome: EvalOutcome) -> None:
        self._outcome = outcome

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a result whose evidence is not a list."""
        return EvalResult(
            outcome=self._outcome,
            evidence=123,  # ty: ignore[invalid-argument-type]
            rationale="hostile",
        )


class TestCompositionToleratesHostileEvidence:
    """A bad evidence collection must not cost the composed verdict."""

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_left_evidence_keeps_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        hostile = _HostileEvidenceEvaluator(outcome=left)
        readable = _StubEvaluator(outcome=right)
        composed = hostile & readable if operator == "and" else hostile | readable

        result = await composed.evaluate_async(context=_ctx())

        assert all(isinstance(e, str) for e in result.evidence)
        assert "123" not in result.evidence

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_right_evidence_keeps_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        readable = _StubEvaluator(outcome=left)
        hostile = _HostileEvidenceEvaluator(outcome=right)
        composed = readable & hostile if operator == "and" else readable | hostile

        result = await composed.evaluate_async(context=_ctx())

        assert all(isinstance(e, str) for e in result.evidence)
        assert "123" not in result.evidence

    @pytest.mark.parametrize(
        "outcome",
        [EvalOutcome.DETECTED, EvalOutcome.NOT_DETECTED],
    )
    async def test_negation_normalizes_evidence_it_flips_async(
        self,
        outcome: EvalOutcome,
    ) -> None:
        result = await (~_HostileEvidenceEvaluator(outcome=outcome)).evaluate_async(
            context=_ctx(),
        )

        assert result.evidence == []

    async def test_negation_passes_an_undetermined_result_through_async(self) -> None:
        # `~` returns the inner result unchanged when it is UNDETERMINED, as it
        # does on main, so nothing about it is normalized here.
        inner = _HostileEvidenceEvaluator(outcome=EvalOutcome.UNDETERMINED)

        result = await (~inner).evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert result.evidence == 123

    async def test_conjunction_keeps_readable_evidence_async(self) -> None:
        composed = _HostileEvidenceEvaluator(
            outcome=EvalOutcome.DETECTED,
        ) & _StubEvaluator(outcome=EvalOutcome.DETECTED)

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["stub:detected"]

    async def test_disjunction_keeps_readable_evidence_async(self) -> None:
        composed = _HostileEvidenceEvaluator(
            outcome=EvalOutcome.UNDETERMINED,
        ) | _StubEvaluator(outcome=EvalOutcome.UNDETERMINED)

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is EvalOutcome.UNDETERMINED
        assert result.evidence == ["stub:undetermined"]


class _Unrenderable:
    """Stands in for an evaluator value whose ``__str__`` raises."""

    def __str__(self) -> str:
        raise RuntimeError("boom")


class _HostileRationaleEvaluator(BaseEvaluator):
    """Returns a rationale that cannot be rendered."""

    def __init__(self, *, outcome: EvalOutcome) -> None:
        self._outcome = outcome

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a result whose rationale raises when it is rendered."""
        return EvalResult(
            outcome=self._outcome,
            evidence=["hostile"],
            rationale=_Unrenderable(),  # ty: ignore[invalid-argument-type]
        )


class _SneakyRationale(str):  # ruff: ignore[subclass-builtin]
    """A rationale that is a str subclass and overrides what the code calls next.

    ``str()`` accepts a ``__str__`` that returns a subclass, so containment has
    to hand back an exact ``str`` or the rendered value still runs this code.
    """

    __slots__ = ()

    def __str__(self) -> str:
        return self

    def strip(self, chars: str | None = None) -> str:
        raise RuntimeError("boom")


class _SneakyRationaleEvaluator(BaseEvaluator):
    """Returns a rationale that is a hostile str subclass."""

    def __init__(self, *, outcome: EvalOutcome) -> None:
        self._outcome = outcome

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a result whose rationale is a hostile str subclass."""
        return EvalResult(
            outcome=self._outcome,
            rationale=_SneakyRationale("the operand could not look"),
        )


class _HostileOperandsEvaluator(BaseEvaluator):
    """Returns an undetermined-operand collection that cannot be iterated."""

    def __init__(self, *, outcome: EvalOutcome) -> None:
        self._outcome = outcome

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Return a result whose undetermined_operands is not a list."""
        return EvalResult(
            outcome=self._outcome,
            rationale="hostile",
            undetermined_operands=123,  # ty: ignore[invalid-argument-type]
        )


async def _readable_outcome_async(
    *,
    left: EvalOutcome,
    right: EvalOutcome,
    operator: str,
) -> EvalOutcome:
    """Compose two readable stubs the same way, to compare a verdict against.

    A differential oracle, not an independent one. The outcome table itself is
    pinned by ``TestOrComposition``, ``TestAndComposition`` and
    ``TestCompositionAlgebra``; what the sweeps below add is that swapping a
    readable operand for a hostile one moves nothing.
    """
    first = _StubEvaluator(outcome=left)
    second = _StubEvaluator(outcome=right)
    composed = first & second if operator == "and" else first | second
    result = await composed.evaluate_async(context=_ctx())
    return result.outcome


class TestCompositionToleratesHostileRationale:
    """A rationale that cannot be rendered must not cost the composed verdict."""

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_left_rationale_keeps_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        hostile = _HostileRationaleEvaluator(outcome=left)
        readable = _StubEvaluator(outcome=right)
        composed = hostile & readable if operator == "and" else hostile | readable
        expected = await _readable_outcome_async(
            left=left,
            right=right,
            operator=operator,
        )

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is expected
        assert all(isinstance(r, str) for r in result.undetermined_operands)

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_right_rationale_keeps_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        readable = _StubEvaluator(outcome=left)
        hostile = _HostileRationaleEvaluator(outcome=right)
        composed = readable & hostile if operator == "and" else readable | hostile
        expected = await _readable_outcome_async(
            left=left,
            right=right,
            operator=operator,
        )

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is expected
        assert all(isinstance(r, str) for r in result.undetermined_operands)

    @pytest.mark.parametrize(
        "outcome",
        [EvalOutcome.DETECTED, EvalOutcome.NOT_DETECTED],
    )
    async def test_negation_renders_the_rationale_it_flips_async(
        self,
        outcome: EvalOutcome,
    ) -> None:
        result = await (~_HostileRationaleEvaluator(outcome=outcome)).evaluate_async(
            context=_ctx(),
        )

        assert result.rationale == "NOT (<unprintable value>)"

    @pytest.mark.parametrize(
        ("left", "operator", "right", "expected"),
        [
            (
                EvalOutcome.NOT_DETECTED,
                "and",
                EvalOutcome.DETECTED,
                "Left operand not detected: <unprintable value>",
            ),
            (
                EvalOutcome.DETECTED,
                "and",
                EvalOutcome.NOT_DETECTED,
                "Right operand not detected: <unprintable value>",
            ),
            (
                EvalOutcome.UNDETERMINED,
                "and",
                EvalOutcome.DETECTED,
                "Left operand undetermined: <unprintable value>",
            ),
            (
                EvalOutcome.DETECTED,
                "and",
                EvalOutcome.UNDETERMINED,
                "Right operand undetermined: <unprintable value>",
            ),
            (
                EvalOutcome.DETECTED,
                "and",
                EvalOutcome.DETECTED,
                "(<unprintable value>) AND (<unprintable value>)",
            ),
            (
                EvalOutcome.UNDETERMINED,
                "or",
                EvalOutcome.NOT_DETECTED,
                "Left operand undetermined: <unprintable value>",
            ),
            (
                EvalOutcome.NOT_DETECTED,
                "or",
                EvalOutcome.UNDETERMINED,
                "Right operand undetermined: <unprintable value>",
            ),
        ],
    )
    async def test_every_worded_rationale_names_the_contained_value_async(
        self,
        left: EvalOutcome,
        operator: str,
        right: EvalOutcome,
        expected: str,
    ) -> None:
        # One case per branch that words a rationale of its own, so the content
        # is pinned and not only the fact that the guard did not raise.
        lhs = _HostileRationaleEvaluator(outcome=left)
        rhs = _HostileRationaleEvaluator(outcome=right)
        composed = lhs & rhs if operator == "and" else lhs | rhs

        result = await composed.evaluate_async(context=_ctx())

        assert result.rationale == expected

    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_a_string_subclass_rationale_is_recorded_async(
        self,
        operator: str,
    ) -> None:
        sneaky = _SneakyRationaleEvaluator(outcome=EvalOutcome.UNDETERMINED)
        readable = _StubEvaluator(outcome=EvalOutcome.DETECTED)
        composed = sneaky & readable if operator == "and" else sneaky | readable

        result = await composed.evaluate_async(context=_ctx())

        assert result.undetermined_operands == ["the operand could not look"]
        assert [type(r) for r in result.undetermined_operands] == [str]


class TestCompositionToleratesHostileOperands:
    """A bad operand collection must not cost the composed verdict either."""

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_left_operands_keep_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        hostile = _HostileOperandsEvaluator(outcome=left)
        readable = _StubEvaluator(outcome=right)
        composed = hostile & readable if operator == "and" else hostile | readable
        expected = await _readable_outcome_async(
            left=left,
            right=right,
            operator=operator,
        )

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is expected
        assert all(isinstance(r, str) for r in result.undetermined_operands)

    @pytest.mark.parametrize("left", _OUTCOMES)
    @pytest.mark.parametrize("right", _OUTCOMES)
    @pytest.mark.parametrize("operator", ["and", "or"])
    async def test_hostile_right_operands_keep_the_verdict_async(
        self,
        left: EvalOutcome,
        right: EvalOutcome,
        operator: str,
    ) -> None:
        readable = _StubEvaluator(outcome=left)
        hostile = _HostileOperandsEvaluator(outcome=right)
        composed = readable & hostile if operator == "and" else readable | hostile
        expected = await _readable_outcome_async(
            left=left,
            right=right,
            operator=operator,
        )

        result = await composed.evaluate_async(context=_ctx())

        assert result.outcome is expected
        assert all(isinstance(r, str) for r in result.undetermined_operands)

    @pytest.mark.parametrize(
        "outcome",
        [EvalOutcome.DETECTED, EvalOutcome.NOT_DETECTED],
    )
    async def test_negation_normalizes_operands_it_flips_async(
        self,
        outcome: EvalOutcome,
    ) -> None:
        result = await (~_HostileOperandsEvaluator(outcome=outcome)).evaluate_async(
            context=_ctx(),
        )

        assert result.undetermined_operands == []
