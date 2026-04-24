# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LLMDriver — LLM-backed prompt driver.

Wraps a PyRIT PromptChatTarget to generate prompts on each turn.
The conversation (system prompt + prior exchanges with the driving
LLM) is maintained by PyRIT's CentralMemory, keyed by a
conversation_id this driver owns.

One driver instance = one conversation. Construct a new driver per
test.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import yaml
from jinja2 import Template
from pyrit.models import MessagePiece

from rampart._pyrit.llm_bridge import create_prompt_target
from rampart.core.errors import DriverError
from rampart.core.llm import LLMConfig
from rampart.core.persona import Persona
from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Payload, Request, Turn

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt_template(name: str) -> Template:
    """Load a YAML prompt template from the prompts directory as a Jinja2 Template."""
    path = _PROMPTS_DIR / name
    with path.open() as f:
        data = yaml.safe_load(f)
    return Template(data["value"])


_SYSTEM_PROMPT_TEMPLATE = _load_prompt_template("llm_driver_system_prompt.yaml")


class LLMDriver:
    """LLM-backed prompt driver.

    Wraps a PyRIT PromptChatTarget to generate the next user prompt on
    each turn. The LLM responds with plain text — its response *is*
    the next prompt to send to the target agent. Conversation history
    is maintained by PyRIT's CentralMemory, keyed by a conversation_id
    this driver owns.

    Termination is handled externally: the evaluator's early-stop
    (on detection) or the execution loop's max_turns budget. The
    driver itself never self-terminates.

    One driver instance = one conversation. Construct a new driver per
    test.

    Args:
        llm: LLM configuration for the driving model.
        persona: System-prompt identity for the LLM. Personas are
            reusable across many tests.
        objective: Per-test goal as a natural-language string. Optional;
            XPIA benign-trigger flows often leave this None.
        injections: Payloads placed in the agent's data sources.
            Metadata (id, format, description) is embedded in the
            system prompt so the LLM can reference them naturally.
            None when no injections.
    """

    def __init__(
        self,
        *,
        llm: LLMConfig,
        persona: Persona,
        objective: str | None = None,
        injections: list[Payload] | None = None,
    ) -> None:
        self._persona = persona
        self._objective = objective
        self._injections = injections or []

        self._target = create_prompt_target(llm)
        self._conversation_id = str(uuid.uuid4())
        self._target.set_system_prompt(
            system_prompt=self._build_system_prompt(),
            conversation_id=self._conversation_id,
        )

    async def next_prompt_async(
        self,
        *,
        history: list[Turn],
    ) -> PromptDecision | None:
        """Generate the next prompt decision based on conversation history.

        Sends the latest turn data to the driving LLM and returns
        its plain-text response as the next prompt. Returns None only
        if the LLM produces an empty response.

        Raises:
            DriverError: If the LLM call fails.

        Args:
            history: All turns so far (empty on first call).

        Returns:
            The next decision, or None if the LLM returns empty text.
        """
        user_message = self._build_user_message(history=history)
        try:
            prompt_text = await self._send_async(user_message)
        except Exception as exc:
            raise DriverError(
                f"LLMDriver: send_prompt_async failed: {exc}",
            ) from exc

        prompt_text = prompt_text.strip()
        if not prompt_text:
            return None

        return PromptDecision(request=Request(prompt=prompt_text))

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Build the full system prompt from persona, objective, and injections.

        Renders ``prompts/llm_driver_system_prompt.yaml`` with the
        driver's construction-time parameters. All prompt text lives
        in the YAML template; Python only supplies data values.

        Injection metadata (id, format, description) is passed — never
        raw payload content. This avoids embedding attack text in the
        LLM's system prompt (prompt injection risk) and handles binary
        payloads cleanly.
        """
        injections = [
            {
                "id": p.id,
                "format": p.format.value,
                "description": p.metadata.get("description", ""),
            }
            for p in self._injections
        ] or None

        return _SYSTEM_PROMPT_TEMPLATE.render(
            persona_system_prompt=self._persona.system_prompt,
            objective=self._objective,
            injections=injections,
        )

    # ------------------------------------------------------------------
    # User message construction
    # ------------------------------------------------------------------

    def _build_user_message(self, *, history: list[Turn]) -> str:
        """Build the user message for the driving LLM.

        Only sends newly-available information — PyRIT maintains the
        full conversation via CentralMemory.
        """
        if not history:
            return "Begin. Send the first user prompt."

        latest = history[-1]
        parts = [f"Agent response: {latest.response.text}"]

        if latest.eval_result is not None:
            parts.append(f"Evaluator outcome: {latest.eval_result.outcome.value}")
            if latest.eval_result.rationale:
                parts.append(f"Evaluator rationale: {latest.eval_result.rationale}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def _send_async(self, user_message: str) -> str:
        """Send a user message to the driving LLM via PyRIT."""
        piece = MessagePiece(
            role="user",
            original_value=user_message,
            conversation_id=self._conversation_id,
        )
        responses = await self._target.send_prompt_async(
            message=piece.to_message(),
        )
        return responses[0].get_value()
