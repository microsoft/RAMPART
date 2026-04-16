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
    resolve_as_attack,
    resolve_as_probe,
)
from rampart.core.types import EvalOutcome, EvalResult, ObservabilityLevel


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
    def test_bool_returns_safe_true(self) -> None:
        r = Result(safe=True, status=SafetyStatus.SAFE, summary="ok")
        assert bool(r) is True

    def test_bool_returns_safe_false(self) -> None:
        r = Result(safe=False, status=SafetyStatus.UNSAFE, summary="bad")
        assert bool(r) is False

    def test_assert_safe_pattern(self) -> None:
        safe_result = Result(safe=True, status=SafetyStatus.SAFE, summary="ok")
        assert safe_result, safe_result.summary

        unsafe_result = Result(
            safe=False,
            status=SafetyStatus.UNSAFE,
            summary="attack detected",
        )
        with pytest.raises(AssertionError):
            assert unsafe_result, unsafe_result.summary

    def test_repr(self) -> None:
        r = Result(safe=True, status=SafetyStatus.SAFE, summary="Agent defended")
        assert "safe=True" in repr(r)
        assert "safe" in repr(r)
        assert "Agent defended" in repr(r)

    def test_defaults(self) -> None:
        r = Result(safe=True, status=SafetyStatus.SAFE, summary="ok")
        assert r.turns == []
        assert r.eval_results == []
        assert r.duration_seconds == 0.0
        assert r.harm_category is None
        assert r.strategy == ""
        assert r.observability_level is ObservabilityLevel.RESPONSE_ONLY
        assert r.injections == []
        assert r.metadata == {}

    def test_harm_category_accepts_enum(self) -> None:
        r = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="ok",
            harm_category=HarmCategory.DATA_EXFILTRATION,
        )
        assert r.harm_category == "data_exfiltration"
        assert r.harm_category == HarmCategory.DATA_EXFILTRATION

    def test_harm_category_accepts_plain_string(self) -> None:
        r = Result(
            safe=True,
            status=SafetyStatus.SAFE,
            summary="ok",
            harm_category="custom_product_risk",
        )
        assert r.harm_category == "custom_product_risk"


class TestResolveAsAttack:
    def test_empty_returns_error(self) -> None:
        safe, status = resolve_as_attack(eval_results=[])
        assert safe is False
        assert status is SafetyStatus.ERROR

    def test_detected_returns_unsafe(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.DETECTED)],
        )
        assert safe is False
        assert status is SafetyStatus.UNSAFE

    def test_not_detected_returns_safe(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.NOT_DETECTED)],
        )
        assert safe is True
        assert status is SafetyStatus.SAFE

    def test_undetermined_only_returns_undetermined(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[_er(EvalOutcome.UNDETERMINED)],
        )
        assert safe is False
        assert status is SafetyStatus.UNDETERMINED

    def test_mixed_detected_and_undetermined_returns_unsafe(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.UNDETERMINED),
                _er(EvalOutcome.DETECTED),
            ],
        )
        assert safe is False
        assert status is SafetyStatus.UNSAFE

    def test_mixed_not_detected_and_undetermined_returns_undetermined(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.NOT_DETECTED),
                _er(EvalOutcome.UNDETERMINED),
            ],
        )
        assert safe is False
        assert status is SafetyStatus.UNDETERMINED

    def test_all_not_detected_returns_safe(self) -> None:
        safe, status = resolve_as_attack(
            eval_results=[
                _er(EvalOutcome.NOT_DETECTED),
                _er(EvalOutcome.NOT_DETECTED),
            ],
        )
        assert safe is True
        assert status is SafetyStatus.SAFE


class TestResolveAsProbe:
    def test_empty_returns_error(self) -> None:
        safe, status = resolve_as_probe(eval_results=[])
        assert safe is False
        assert status is SafetyStatus.ERROR

    def test_detected_returns_safe(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.DETECTED)],
        )
        assert safe is True
        assert status is SafetyStatus.SAFE

    def test_not_detected_returns_unsafe(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.NOT_DETECTED)],
        )
        assert safe is False
        assert status is SafetyStatus.UNSAFE

    def test_undetermined_only_returns_undetermined(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[_er(EvalOutcome.UNDETERMINED)],
        )
        assert safe is False
        assert status is SafetyStatus.UNDETERMINED

    def test_mixed_not_detected_and_undetermined_returns_unsafe(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.UNDETERMINED),
                _er(EvalOutcome.NOT_DETECTED),
            ],
        )
        assert safe is False
        assert status is SafetyStatus.UNSAFE

    def test_mixed_detected_and_undetermined_returns_undetermined(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.DETECTED),
                _er(EvalOutcome.UNDETERMINED),
            ],
        )
        assert safe is False
        assert status is SafetyStatus.UNDETERMINED

    def test_all_detected_returns_safe(self) -> None:
        safe, status = resolve_as_probe(
            eval_results=[
                _er(EvalOutcome.DETECTED),
                _er(EvalOutcome.DETECTED),
            ],
        )
        assert safe is True
        assert status is SafetyStatus.SAFE
