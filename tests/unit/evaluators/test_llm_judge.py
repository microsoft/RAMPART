# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.llm_judge — LLMJudge evaluator.

All tests run without a live LLM by patching the PyRIT bridge entry
points (``create_prompt_target``, ``PromptNormalizer``, and
``send_judge_request_async``) the same way the LLMDriver tests do.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from pyrit.exceptions import (
    EmptyResponseException,
    InvalidJsonException,
    RateLimitException,
)

from rampart.core.errors import EvaluatorError
from rampart.core.llm import LLMConfig
from rampart.core.manifest import AppManifest, ToolDeclaration
from rampart.core.persona import Persona
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)
from rampart.evaluators import NEUTRAL_EVALUATOR, LLMJudge, ToolCalled, TranscriptScope
from rampart.evaluators.llm_judge import _JudgeVerdict

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

_TEST_LLM = LLMConfig(
    model="gpt-4o",
    endpoint="https://api.openai.com/v1",
    api_key="sk-test",
)


def _verdict_json(
    *,
    outcome: str = "detected",
    confidence: float = 0.9,
    rationale: str = "rationale",
    evidence: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "outcome": outcome,
            "confidence": confidence,
            "rationale": rationale,
            "evidence": evidence if evidence is not None else ["e1"],
        },
    )


def _make_ctx(*turns: Turn, manifest: AppManifest | None = None) -> EvalContext:
    if not turns:
        turns = (
            Turn(
                request=Request(prompt="hello"),
                response=Response(text="hi"),
            ),
        )
    return EvalContext(turns=list(turns), manifest=manifest)


class _FakeSender:
    """Test stand-in for ``send_judge_request_async``.

    Consumes ``responses`` in order; once exhausted, the last response
    is repeated. ``BaseException`` instances are raised instead of
    returned to simulate transient or fatal LLM failures. Records each
    call's ``(system_prompt, user_message)`` pair so tests can assert
    on the rendered prompts.
    """

    def __init__(self, responses: list[str | BaseException]) -> None:
        self._responses: list[str | BaseException] = list(responses)
        self._index: int = 0
        self.calls: list[tuple[str, str]] = []

    async def __call__(
        self,
        *,
        normalizer: object,
        target: object,
        system_prompt: str,
        user_message: str,
        response_format: str | None = "json",
        labels: dict[str, str] | None = None,
        attack_identifier: object = None,
    ) -> str:
        self.calls.append((system_prompt, user_message))
        idx = min(self._index, len(self._responses) - 1)
        response = self._responses[idx]
        self._index += 1
        if isinstance(response, BaseException):
            raise response
        return response


def _patched_judge(sender: _FakeSender) -> AbstractContextManager[None]:
    """Patch the PyRIT bridge so ``LLMJudge`` never touches CentralMemory."""
    return patch.multiple(
        "rampart.evaluators.llm_judge",
        create_prompt_target=MagicMock(return_value=MagicMock()),
        PromptNormalizer=MagicMock(return_value=MagicMock()),
        send_judge_request_async=sender,
    )


async def _evaluate(
    *,
    responses: list[str | BaseException] | None = None,
    context: EvalContext | None = None,
    objective: str = "Agent disclosed sensitive information.",
    persona: Persona | None = None,
    scope: TranscriptScope = TranscriptScope.FULL,
) -> tuple[EvalResult, _FakeSender]:
    """Build a judge, run ``evaluate_async``, and return verdict + capture."""
    sender = _FakeSender(
        responses if responses is not None else [_verdict_json()],
    )
    ctx = context if context is not None else _make_ctx()
    with _patched_judge(sender):
        judge = LLMJudge(
            objective=objective,
            llm=_TEST_LLM,
            persona=persona,
            scope=scope,
        )
        result = await judge.evaluate_async(context=ctx)
    return result, sender


class TestConstructorValidation:
    def test_empty_objective_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            LLMJudge(objective="", llm=_TEST_LLM)

    def test_whitespace_objective_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            LLMJudge(objective="   ", llm=_TEST_LLM)

    def test_both_llm_and_target_raises_type_error(self) -> None:
        mock_target = MagicMock()
        with pytest.raises(TypeError, match="not both"):
            LLMJudge(objective="x", llm=_TEST_LLM, target=mock_target)

    def test_neither_llm_nor_target_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="either 'llm' or 'target'"):
            LLMJudge(objective="x")

    def test_persona_defaults_to_neutral_evaluator(self) -> None:
        judge = LLMJudge(objective="x", llm=_TEST_LLM)
        assert judge._persona is NEUTRAL_EVALUATOR


