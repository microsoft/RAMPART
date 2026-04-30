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
        driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
        assert isinstance(driver, PromptDriver)

    def test_rejects_both_llm_and_target(self) -> None:
        mock_target = MagicMock()
        with pytest.raises(TypeError, match="Provide either"):
            LLMDriver(
                llm=_TEST_LLM,
                target=mock_target,
                persona=_TEST_PERSONA,
            )

    def test_rejects_neither_llm_nor_target(self) -> None:
        with pytest.raises(TypeError, match="Provide either"):
            LLMDriver(persona=_TEST_PERSONA)


class TestLLMDriverLazyInit:
    def test_construction_does_not_call_create_prompt_target(self) -> None:
        """LLMDriver can be constructed before initialize_pyrit_async."""
        with patch(
            "rampart.drivers.llm.create_prompt_target",
        ) as mock_create:
            LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            mock_create.assert_not_called()

    async def test_first_call_initializes_target(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch(
                "rampart.drivers.llm.create_prompt_target",
                return_value=mock_target,
            ) as mock_create,
            patch(
                "rampart.drivers.llm.PromptNormalizer",
            ),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hello",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            mock_create.assert_not_called()

            await driver.next_prompt_async(history=[])
            mock_create.assert_called_once_with(_TEST_LLM)
            mock_target.set_system_prompt.assert_called_once()


class TestLLMDriverConstruction:
    async def test_system_prompt_includes_persona(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hi",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            await driver.next_prompt_async(history=[])
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "You are a test persona." in sp

    async def test_system_prompt_includes_objective_when_provided(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hi",
            ),
        ):
            driver = LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                objective="Extract secret data",
            )
            await driver.next_prompt_async(history=[])
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Objective" in sp
            assert "Extract secret data" in sp

    async def test_system_prompt_omits_objective_when_none(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hi",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            await driver.next_prompt_async(history=[])
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Objective" not in sp

    async def test_system_prompt_includes_injection_metadata_not_content(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hi",
            ),
        ):
            payload = Payload(
                content="secret doc content",
                id="pay-1",
                metadata={"description": "Q3 financial report"},
            )
            driver = LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                injections=[payload],
            )
            await driver.next_prompt_async(history=[])
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "Injected Context" in sp
            assert "pay-1" in sp
            assert "Q3 financial report" in sp
            assert "secret doc content" not in sp

    def test_two_drivers_have_distinct_conversation_ids(self) -> None:
        d1 = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
        d2 = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
        assert d1._conversation_id != d2._conversation_id


class TestLLMDriverSendFlow:
    async def test_returns_plain_text_as_prompt(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="Tell me about Q3 earnings",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is not None
            assert decision.request.prompt == "Tell me about Q3 earnings"

    async def test_send_uses_normalizer_helper(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hi",
            ) as mock_send,
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            await driver.next_prompt_async(history=[])

            mock_send.assert_awaited_once()
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["conversation_id"] == driver._conversation_id
            assert call_kwargs["user_message"] == "Begin. Send the first user prompt."
            assert "rampart.component" in call_kwargs["labels"]

    async def test_non_empty_history_sends_agent_response(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        # System prompt message + 1 user + 1 assistant = history matches 1 turn
        mock_piece = MagicMock()
        mock_piece.api_role = "user"
        mock_msg = MagicMock()
        mock_msg.get_piece.return_value = mock_piece
        mock_memory.get_conversation.return_value = [
            MagicMock(get_piece=MagicMock(return_value=MagicMock(api_role="system"))),
            mock_msg,
            MagicMock(
                get_piece=MagicMock(return_value=MagicMock(api_role="assistant")),
            ),
        ]

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=mock_target),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="next question",
            ) as mock_send,
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

            user_msg = mock_send.call_args.kwargs["user_message"]
            assert "agent said this" in user_msg
            assert "not_detected" in user_msg
            assert "not found" in user_msg

    async def test_strips_whitespace_from_response(self) -> None:
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="  Tell me about Q3  \n",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is not None
            assert decision.request.prompt == "Tell me about Q3"


