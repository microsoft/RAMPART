# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.result.

Result, SafetyStatus, HarmCategory, resolve functions.
"""

import pytest

from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
    Result,
    SafetyStatus,
    _explain_undetermined,
    _summarize_undetermined_operands,
    resolve_as_attack,
    resolve_as_probe,
)
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Request,
    Response,
    Turn,
)


class _RaisingIter:
    """Stands in for an evaluator whose operand collection cannot be iterated."""

    def __iter__(self) -> object:
        raise RuntimeError("boom")


def _er(outcome: EvalOutcome) -> EvalResult:
    """Shorthand to build an EvalResult with a given outcome."""
    return EvalResult(outcome=outcome)


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
        assert r.eval_results == []
        assert r.duration_seconds == pytest.approx(0.0)
        assert r.harm_category is None
        assert r.strategy == ""
        assert r.observability_level is ObservabilityLevel.RESPONSE_ONLY
        assert r.injections == []
        assert r.metadata == {}

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


class TestResultEvalResultsProperty:
    """eval_results is a property derived from turns."""

    def test_empty_turns_gives_empty_eval_results(self) -> None:
        r = Result(
            observability_level=ObservabilityLevel.RESPONSE_ONLY,
            status=SafetyStatus.SAFE,
            summary="ok",
        )
        assert r.eval_results == []

    def test_turns_with_eval_results_returned_in_order(self) -> None:
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
        assert r.eval_results == [er1, er2]

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
        assert r.eval_results == [er]


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
