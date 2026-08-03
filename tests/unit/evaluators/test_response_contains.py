# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.evaluators.response_contains — ResponseContains evaluator."""

import re
import warnings

import pytest

from rampart.core.types import EvalContext, EvalOutcome, Request, Response, Turn
from rampart.evaluators import ResponseContains, ResponseScope


def _ctx(text: str) -> EvalContext:
    """Build a single-turn EvalContext with the given response text."""
    return EvalContext(
        turns=[Turn(request=Request(prompt="test"), response=Response(text=text))],
    )


def _multi_ctx(*texts: str) -> EvalContext:
    """Build a multi-turn EvalContext, one response per text."""
    return EvalContext(
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
    async def test_case_insensitive_by_default(self) -> None:
        result = await ResponseContains("HELLO").evaluate_async(
            context=_ctx("hello world"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_case_sensitive_opt_in(self) -> None:
        result = await ResponseContains(
            "HELLO",
            case_sensitive=True,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_case_sensitive_match(self) -> None:
        result = await ResponseContains(
            "hello",
            case_sensitive=True,
        ).evaluate_async(context=_ctx("hello world"))
        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_detected(self) -> None:
        result = await ResponseContains("evil").evaluate_async(context=_ctx("all good"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsRegex:
    async def test_regex_match(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(pattern).evaluate_async(
            context=_ctx("sent to evil@evil.com"),
        )
        assert result.outcome is EvalOutcome.DETECTED

    async def test_regex_no_match(self) -> None:
        pattern = re.compile(r"evil@\w+\.com")
        result = await ResponseContains(pattern).evaluate_async(
            context=_ctx("all good"),
        )
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsCallable:
    async def test_callable_match(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
        ).evaluate_async(context=_ctx("the secret is here"))
        assert result.outcome is EvalOutcome.DETECTED

    async def test_callable_no_match(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
        ).evaluate_async(context=_ctx("nothing to see"))
        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseContainsComposition:
    async def test_composable_with_not(self) -> None:
        composed = ~ResponseContains("I cannot help")
        result = await composed.evaluate_async(context=_ctx("Sure, here you go"))
        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeAnyTurn:
    async def test_earlier_match_then_benign_final_response(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("here is id_rsa", "Anything else?"))

        assert result.outcome is EvalOutcome.DETECTED
        assert result.evidence == ["Pattern found on turn(s): 0"]
        assert result.rationale == "At least one response contains the target pattern"

    async def test_no_turn_matches(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("all good", "still fine"))

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_regex_target(self) -> None:
        result = await ResponseContains(
            re.compile(r"evil@\w+\.com"),
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("sent to evil@evil.com", "done"))

        assert result.outcome is EvalOutcome.DETECTED

    async def test_case_sensitive_target(self) -> None:
        result = await ResponseContains(
            "SECRET",
            case_sensitive=True,
            scope=ResponseScope.ANY_TURN,
        ).evaluate_async(context=_multi_ctx("secret", "still secret"))

        assert result.outcome is EvalOutcome.NOT_DETECTED


class TestResponseScopeAllTurns:
    async def test_every_turn_matches(self) -> None:
        result = await ResponseContains(
            "Paris",
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("Paris is the capital", "Still Paris"))

        assert result.outcome is EvalOutcome.DETECTED

    async def test_one_turn_missing(self) -> None:
        result = await ResponseContains(
            "Paris",
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("Paris is the capital", "I don't know"))

        assert result.outcome is EvalOutcome.NOT_DETECTED
        assert result.evidence == ["Pattern missing on turn(s): 1"]
        assert result.rationale == "Not every response contains the target pattern"

    async def test_callable_target(self) -> None:
        result = await ResponseContains(
            lambda text: "secret" in text,
            scope=ResponseScope.ALL_TURNS,
        ).evaluate_async(context=_multi_ctx("the secret is here", "secret again"))

        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeCurrentTurn:
    async def test_ignores_earlier_turns(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_multi_ctx("here is id_rsa", "Anything else?"))

        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_matches_final_turn(self) -> None:
        result = await ResponseContains(
            "id_rsa",
            scope=ResponseScope.CURRENT_TURN,
        ).evaluate_async(context=_multi_ctx("nothing yet", "here is id_rsa"))

        assert result.outcome is EvalOutcome.DETECTED


class TestResponseScopeMigrationWarning:
    async def test_unspecified_scope_warns_on_multi_turn(self) -> None:
        with pytest.warns(FutureWarning, match="ResponseScope") as warning_record:
            result = await ResponseContains("id_rsa").evaluate_async(
                context=_multi_ctx("here is id_rsa", "Anything else?"),
            )

        assert len(warning_record) == 1
        assert result.outcome is EvalOutcome.NOT_DETECTED

    async def test_unspecified_scope_single_turn_does_not_warn(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            result = await ResponseContains("hello").evaluate_async(
                context=_ctx("hello world"),
            )

        assert result.outcome is EvalOutcome.DETECTED

    @pytest.mark.parametrize("scope", list(ResponseScope))
    async def test_explicit_scope_does_not_warn(self, scope: ResponseScope) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            await ResponseContains("id_rsa", scope=scope).evaluate_async(
                context=_multi_ctx("here is id_rsa", "Anything else?"),
            )


class TestResponseScopeNegation:
    async def test_not_all_turns_detects_single_failure_to_refuse(self) -> None:
        composed = ~ResponseContains(
            "I cannot help",
            scope=ResponseScope.ALL_TURNS,
        )
        result = await composed.evaluate_async(
            context=_multi_ctx("I cannot help", "Sure, here you go"),
        )

        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_all_turns_stays_not_detected_when_every_turn_refuses(
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

    async def test_not_any_turn_detects_clean_transcript(self) -> None:
        composed = ~ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN)
        result = await composed.evaluate_async(
            context=_multi_ctx("all good", "fine"),
        )

        assert result.outcome is EvalOutcome.DETECTED

    async def test_not_any_turn_stays_not_detected_when_one_turn_matches(
        self,
    ) -> None:
        composed = ~ResponseContains("id_rsa", scope=ResponseScope.ANY_TURN)
        result = await composed.evaluate_async(
            context=_multi_ctx("all good", "found id_rsa"),
        )

        assert result.outcome is EvalOutcome.NOT_DETECTED


@pytest.mark.parametrize("scope", [None, *ResponseScope])
async def test_empty_context_raises(scope: ResponseScope | None) -> None:
    """Every response scope rejects a trace that never exercised the agent."""
    evaluator = ResponseContains("anything", scope=scope)

    with pytest.raises(ValueError, match="No turns in context"):
        await evaluator.evaluate_async(context=EvalContext(turns=[]))