class TestOutcomeRoundTrip:
    async def test_detected_round_trips_async(self) -> None:
        result, _ = await _evaluate(
            responses=[
                _verdict_json(
                    outcome="detected",
                    confidence=0.81,
                    rationale="disclosed PII",
                    evidence=["email leaked"],
                ),
            ],
        )
        assert result.outcome is EvalOutcome.DETECTED
        assert result.confidence == pytest.approx(0.81)  # pyright: ignore[reportUnknownMemberType]
        assert result.rationale == "disclosed PII"
        assert result.evidence == ["email leaked"]

    async def test_not_detected_round_trips_async(self) -> None:
        result, _ = await _evaluate(
            responses=[_verdict_json(outcome="not_detected")],
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_undetermined_round_trips_async(self) -> None:
        result, _ = await _evaluate(
            responses=[_verdict_json(outcome="undetermined")],
        )
        assert result.outcome is EvalOutcome.UNDETERMINED


class TestJsonRobustness:
    async def test_markdown_fenced_json_parses_async(self) -> None:
        raw = f"```json\n{_verdict_json()}\n```"
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.DETECTED

    async def test_json_embedded_in_prose_parses_async(self) -> None:
        raw = f"Here is the verdict: {_verdict_json()} (end)"
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.DETECTED

    async def test_malformed_json_exhausts_retries_to_undetermined_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        result, _ = await _evaluate(responses=["not json at all"])
        assert result.outcome is EvalOutcome.UNDETERMINED
        assert "valid JSON" in result.rationale
        assert result.confidence == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]

    async def test_unknown_outcome_value_degrades_to_undetermined_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        result, _ = await _evaluate(
            responses=[_verdict_json(outcome="maybe_detected")],
        )
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_missing_required_key_degrades_to_undetermined_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        raw = json.dumps({"outcome": "detected", "confidence": 0.5, "rationale": "r"})
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_evidence_must_be_list_of_strings_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        raw = json.dumps(
            {
                "outcome": "detected",
                "confidence": 0.5,
                "rationale": "r",
                "evidence": [1, 2, 3],
            },
        )
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.UNDETERMINED


class TestConfidenceClamping:
    async def test_above_one_clamps_to_one_async(self) -> None:
        result, _ = await _evaluate(responses=[_verdict_json(confidence=1.7)])
        assert result.confidence == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]

    async def test_below_zero_clamps_to_zero_async(self) -> None:
        result, _ = await _evaluate(responses=[_verdict_json(confidence=-0.4)])
        assert result.confidence == pytest.approx(0.0)  # pyright: ignore[reportUnknownMemberType]

    async def test_non_numeric_confidence_degrades_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        raw = json.dumps(
            {
                "outcome": "detected",
                "confidence": "high",
                "rationale": "r",
                "evidence": [],
            },
        )
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_nan_confidence_degrades_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Defense against json.loads accepting NaN — without the finite-check
        # in _validate_confidence, NaN would propagate through min/max and
        # produce a poisoned EvalResult.confidence. The retry path should
        # engage and ultimately degrade to UNDETERMINED.
        monkeypatch.setenv("RETRY_MAX_NUM_ATTEMPTS", "2")
        raw = (
            '{"outcome": "detected", "confidence": NaN, '
            '"rationale": "r", "evidence": []}'
        )
        result, _ = await _evaluate(responses=[raw])
        assert result.outcome is EvalOutcome.UNDETERMINED


def _two_turn_ctx() -> EvalContext:
    return _make_ctx(
        Turn(
            request=Request(prompt="first user prompt"),
            response=Response(text="first agent reply"),
            turn_number=0,
        ),
        Turn(
            request=Request(prompt="second user prompt"),
            response=Response(text="second agent reply"),
            turn_number=1,
        ),
    )


class TestTranscriptScope:
    async def test_full_scope_includes_all_turns_async(self) -> None:
        _, sender = await _evaluate(
            context=_two_turn_ctx(),
            scope=TranscriptScope.FULL,
        )
        _, user_message = sender.calls[0]
        assert "first user prompt" in user_message
        assert "second user prompt" in user_message
        assert "[Turn 0]" in user_message
        assert "[Turn 1]" in user_message

    async def test_current_turn_scope_excludes_earlier_turns_async(self) -> None:
        _, sender = await _evaluate(
            context=_two_turn_ctx(),
            scope=TranscriptScope.CURRENT_TURN,
        )
        _, user_message = sender.calls[0]
        assert "first user prompt" not in user_message
        assert "second user prompt" in user_message

    async def test_empty_transcript_uses_placeholder_async(self) -> None:
        _, sender = await _evaluate(context=EvalContext(turns=[]))
        _, user_message = sender.calls[0]
        assert user_message == "(empty transcript)"


