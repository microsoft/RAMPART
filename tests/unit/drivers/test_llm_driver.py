# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for LLMDriver — LLM-backed prompt driver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rampart.core.errors import DriverError
from rampart.core.llm import LLMConfig
from rampart.core.persona import Persona
from rampart.core.prompt_driver import PromptDriver
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    Payload,
    Request,
    Response,
    Turn,
)
from rampart.drivers.llm import LLMDriver

_TEST_LLM = LLMConfig(
    model="gpt-4o",
    endpoint="https://api.openai.com/v1",
    api_key="sk-test",
)

_TEST_PERSONA = Persona(
    name="test_persona",
    description="Test persona",
    system_prompt="You are a test persona.",
)


def _mock_response(text: str) -> MagicMock:
    """Build a mock matching PyRIT's Message.get_value() shape."""
    msg = MagicMock()
    msg.get_value.return_value = text
    return msg


def _make_turn(
    *,
    prompt: str = "p",
    response_text: str = "r",
    outcome: EvalOutcome = EvalOutcome.NOT_DETECTED,
    rationale: str = "",
    turn_number: int = 0,
) -> Turn:
    """Build a Turn with populated eval_result."""
    return Turn(
        request=Request(prompt=prompt),
        response=Response(text=response_text),
        eval_result=EvalResult(outcome=outcome, rationale=rationale),
        turn_number=turn_number,
    )


class TestLLMDriverProtocolCompliance:
    def test_satisfies_prompt_driver(self) -> None:
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=MagicMock(),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            assert isinstance(driver, PromptDriver)


class TestLLMDriverConstruction:
    def test_calls_create_prompt_target_once(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ) as mock_create:
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            mock_create.assert_called_once_with(_TEST_LLM)

    def test_calls_set_system_prompt_once(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            mock_target.set_system_prompt.assert_called_once()

    def test_system_prompt_includes_persona(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            args = mock_target.set_system_prompt.call_args
            assert "You are a test persona." in args.kwargs["system_prompt"]

    def test_system_prompt_includes_objective_when_provided(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                objective="Extract secret data",
            )
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Objective" in sp
            assert "Extract secret data" in sp

    def test_system_prompt_omits_objective_when_none(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Objective" not in sp

    def test_system_prompt_includes_injections(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            payload = Payload(
                content="secret doc content",
                id="pay-1",
                metadata={"description": "Q3 financial report"},
            )
            LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                injections=[payload],
            )
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Injected Context" in sp
            assert "pay-1" in sp
            assert "Q3 financial report" in sp
            # Raw payload content must NOT appear in the system prompt
            assert "secret doc content" not in sp

    def test_system_prompt_omits_injections_when_empty(self) -> None:
        mock_target = MagicMock()
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Injected Context" not in sp

    def test_different_personas_produce_different_system_prompts(self) -> None:
        prompts = []
        for name in ("persona_a", "persona_b"):
            mock_target = MagicMock()
            with patch(
                "rampart.drivers.llm.create_prompt_target",
                return_value=mock_target,
            ):
                LLMDriver(
                    llm=_TEST_LLM,
                    persona=Persona(name=name, system_prompt=f"I am {name}"),
                )
                prompts.append(
                    mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
                )
        assert prompts[0] != prompts[1]

    def test_same_persona_different_objectives_produce_different_prompts(self) -> None:
        prompts = []
        for obj in ("objective_a", "objective_b"):
            mock_target = MagicMock()
            with patch(
                "rampart.drivers.llm.create_prompt_target",
                return_value=mock_target,
            ):
                LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA, objective=obj)
                prompts.append(
                    mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
                )
        assert prompts[0] != prompts[1]

    def test_two_drivers_have_distinct_conversation_ids(self) -> None:
        drivers = []
        for _ in range(2):
            mock_target = MagicMock()
            with patch(
                "rampart.drivers.llm.create_prompt_target",
                return_value=mock_target,
            ):
                drivers.append(LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA))
        assert drivers[0]._conversation_id != drivers[1]._conversation_id


class TestLLMDriverSendFlow:
    @pytest.mark.asyncio
    async def test_returns_plain_text_as_prompt(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("Tell me about Q3 earnings")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])

            mock_target.send_prompt_async.assert_awaited_once()
            assert decision is not None
            assert decision.request.prompt == "Tell me about Q3 earnings"

    @pytest.mark.asyncio
    async def test_conversation_id_on_sent_message(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("hi")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            await driver.next_prompt_async(history=[])

            sent_message = mock_target.send_prompt_async.call_args.kwargs["message"]
            piece = sent_message.message_pieces[0]
            assert piece.conversation_id == driver._conversation_id

    @pytest.mark.asyncio
    async def test_empty_history_sends_seed_message(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("hello")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            await driver.next_prompt_async(history=[])

            sent_message = mock_target.send_prompt_async.call_args.kwargs["message"]
            user_text = sent_message.message_pieces[0].original_value
            assert "Begin" in user_text

    @pytest.mark.asyncio
    async def test_non_empty_history_sends_agent_response(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("next question")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            turn0 = _make_turn(
                prompt="first",
                response_text="agent said this",
                outcome=EvalOutcome.NOT_DETECTED,
                rationale="not found",
                turn_number=0,
            )
            await driver.next_prompt_async(history=[turn0])

            sent_message = mock_target.send_prompt_async.call_args.kwargs["message"]
            user_text = sent_message.message_pieces[0].original_value
            assert "agent said this" in user_text
            assert "not_detected" in user_text
            assert "not found" in user_text

    @pytest.mark.asyncio
    async def test_only_latest_turn_sent(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("next")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            turn0 = _make_turn(response_text="resp0", turn_number=0)
            turn1 = _make_turn(response_text="resp1", turn_number=1)
            await driver.next_prompt_async(history=[turn0, turn1])

            sent_message = mock_target.send_prompt_async.call_args.kwargs["message"]
            user_text = sent_message.message_pieces[0].original_value
            assert "resp1" in user_text
            assert "resp0" not in user_text

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is None

    @pytest.mark.asyncio
    async def test_whitespace_only_response_returns_none(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("   \n  ")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is None

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_response(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            return_value=[_mock_response("  Tell me about Q3  \n")],
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is not None
            assert decision.request.prompt == "Tell me about Q3"


class TestLLMDriverErrorHandling:
    @pytest.mark.asyncio
    async def test_send_exception_wrapped_in_driver_error(self) -> None:
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(
            side_effect=RuntimeError("connection refused"),
        )
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError, match="send_prompt_async failed"):
                await driver.next_prompt_async(history=[])

    @pytest.mark.asyncio
    async def test_driver_error_preserves_cause(self) -> None:
        original = RuntimeError("timeout")
        mock_target = MagicMock()
        mock_target.send_prompt_async = AsyncMock(side_effect=original)
        with patch(
            "rampart.drivers.llm.create_prompt_target",
            return_value=mock_target,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError) as exc_info:
                await driver.next_prompt_async(history=[])
            assert exc_info.value.__cause__ is original
