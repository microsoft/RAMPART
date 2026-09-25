# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.result.

Result, SafetyStatus, HarmCategory, resolve functions.
"""

import pytest

from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
    PopulationRef,
    PopulationResult,
    Result,
    SafetyStatus,
    _explain_undetermined,
    _summarize_undetermined_operands,
    resolve_as_attack,
    resolve_as_probe,
    resolve_attack_verdict,
    resolve_probe_verdict,
)
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Request,
    Response,
    TraceEndReason,
    Turn,
)


class _RaisingIter:
    """Stands in for an evaluator whose operand collection cannot be iterated."""

    def __iter__(self) -> object:
        raise RuntimeError("boom")


def _er(outcome: EvalOutcome) -> EvalResult:
    """Shorthand to build an EvalResult with a given outcome."""
    return EvalResult(outcome=outcome)


def _result(status: SafetyStatus) -> Result:
    """Build a minimal result with the requested status."""
    return Result(
        observability_level=ObservabilityLevel.RESPONSE_ONLY,
        status=status,
        summary=status.value,
    )


class TestSafetyStatus:
    def test_values(self) -> None:
        assert SafetyStatus.SAFE.value == "safe"
        assert SafetyStatus.UNSAFE.value == "unsafe"
        assert SafetyStatus.UNDETERMINED.value == "undetermined"
        assert SafetyStatus.ERROR.value == "error"


class TestHarmCategory:
    def test_is_strenum(self) -> None:
        assert isinstance(HarmCategory.PROMPT_INJECTION, str)

    def test_values_are_plain_strings(self) -> None:
        assert HarmCategory.PROMPT_INJECTION == "prompt_injection"
        assert HarmCategory.JAILBREAK == "jailbreak"
        assert HarmCategory.DATA_EXFILTRATION == "data_exfiltration"
        assert HarmCategory.OVER_PERMISSIVE_ACTION == "over_permissive_action"
        assert HarmCategory.DATA_LEAKAGE == "data_leakage"
        assert HarmCategory.CONTENT_SAFETY == "content_safety"
        assert HarmCategory.HALLUCINATION == "hallucination"
        assert HarmCategory.BEHAVIORAL_REGRESSION == "behavioral_regression"

    def test_xpia_is_not_a_harm_category(self) -> None:
        assert not hasattr(HarmCategory, "XPIA")

    def test_interchangeable_with_plain_string(self) -> None:
        assert HarmCategory.PROMPT_INJECTION == "prompt_injection"
        assert HarmCategory.PROMPT_INJECTION == "prompt_injection"

    def test_usable_as_dict_key(self) -> None:
        d: dict[str, int] = {HarmCategory.DATA_EXFILTRATION: 1, "custom_risk": 2}
        assert d["data_exfiltration"] == 1
        assert d[HarmCategory.DATA_EXFILTRATION] == 1


class TestInjectionRecord:
    def test_construction(self) -> None:
        rec = InjectionRecord(payload_id="abc123", surface_name="SharePoint")
        assert rec.payload_id == "abc123"
        assert rec.surface_name == "SharePoint"

    def test_none_payload_id(self) -> None:
        rec = InjectionRecord(payload_id=None, surface_name="Exchange")
        assert rec.payload_id is None


class TestResult:
    def test_observability_level_is_required(self) -> None:
        with pytest.raises(TypeError, match="observability_level"):
            Result(  # ty: ignore[missing-argument]
                status=SafetyStatus.SAFE,
                summary="ok",
            )

    def test_bool_returns_safe_true(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )
        assert bool(r) is True

    def test_bool_returns_safe_false(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
        )
        assert bool(r) is False

    def test_assert_safe_pattern(self) -> None:
        safe_result = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )
        assert safe_result, safe_result.summary

        unsafe_result = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="attack detected",
        )
        with pytest.raises(AssertionError):
            assert unsafe_result, unsafe_result.summary

    def test_repr(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="Agent defended",
        )
        assert "safe=True" in repr(r)
        assert "safe" in repr(r)
        assert "Agent defended" in repr(r)

    def test_defaults(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )
        assert r.turns == []
        assert r.turn_evaluations == []
        assert r.duration_seconds == pytest.approx(0.0)
        assert r.harm_category is None
        assert r.strategy == ""
        assert r.observability_level is ObservabilityLevel.RESPONSE_ONLY
        assert r.injections == []
        assert r.metadata == {}
        assert r.terminal_evaluation is None
        assert r.trace_end_reason is None

    def test_terminal_evaluation_and_trace_end_reason_round_trip(self) -> None:
        evaluation = _er(EvalOutcome.DETECTED)
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            terminal_evaluation=evaluation,
            trace_end_reason=TraceEndReason.STOP_CONDITION_MET,
        )
        assert r.terminal_evaluation is evaluation
        assert r.trace_end_reason is TraceEndReason.STOP_CONDITION_MET

    def test_harm_category_accepts_enum(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
            harm_category=HarmCategory.DATA_EXFILTRATION,
        )
        assert r.harm_category == "data_exfiltration"
        assert r.harm_category == HarmCategory.DATA_EXFILTRATION

    def test_harm_category_accepts_plain_string(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
            harm_category="custom_product_risk",
        )
        assert r.harm_category == "custom_product_risk"


class TestPopulationResult:
    def test_passes_at_exact_threshold(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.UNSAFE),
                _result(SafetyStatus.UNSAFE),
            ],
            threshold=0.6,
        )

        assert population.status is SafetyStatus.SAFE
        assert population.pass_rate == pytest.approx(0.6)
        assert bool(population) is True

    def test_fails_below_threshold_with_unsafe_status(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.UNSAFE),
            ],
            threshold=0.6,
        )

        assert population.status is SafetyStatus.UNSAFE
        assert bool(population) is False

    def test_error_takes_precedence_over_passing_rate(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.ERROR),
            ],
            threshold=0.5,
        )

        assert population.status is SafetyStatus.ERROR

    def test_all_error_returns_error(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.ERROR),
                _result(SafetyStatus.ERROR),
            ],
            threshold=0.5,
        )

        assert population.status is SafetyStatus.ERROR

    def test_undetermined_counts_against_pass_rate(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.SAFE),
                _result(SafetyStatus.UNDETERMINED),
            ],
            threshold=0.75,
        )

        assert population.pass_rate == pytest.approx(0.5)
        assert population.status is SafetyStatus.UNDETERMINED

    def test_all_undetermined_returns_undetermined(self) -> None:
        population = PopulationResult(
            results=[
                _result(SafetyStatus.UNDETERMINED),
                _result(SafetyStatus.UNDETERMINED),
            ],
            threshold=0.5,
        )

        assert population.status is SafetyStatus.UNDETERMINED

    @pytest.mark.parametrize("threshold", [-0.1, 1.1])
    def test_rejects_threshold_outside_valid_range(self, threshold: float) -> None:
        with pytest.raises(ValueError, match="threshold must be between"):
            PopulationResult(results=[], threshold=threshold)

    @pytest.mark.parametrize("threshold", [True, float("nan"), float("inf")])
    def test_rejects_invalid_threshold(self, threshold: object) -> None:
        with pytest.raises((TypeError, ValueError)):
            PopulationResult(
                results=[],
                threshold=threshold,  # ty: ignore[invalid-argument-type]
            )

    def test_summary_contains_population_verdict(self) -> None:
        population = PopulationResult(
            results=[_result(SafetyStatus.SAFE), _result(SafetyStatus.UNSAFE)],
            threshold=0.5,
        )

        assert population.summary == (
            "1/2 trials safe (50.0% pass rate, threshold: 50.0%); status: safe"
        )

    def test_repr(self) -> None:
        population = PopulationResult(
            results=[_result(SafetyStatus.SAFE), _result(SafetyStatus.UNSAFE)],
            threshold=0.5,
        )

        assert repr(population) == (
            "PopulationResult(safe=True, status=safe, safe_count=1, "
            "executed_count=2, pass_rate=0.5, threshold=0.5)"
        )


class TestPopulationRef:
    def test_accepts_generated_shape(self) -> None:
        ref = PopulationRef(id="a" * 32, index=2, size=5, threshold=0.8)
        assert ref.index == 2

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"id": ""}, "id must be non-empty"),
            ({"index": -1}, "index must be"),
            ({"index": 5}, "index must be"),
            ({"size": 0}, "size must be"),
            ({"threshold": float("nan")}, "threshold must be finite"),
            ({"threshold": 1.1}, "threshold must be between"),
        ],
    )
    def test_rejects_invalid_provenance(
        self,
        overrides: dict[str, object],
        message: str,
    ) -> None:
        values: dict[str, object] = {
            "id": "population-1",
            "index": 0,
            "size": 5,
            "threshold": 0.8,
        }
        values.update(overrides)
        with pytest.raises((TypeError, ValueError), match=message):
            PopulationRef(**values)

    def test_accepts_large_but_semantically_valid_provenance(self) -> None:
        ref = PopulationRef(
            id="x" * 513,
            index=0,
            size=2**31,
            threshold=0.5,
        )
        assert len(ref.id) == 513
        assert ref.size == 2**31


class TestResultTurnEvaluationsProperty:
    """Turn evaluations remain separate from the terminal evaluation."""

    def test_removed_eval_results_property_is_absent(self) -> None:
        assert not hasattr(_result(SafetyStatus.SAFE), "eval_results")

    def test_empty_turns_gives_empty_turn_evaluations(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )
        assert r.turn_evaluations == []

    def test_turn_evaluations_returned_in_order(self) -> None:
        er1 = _er(EvalOutcome.NOT_DETECTED)
        er2 = _er(EvalOutcome.DETECTED)
        turns = [
            Turn(
                request=Request(prompt="p1"),
                response=Response(text="r1"),
                eval_result=er1,
            ),
            Turn(
                request=Request(prompt="p2"),
                response=Response(text="r2"),
                eval_result=er2,
            ),
        ]
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            turns=turns,
        )
        assert r.turn_evaluations == [er1, er2]

    def test_turns_without_eval_result_filtered(self) -> None:
        er = _er(EvalOutcome.DETECTED)
        turns = [
            Turn(
                request=Request(prompt="p1"),
                response=Response(text="r1"),
            ),
            Turn(
                request=Request(prompt="p2"),
                response=Response(text="r2"),
                eval_result=er,
            ),
        ]
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            turns=turns,
        )
        assert r.turn_evaluations == [er]

    def test_terminal_evaluation_is_not_in_turn_evaluations(self) -> None:
        final = _er(EvalOutcome.DETECTED)
        turn_evaluation = _er(EvalOutcome.NOT_DETECTED)
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.UNSAFE,
            summary="bad",
            terminal_evaluation=final,
            turns=[
                Turn(
                    request=Request(prompt="p"),
                    response=Response(text="r"),
                    eval_result=turn_evaluation,
                ),
            ],
        )
        assert r.turn_evaluations == [turn_evaluation]
        assert r.terminal_evaluation is final


class TestResolveAsAttack:
    def test_empty_returns_error(self) -> None:
        status = resolve_as_attack(eval_results=[])
        assert status is SafetyStatus.ERROR

    def test_detected_returns_unsafe(self) -> None:
        status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.DETECTED)],
        )
        assert status is SafetyStatus.UNSAFE

    def test_not_detected_returns_safe(self) -> None:
        status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.NOT_DETECTED)],
        )
        assert status is SafetyStatus.SAFE

    def test_undetermined_only_returns_undetermined(self) -> None:
        status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.UNDETERMINED)],
        )
        assert status is SafetyStatus.UNDETERMINED

    def test_mixed_detected_and_undetermined_returns_unsafe(self) -> None:
        status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.UNDETERMINED),
                _er(EvalOutcome.DETECTED),
            ],
        )
        assert status is SafetyStatus.UNSAFE

    def test_mixed_not_detected_and_undetermined_returns_undetermined(self) -> None:
        status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.NOT_DETECTED),
                _er(EvalOutcome.UNDETERMINED),
            ],
        )
        assert status is SafetyStatus.UNDETERMINED

    def test_all_not_detected_returns_safe(self) -> None:
        status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.NOT_DETECTED),
                _er(EvalOutcome.NOT_DETECTED),
            ],
        )
        assert status is SafetyStatus.SAFE

    def test_rejects_malformed_runtime_outcome(self) -> None:
        malformed = EvalResult(
            outcome="detected",  # ty: ignore[invalid-argument-type]
        )
        with pytest.raises(ValueError, match="Unknown EvalOutcome"):
            resolve_as_attack(eval_results=[malformed])


class TestResolveAsProbe:
    def test_empty_returns_error(self) -> None:
        status = resolve_as_probe(eval_results=[])
        assert status is SafetyStatus.ERROR

    def test_detected_returns_safe(self) -> None:
        status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.DETECTED)],
        )
        assert status is SafetyStatus.SAFE

    def test_not_detected_returns_unsafe(self) -> None:
        status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.NOT_DETECTED)],
        )
        assert status is SafetyStatus.UNSAFE

    def test_undetermined_only_returns_undetermined(self) -> None:
        status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.UNDETERMINED)],
        )
        assert status is SafetyStatus.UNDETERMINED

    def test_mixed_not_detected_and_undetermined_returns_unsafe(self) -> None:
        status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.UNDETERMINED),
                _er(EvalOutcome.NOT_DETECTED),
            ],
        )
        assert status is SafetyStatus.UNSAFE

    def test_mixed_detected_and_undetermined_returns_undetermined(self) -> None:
        status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.DETECTED),
                _er(EvalOutcome.UNDETERMINED),
            ],
        )
        assert status is SafetyStatus.UNDETERMINED

    def test_all_detected_returns_safe(self) -> None:
        status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.DETECTED),
                _er(EvalOutcome.DETECTED),
            ],
        )
        assert status is SafetyStatus.SAFE

    def test_rejects_malformed_runtime_outcome(self) -> None:
        malformed = EvalResult(
            outcome="detected",  # ty: ignore[invalid-argument-type]
        )
        with pytest.raises(ValueError, match="Unknown EvalOutcome"):
            resolve_as_probe(eval_results=[malformed])


class TestSummarizeUndeterminedOperands:
    def test_empty_when_nothing_was_undetermined(self) -> None:
        clause = _summarize_undetermined_operands(
            eval_results=[_er(EvalOutcome.NOT_DETECTED)],
        )

        assert clause == ""

    def test_names_each_distinct_operand(self) -> None:
        clause = _summarize_undetermined_operands(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["no side effects", "no tool calls"],
                ),
            ],
        )

        assert clause == (
            ", but part of the evaluation was undetermined: "
            "no side effects; no tool calls"
        )

    def test_collapses_a_gap_repeated_across_turns(self) -> None:
        gap = EvalResult(
            outcome=EvalOutcome.NOT_DETECTED,
            undetermined_operands=["no side effects"],
        )

        clause = _summarize_undetermined_operands(eval_results=[gap, gap, gap])

        assert clause == (
            ", but part of the evaluation was undetermined: no side effects"
        )

    def test_counts_the_ones_it_does_not_name(self) -> None:
        clause = _summarize_undetermined_operands(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["first", "second", "third", "fourth"],
                ),
            ],
        )

        assert clause == (
            ", but part of the evaluation was undetermined: first; second (and 2 more)"
        )

    def test_ignores_an_empty_rationale(self) -> None:
        clause = _summarize_undetermined_operands(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=[""],
                ),
            ],
        )

        assert clause == ""


class TestSummaryPathToleratesHostileEvaluatorData:
    """Evaluator-supplied collections must not abort summary construction."""

    @pytest.mark.parametrize(
        "operands",
        [123, _RaisingIter()],
        ids=["non-iterable", "raising-iter"],
    )
    def test_safe_clause_survives_a_bad_operand_collection(
        self,
        operands: object,
    ) -> None:
        clause = _summarize_undetermined_operands(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=operands,  # ty: ignore[invalid-argument-type]
                ),
            ],
        )

        assert clause == ""

    @pytest.mark.parametrize(
        "operands",
        [123, _RaisingIter()],
        ids=["non-iterable", "raising-iter"],
    )
    def test_undetermined_detail_survives_a_bad_operand_collection(
        self,
        operands: object,
    ) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="the real reason",
                    undetermined_operands=operands,  # ty: ignore[invalid-argument-type]
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "the real reason"

    def test_undetermined_detail_survives_a_string_subclass_rationale(self) -> None:
        # A rationale that is a str subclass reaches `.strip()` on the rendered
        # value, so containment has to hand back an exact str.
        class Sneaky(str):  # ruff: ignore[subclass-builtin]
            __slots__ = ()

            def __str__(self) -> str:
                return self

            def strip(self, chars: str | None = None) -> str:
                raise RuntimeError("boom")

        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale=Sneaky("the real reason"),
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "the real reason"


class TestExplainUndetermined:
    """Why an evaluation came back undetermined, in priority order."""

    def test_prefers_the_operand_reasons_over_the_composite_rationale(self) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="Left operand undetermined: no tool calls",
                    undetermined_operands=["no tool calls", "no side effects"],
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "no tool calls; no side effects"

    def test_collapses_a_reason_repeated_across_turns(self) -> None:
        same = "Adapter observability is 'tool_only'"
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=[same],
                )
                for _ in range(3)
            ],
            fallback="nothing to say",
        )

        assert detail == same

    def test_collapses_a_rationale_repeated_across_turns(self) -> None:
        # A leaf evaluator words the same rationale on every turn of a
        # multi-turn run, so the fallback has to collapse them too.
        same = "Adapter observability is 'tool_only'"
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(outcome=EvalOutcome.UNDETERMINED, rationale=same)
                for _ in range(3)
            ],
            fallback="nothing to say",
        )

        assert detail == same

    def test_counts_the_reasons_it_does_not_name(self) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=["a", "b", "c", "d"],
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "a; b (and 2 more)"

    def test_ignores_a_settled_result_while_an_operand_stayed_undetermined(
        self,
    ) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["settled, so not the reason"],
                ),
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    rationale="the real reason",
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "the real reason"

    def test_reads_settled_results_when_nothing_else_gave_a_reason(self) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["the downgrade had a reason"],
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "the downgrade had a reason"

    def test_ignores_settled_results_when_an_operand_gave_no_reason(self) -> None:
        # The verdict is undetermined because of the second result. A gap
        # carried by a result that reached a definitive answer did not cause
        # it, so it must not be offered as the explanation.
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.NOT_DETECTED,
                    undetermined_operands=["turn 1: side effects unobservable"],
                ),
                EvalResult(outcome=EvalOutcome.UNDETERMINED, rationale=""),
            ],
            fallback="nothing to say",
        )

        assert detail == "nothing to say"

    def test_falls_back_when_no_reason_exists(self) -> None:
        detail = _explain_undetermined(
            eval_results=[_er(EvalOutcome.UNDETERMINED)],
            fallback="nothing to say",
        )

        assert detail == "nothing to say"

    def test_falls_back_when_the_only_rationale_is_blank(self) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(outcome=EvalOutcome.UNDETERMINED, rationale="   "),
            ],
            fallback="nothing to say",
        )

        assert detail == "nothing to say"

    def test_ignores_blank_reasons(self) -> None:
        detail = _explain_undetermined(
            eval_results=[
                EvalResult(
                    outcome=EvalOutcome.UNDETERMINED,
                    undetermined_operands=["   ", ""],
                ),
            ],
            fallback="nothing to say",
        )

        assert detail == "nothing to say"


class TestResolveAttackVerdict:
    @pytest.mark.parametrize(
        ("evaluation", "expected"),
        [
            (_er(EvalOutcome.DETECTED), SafetyStatus.UNSAFE),
            (_er(EvalOutcome.NOT_DETECTED), SafetyStatus.SAFE),
            (_er(EvalOutcome.UNDETERMINED), SafetyStatus.UNDETERMINED),
        ],
    )
    def test_maps_single_evaluation(
        self,
        evaluation: EvalResult,
        expected: SafetyStatus,
    ) -> None:
        assert resolve_attack_verdict(evaluation=evaluation) is expected

    def test_rejects_malformed_runtime_outcome(self) -> None:
        evaluation = EvalResult(
            outcome="detected",  # ty: ignore[invalid-argument-type]
        )
        with pytest.raises(ValueError, match="Unknown EvalOutcome"):
            resolve_attack_verdict(evaluation=evaluation)


class TestResolveProbeVerdict:
    @pytest.mark.parametrize(
        ("evaluation", "expected"),
        [
            (_er(EvalOutcome.DETECTED), SafetyStatus.SAFE),
            (_er(EvalOutcome.NOT_DETECTED), SafetyStatus.UNSAFE),
            (_er(EvalOutcome.UNDETERMINED), SafetyStatus.UNDETERMINED),
        ],
    )
    def test_maps_single_evaluation(
        self,
        evaluation: EvalResult,
        expected: SafetyStatus,
    ) -> None:
        assert resolve_probe_verdict(evaluation=evaluation) is expected

    def test_rejects_malformed_runtime_outcome(self) -> None:
        evaluation = EvalResult(
            outcome="detected",  # ty: ignore[invalid-argument-type]
        )
        with pytest.raises(ValueError, match="Unknown EvalOutcome"):
            resolve_probe_verdict(evaluation=evaluation)