class TestTranscriptRendering:
    async def test_includes_field_labels_async(self) -> None:
        ctx = _make_ctx(
            Turn(
                request=Request(prompt="please help"),
                response=Response(
                    text="here you go",
                    tool_calls=[
                        ToolCall(
                            name="lookup",
                            arguments={"id": "42"},
                            result="answer-42",
                        ),
                    ],
                    side_effects=[
                        SideEffect(
                            kind="http_request",
                            details={"url": "host_marker_42"},
                        ),
                    ],
                ),
            ),
        )
        _, sender = await _evaluate(context=ctx)
        _, user_message = sender.calls[0]
        assert "User: please help" in user_message
        assert "Agent: here you go" in user_message
        assert "Tool call: lookup(" in user_message
        assert "answer-42" in user_message
        assert "Side effect: http_request" in user_message
        assert any(
            line
            in {
                "Side effect: http_request - url='host_marker_42'",
                "Side effect: http_request — url='host_marker_42'",
            }
            for line in user_message.splitlines()
        )

    async def test_attachment_content_excluded_metadata_included_async(self) -> None:
        payload_body = "VERY_SECRET_PAYLOAD_CONTENT_42"
        ctx = _make_ctx(
            Turn(
                request=Request(
                    prompt="see attachment",
                    attachments=[
                        Payload(
                            content=payload_body,
                            id="att-123",
                            format=PayloadFormat.TEXT,
                        ),
                    ],
                ),
                response=Response(text="ok"),
            ),
        )
        _, sender = await _evaluate(context=ctx)
        _, user_message = sender.calls[0]
        assert payload_body not in user_message
        assert "att-123" in user_message
        assert "format=text" in user_message


class TestSystemPromptAssembly:
    async def test_hardening_suffix_appended_async(self) -> None:
        _, sender = await _evaluate()
        system_prompt, _ = sender.calls[0]
        assert system_prompt.endswith(LLMJudge._HARDENING_SUFFIX)
        assert "SECURITY BOUNDARY" in system_prompt

    async def test_persona_prompt_rendered_async(self) -> None:
        custom = Persona(
            name="security_reviewer",
            system_prompt="You are a senior security engineer.",
        )
        _, sender = await _evaluate(persona=custom)
        system_prompt, _ = sender.calls[0]
        assert "senior security engineer" in system_prompt

    async def test_objective_rendered_async(self) -> None:
        _, sender = await _evaluate(objective="The agent leaked an API key.")
        system_prompt, _ = sender.calls[0]
        assert "The agent leaked an API key." in system_prompt

    async def test_default_persona_neutral_evaluator_in_prompt_async(self) -> None:
        _, sender = await _evaluate()
        system_prompt, _ = sender.calls[0]
        assert (
            NEUTRAL_EVALUATOR.system_prompt.split(".", maxsplit=1)[0] in system_prompt
        )

    async def test_manifest_summary_rendered_when_present_async(self) -> None:
        manifest = AppManifest(
            name="TestAgent",
            description="A test agent.",
            tools=[ToolDeclaration(name="send_email", description="send mail")],
        )
        _, sender = await _evaluate(context=_make_ctx(manifest=manifest))
        system_prompt, _ = sender.calls[0]
        assert "TestAgent" in system_prompt
        assert "send_email" in system_prompt

    async def test_schema_declaration_in_system_prompt_async(self) -> None:
        _, sender = await _evaluate()
        system_prompt, _ = sender.calls[0]
        assert "outcome" in system_prompt
        assert "confidence" in system_prompt
        assert "rationale" in system_prompt
        assert "evidence" in system_prompt


class TestFailureTiers:
    async def test_transient_empty_response_degrades_to_undetermined_async(
        self,
    ) -> None:
        result, _ = await _evaluate(
            responses=[EmptyResponseException(message="empty")],
        )
        assert result.outcome is EvalOutcome.UNDETERMINED
        assert "EmptyResponseException" in result.rationale

    async def test_transient_rate_limit_degrades_to_undetermined_async(self) -> None:
        result, _ = await _evaluate(
            responses=[RateLimitException(message="rate")],
        )
        assert result.outcome is EvalOutcome.UNDETERMINED

    async def test_config_error_raises_evaluator_error_async(self) -> None:
        sender = _FakeSender([ConnectionRefusedError("endpoint unreachable")])
        with _patched_judge(sender):
            judge = LLMJudge(objective="x", llm=_TEST_LLM)
            with pytest.raises(EvaluatorError, match="judge LLM"):
                await judge.evaluate_async(context=_make_ctx())


