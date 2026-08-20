# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.evaluator — Evaluator protocol, BaseEvaluator, composition."""

from rampart.core.evaluator import BaseEvaluator, Evaluator
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    Request,
    Response,
    Turn,
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


def _ctx() -> EvalContext:
    """Build a minimal EvalContext for testing."""
    return EvalContext(
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
