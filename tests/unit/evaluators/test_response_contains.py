# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.response_contains — ResponseContains evaluator."""

import re
from dataclasses import replace

import pytest

from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    ObservabilityLevel,
    Request,
    Response,
    Turn,
)
from rampart.evaluators import (
    ResponseContains,
    ResponseScope,
    TranscriptScope,
)


def _ctx(text: str) -> EvalContext:
    """Build a single-turn EvalContext with the given response text."""
    return EvalContext(
        observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        turns=[Turn(request=Request(prompt="test"), response=Response(text=text))],
    )


def _multi_ctx(*texts: str) -> EvalContext:
    """Build a multi-turn EvalContext, one response per text."""
    return EvalContext(
        observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
        turns=[
            Turn(
                request=Request(prompt="test"),
                response=Response(text=text),
                turn_number=index,
            )
            for index, text in enumerate(texts)
        ],
    )


class TestResponseContainsSubstring:
    async def test_case_insensitive_by_default_async(self) -> None:
        result = await ResponseContains(
            "HELLO", scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(
            context=_ctx("hello world"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_case_sensitive_opt_in_async(self) -> None:
        result = await ResponseContains(
            "HELLO",
            case_sensitive=True,
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_case_sensitive_match_async(self) -> None:
        result = await ResponseContains(
            "hello",
            case_sensitive=True,
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected_async(self) -> None:
        result = await ResponseContains(
            "evil", scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(context=_ctx("all good"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsRegex:
    async def test_regex_match_async(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(
            pattern, scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(
            context=_ctx("sent to evil@evil.com"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_regex_no_match_async(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(
            pattern, scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(
            context=_ctx("all good"),
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsCallable:
    async def test_callable_match_async(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_ctx("the secret is here"))
        assert result.outcome is EvalOutcome.DETECTED

    async def test_callable_no_match_async(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_ctx("nothing to see"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsComposition:
    async def test_composable_with_not_async(self) -> None:
        composed = ~ResponseContains("I cannot help", scope=ResponseScope.CURRENT_TURN)
        result = await composed.evaluate_async(context=_ctx("Sure, here you go"))
        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeAnyTurn:
    async def test_earlier_match_then_benign_final_response_async(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("here is id_rsa", "Anything else?"))

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["Pattern found on turn(s): 0"]
        assert result.rationale == "At least one response contains the target pattern"

    async def test_no_turn_matches_async(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("all good", "still fine"))

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_regex_target_async(self) -> None:
        result = await ResponseContains(
            re.compile(r"evil@\w+\.com"),
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("sent to evil@evil.com", "done"))

        assert result.outcome is EvalOutcome.DETECTED

    async def test_reports_all_matching_turn_numbers_async(self) -> None:
        result = await ResponseContains(
            "id_rsa", scope=ResponseScope.ANY_TURN
        ).evaluate_async(
            context=_multi_ctx("here is id_rsa", "nothing", "id_rsa again"),
        )

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["Pattern found on turn(s): 0, 2"]

    async def test_case_sensitive_target_async(self) -> None:
        result = await ResponseContains(
            "SECRET",
            case_sensitive=True,
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("secret", "still secret"))

        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseScopeAllTurns:
    async def test_every_turn_matches_async(self) -> None:
        result = await ResponseContains(
            "Paris",
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("Paris is the capital", "Still Paris"))

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["Pattern found on turn(s): 0, 1"]

    async def test_one_turn_missing_async(self) -> None:
        result = await ResponseContains(
            "Paris",
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("Paris is the capital", "I don't know"))

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.evidence == ["Pattern missing on turn(s): 1"]
        assert result.rationale == "Not every response contains the target pattern"

    async def test_callable_target_async(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("the secret is here", "secret again"))

        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeCurrentTurn:
    async def test_ignores_earlier_turns_async(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_multi_ctx("here is id_rsa", "Anything else?"))

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.evidence == []

    async def test_matches_final_turn_async(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_multi_ctx("nothing yet", "here is id_rsa"))

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["Pattern found on turn(s): 1"]

    async def test_uses_recorded_turn_number_async(self) -> None:
        context = _multi_ctx("nothing yet", "here is id_rsa")
        context.turns[-1] = replace(context.turns[-1], turn_number=7)
        result = await ResponseContains(
            "id_rsa", scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(context=context)

        assert result.evidence == ["Pattern found on turn(s): 7"]

    async def test_predicate_only_receives_current_response_async(self) -> None:
        responses = []

        def matches(text: str) -> bool:
            responses.append(text)
            return "id_rsa" in text

        result = await ResponseContains(
            matches, scope=ResponseScope.CURRENT_TURN
        ).evaluate_async(context=_multi_ctx("earlier", "here is id_rsa"))

        assert responses == ["here is id_rsa"]
        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeContract:
    def test_scope_is_required(self) -> None:
        with pytest.raises(TypeError, match="required keyword-only argument: 'scope'"):
            ResponseContains("id_rsa")  # ty: ignore[missing-argument]

    def test_scope_is_keyword_only(self) -> None:
        with pytest.raises(TypeError, match="positional arguments"):
            ResponseContains("id_rsa", ResponseScope.ANY_TURN)  # ty: ignore[too-many-positional-arguments, missing-argument]

    @pytest.mark.parametrize(
        "scope",
        [
            None,
            "current_turn",
            "any_turn",
            "all_turns",
            "invalid",
            TranscriptScope.CURRENT_TURN,
            False,
            1,
            object(),
        ],
    )
    def test_rejects_invalid_scope(self, scope: object) -> None:
        with pytest.raises(TypeError, match="scope must be a ResponseScope"):
            ResponseContains("id_rsa", scope=scope)  # ty: ignore[invalid-argument-type]

    @pytest.mark.parametrize("scope", list(ResponseScope))
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("hello world", EvalOutcome.DETECTED), ("nothing", EvalOutcome.NOT_DETECTED)],
    )
    async def test_explicit_scope_on_single_turn_async(
        self, *, scope: ResponseScope, text: str, expected: EvalOutcome
    ) -> None:
        result = await ResponseContains("hello", scope=scope).evaluate_async(
            context=_ctx(text),
        )

        assert result.outcome is expected
        if expected is EvalOutcome.DETECTED:
            assert result.evidence == ["Pattern found on turn(s): 0"]


class TestResponseScopeNegation:
    async def test_not_all_turns_detects_single_failure_to_refuse_async(self) -> None:
        composed = ~ResponseContains(
            "I cannot help",
            scope=ResponseScope.ALL_TURNS,
        )
        result = await composed.evaluate_async(
            context=_multi_ctx("I cannot help", "Sure, here you go"),
        )

        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_all_turns_stays_not_detected_when_every_turn_refuses_async(
        self,
    ) -> None:
        composed = ~ResponseContains(
            "I cannot help",
            scope=ResponseScope.ALL_TURNS,
        )
        result = await composed.evaluate_async(
            context=_multi_ctx("I cannot help", "I cannot help with that"),
        )

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_not_any_turn_detects_clean_transcript_async(self) -> None:
        composed = ~ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN)
        result = await composed.evaluate_async(
            context=_multi_ctx("all good", "fine"),
        )

        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_any_turn_stays_not_detected_when_one_turn_matches_async(
        self,
    ) -> None:
        composed = ~ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN)
        result = await composed.evaluate_async(
            context=_multi_ctx("all good", "found id_rsa"),
        )

        assert result.outcome is EvalOutcome.NOT_DETECTED


@pytest.mark.parametrize("scope", list(ResponseScope))
async def test_empty_context_raises_async(scope: ResponseScope) -> None:
    """Every response scope rejects a trace that never exercised the agent."""
    evaluator = ResponseContains("anything", scope=scope)

    with pytest.raises(ValueError, match="No turns in context"):
        await evaluator.evaluate_async(
            context=EvalContext(
                observability_level=ObservabilityLevel.TOOL_AND_SIDE_EFFECTS,
                turns=[],
            ),
        )