class TestComposition:
    async def test_or_short_circuits_when_left_detects_async(self) -> None:
        sender = _FakeSender([_verdict_json(outcome="not_detected")])
        ctx = _make_ctx(
            Turn(
                request=Request(prompt="x"),
                response=Response(
                    text="ok",
                    tool_calls=[ToolCall(name="reset_user_password")],
                ),
            ),
        )
        with _patched_judge(sender):
            judge = LLMJudge(objective="x", llm=_TEST_LLM)
            combined = ToolCalled("reset_user_password") | judge
            result = await combined.evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED
        assert sender.calls == []

    async def test_or_falls_through_to_judge_when_left_misses_async(self) -> None:
        sender = _FakeSender([_verdict_json(outcome="detected")])
        ctx = _make_ctx(
            Turn(
                request=Request(prompt="x"),
                response=Response(text="ok"),
            ),
        )
        with _patched_judge(sender):
            judge = LLMJudge(objective="x", llm=_TEST_LLM)
            combined = ToolCalled("reset_user_password") | judge
            result = await combined.evaluate_async(context=ctx)
        assert result.outcome is EvalOutcome.DETECTED
        assert len(sender.calls) == 1


class TestJudgeVerdictUnit:
    def test_from_json_clamps_high_confidence(self) -> None:
        verdict = _JudgeVerdict.from_json(_verdict_json(confidence=2.5))
        assert verdict.confidence == pytest.approx(1.0)  # pyright: ignore[reportUnknownMemberType]

    def test_from_json_rejects_bool_confidence(self) -> None:
        raw = json.dumps(
            {
                "outcome": "detected",
                "confidence": True,
                "rationale": "r",
                "evidence": [],
            },
        )
        with pytest.raises(InvalidJsonException):
            _JudgeVerdict.from_json(raw)

    @pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
    def test_from_json_rejects_non_finite_confidence(self, literal: str) -> None:
        # json.loads accepts NaN/Infinity/-Infinity by default. Without an
        # explicit finite-check, NaN would propagate through min/max and
        # silently poison EvalResult.confidence.
        raw = (
            '{"outcome": "detected", "confidence": '
            + literal
            + ', "rationale": "r", "evidence": []}'
        )
        with pytest.raises(InvalidJsonException):
            _JudgeVerdict.from_json(raw)

    def test_to_eval_result_preserves_fields(self) -> None:
        verdict = _JudgeVerdict(
            outcome="not_detected",
            confidence=0.42,
            rationale="r",
            evidence=["e1", "e2"],
        )
        result = verdict.to_eval_result()
        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.confidence == pytest.approx(0.42)  # pyright: ignore[reportUnknownMemberType]
        assert result.evidence == ["e1", "e2"]


class TestFromTarget:
    async def test_from_target_evaluates_successfully_async(self) -> None:
        sender = _FakeSender([_verdict_json(outcome="detected", confidence=0.85)])
        with _patched_judge(sender):
            judge = LLMJudge.from_target(
                target=MagicMock(),
                objective="Agent leaked PII.",
            )
            result = await judge.evaluate_async(context=_make_ctx())
        assert result.outcome is EvalOutcome.DETECTED
        assert result.confidence == pytest.approx(0.85)  # pyright: ignore[reportUnknownMemberType]

    async def test_from_target_passes_persona_and_scope_async(self) -> None:
        custom_persona = Persona(
            name="strict_reviewer",
            system_prompt="You are a strict reviewer.",
        )
        sender = _FakeSender([_verdict_json()])
        ctx = _two_turn_ctx()
        with _patched_judge(sender):
            judge = LLMJudge.from_target(
                target=MagicMock(),
                objective="Agent disclosed data.",
                persona=custom_persona,
                scope=TranscriptScope.CURRENT_TURN,
            )
            await judge.evaluate_async(context=ctx)
        system_prompt, user_message = sender.calls[0]
        assert "strict reviewer" in system_prompt
        assert "first user prompt" not in user_message
        assert "second user prompt" in user_message

    async def test_from_target_defaults_persona_to_neutral_async(self) -> None:
        sender = _FakeSender([_verdict_json()])
        with _patched_judge(sender):
            judge = LLMJudge.from_target(target=MagicMock(), objective="x")
            assert judge._persona is NEUTRAL_EVALUATOR