class TestLLMDriverErrorHandling:
    async def test_empty_response_raises_driver_error(self) -> None:
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError, match="empty response"):
                await driver.next_prompt_async(history=[])

    async def test_whitespace_only_response_raises_driver_error(self) -> None:
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="   \n  ",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError, match="empty response"):
                await driver.next_prompt_async(history=[])

    async def test_send_exception_wrapped_in_driver_error(self) -> None:
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                side_effect=RuntimeError("connection refused"),
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError, match="send_user_turn_async failed"):
                await driver.next_prompt_async(history=[])

    async def test_driver_error_preserves_cause(self) -> None:
        original = RuntimeError("timeout")
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                side_effect=original,
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            with pytest.raises(DriverError) as exc_info:
                await driver.next_prompt_async(history=[])
            assert exc_info.value.__cause__ is original


class TestLLMDriverDesyncDetection:
    async def test_desync_raises_driver_error(self) -> None:
        """Passing history that doesn't match driver-side memory raises."""
        mock_memory = MagicMock()
        # Driver-side has 0 user turns but we pass 1 agent-side turn
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            turn = _make_turn(turn_number=0)
            with pytest.raises(DriverError, match="desync"):
                await driver.next_prompt_async(history=[turn])


class TestLLMDriverFromTarget:
    def test_from_target_does_not_require_llm_config(self) -> None:
        mock_target = MagicMock()
        driver = LLMDriver.from_target(
            target=mock_target,
            persona=_TEST_PERSONA,
        )
        assert driver._llm is None
        assert driver._target is mock_target

    async def test_from_target_sets_system_prompt_on_first_use(self) -> None:
        mock_target = MagicMock()
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hello",
            ),
        ):
            driver = LLMDriver.from_target(
                target=mock_target,
                persona=_TEST_PERSONA,
                objective="test objective",
            )
            mock_target.set_system_prompt.assert_not_called()

            await driver.next_prompt_async(history=[])
            mock_target.set_system_prompt.assert_called_once()
            sp = mock_target.set_system_prompt.call_args.kwargs["system_prompt"]
            assert "You are a test persona." in sp
            assert "test objective" in sp


class TestLLMDriverAttachments:
    async def test_first_turn_attaches_injections(self) -> None:
        """Injections should be attached to the first request."""
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        payload = Payload(
            content="report content",
            id="pay-1",
            metadata={"description": "Q3 report"},
        )

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="Summarize the document",
            ),
        ):
            driver = LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                injections=[payload],
            )
            decision = await driver.next_prompt_async(history=[])
            assert decision is not None
            assert decision.request.attachments == [payload]

    async def test_subsequent_turns_have_no_attachments(self) -> None:
        """Only the first turn should carry attachments."""
        mock_piece_user = MagicMock()
        mock_piece_user.api_role = "user"
        mock_msg_user = MagicMock()
        mock_msg_user.get_piece.return_value = mock_piece_user

        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = [
            MagicMock(get_piece=MagicMock(return_value=MagicMock(api_role="system"))),
            mock_msg_user,
            MagicMock(
                get_piece=MagicMock(return_value=MagicMock(api_role="assistant")),
            ),
        ]

        payload = Payload(
            content="report content",
            id="pay-1",
            metadata={"description": "Q3 report"},
        )

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="follow-up question",
            ),
        ):
            driver = LLMDriver(
                llm=_TEST_LLM,
                persona=_TEST_PERSONA,
                injections=[payload],
            )
            turn0 = _make_turn(turn_number=0)
            decision = await driver.next_prompt_async(history=[turn0])
            assert decision is not None
            assert decision.request.attachments == []

    async def test_no_injections_means_no_attachments(self) -> None:
        """Without injections, first turn should have empty attachments."""
        mock_memory = MagicMock()
        mock_memory.get_conversation.return_value = []

        with (
            patch("rampart.drivers.llm.create_prompt_target", return_value=MagicMock()),
            patch("rampart.drivers.llm.PromptNormalizer"),
            patch(
                "rampart.drivers.llm.CentralMemory.get_memory_instance",
                return_value=mock_memory,
            ),
            patch(
                "rampart.drivers.llm.send_user_turn_async",
                new_callable=AsyncMock,
                return_value="hello",
            ),
        ):
            driver = LLMDriver(llm=_TEST_LLM, persona=_TEST_PERSONA)
            decision = await driver.next_prompt_async(history=[])
            assert decision is not None
            assert decision.request.attachments == []
