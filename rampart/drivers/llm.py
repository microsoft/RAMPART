# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LLMDriver — LLM-backed prompt driver.

Wraps a PyRIT PromptChatTarget to generate the next user prompt on
each turn. The driver maintains two related conversations:

  - The **driver-side conversation** with the driving LLM, stored in
    PyRIT's CentralMemory keyed by self._conversation_id. Each turn
    consists of a framework-built user message (containing the latest
    agent response and evaluator feedback) and the LLM's next-prompt
    reply.

  - The **agent-side conversation** with the agent under test,
    represented by the ``history: list[Turn]`` passed into
    ``next_prompt_async`` by the execution loop.

These are linked by a derivation invariant: every user turn in the
driver-side conversation is built from the agent-side history at the
time of that call. The driver enforces this invariant on each call;
desync raises DriverError.

One driver instance = one driver-side conversation. Construct a new
driver per test. Use ``from_target`` for custom targets.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

import yaml
from jinja2 import Template
from pyrit.exceptions import EmptyResponseException
from pyrit.memory import CentralMemory
from pyrit.prompt_normalizer import PromptNormalizer
from pyrit.prompt_target import PromptChatTarget

from rampart.core.errors import DriverError
from rampart.core.llm import LLMConfig
from rampart.core.persona import Persona
from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Payload, Request, Turn
from rampart.pyrit_bridge.llm_bridge import create_prompt_target, send_user_turn_async

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
    the next prompt to send to the target agent.

    The driver maintains two related conversations:

      - The **driver-side conversation** with the driving LLM, stored
        in PyRIT's CentralMemory keyed by ``self._conversation_id``.

      - The **agent-side conversation** with the agent under test,
        represented by ``history: list[Turn]`` passed into
        ``next_prompt_async``.

    Termination is handled externally: the evaluator's early-stop
    (on detection) or the execution loop's max_turns budget. The
    driver never self-terminates — empty LLM responses raise
    ``DriverError`` rather than returning None.

    One driver instance = one driver-side conversation. Construct a
    new driver per test. Use ``from_target`` for custom targets.

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
        self._llm: LLMConfig | None = llm
        self._persona = persona
        self._objective = objective
        self._injections = injections or []

        self._conversation_id = str(uuid.uuid4())
        self._target: PromptChatTarget | None = None
        self._normalizer: PromptNormalizer | None = None
        self._initialized = False

    @classmethod
    def from_target(
        cls,
        *,
        target: PromptChatTarget,
        persona: Persona,
        objective: str | None = None,
        injections: list[Payload] | None = None,
    ) -> LLMDriver:
        """Construct an LLMDriver from a pre-configured PromptChatTarget.

        Use this when you need a target type not covered by
        ``create_prompt_target`` (custom subclass, non-OpenAI provider,
        test double). The system prompt is still assembled from
        persona/objective/injections and set on the given target at
        first use, so do not call ``set_system_prompt`` on the target
        yourself before passing it in.

        Args:
            target: A pre-configured PromptChatTarget. CentralMemory
                must be initialized before the driver's first
                ``next_prompt_async`` call (not at construction time).
            persona: System-prompt identity.
            objective: Optional per-test goal.
            injections: Optional injection metadata for the system prompt.
        """
        driver = cls.__new__(cls)
        driver._llm = None
        driver._persona = persona
        driver._objective = objective
        driver._injections = injections or []
        driver._conversation_id = str(uuid.uuid4())
        driver._target = target
        driver._normalizer = None
        driver._initialized = False
        return driver

    def _ensure_initialized(self) -> None:
        """Construct the PyRIT target and set the system prompt on first use.

        Defers all PyRIT interaction to the first ``next_prompt_async``
        call, which is always async and always happens after
        ``initialize_pyrit_async`` has been called in test setup.
        """
        if self._initialized:
            return

        if self._target is not None:
            # from_target path: target exists, need normalizer + system prompt
            if self._normalizer is None:
                self._normalizer = PromptNormalizer()
            self._target.set_system_prompt(
                system_prompt=self._build_system_prompt(),
                conversation_id=self._conversation_id,
            )
        else:
            # LLMConfig path: create everything from scratch
            if self._llm is None:
                raise DriverError(
                    "LLMDriver: no LLMConfig or target provided. "
                    "Use LLMDriver(llm=...) or LLMDriver.from_target(target=...).",
                )
            self._target = create_prompt_target(self._llm)
            self._normalizer = PromptNormalizer()
            self._target.set_system_prompt(
                system_prompt=self._build_system_prompt(),
                conversation_id=self._conversation_id,
            )

        self._initialized = True

    async def next_prompt_async(
        self,
        *,
        history: list[Turn],
    ) -> PromptDecision | None:
        """Generate the next prompt decision based on conversation history.

        Sends the latest agent-side turn data to the driving LLM and
        returns its plain-text response as the next prompt.

        Raises:
            DriverError: If the LLM call fails or returns an empty
                response.

        Args:
            history: All agent-side turns so far (empty on first call).

        Returns:
            The next decision. Never returns None — termination is
            handled externally by the evaluator or max_turns.
        """
        self._ensure_initialized()
        self._assert_conversations_consistent(history)

        user_message = self._build_user_message(history=history)

        try:
            prompt_text = await self._send_async(user_message)
        except EmptyResponseException as exc:
            raise DriverError(
                "LLMDriver: driving LLM returned empty response after retries. "
                f"conversation_id={self._conversation_id}",
            ) from exc
        except Exception as exc:
            raise DriverError(
                f"LLMDriver: send_user_turn_async failed: {exc}",
            ) from exc

        prompt_text = prompt_text.strip()
        if not prompt_text:
            raise DriverError(
                "LLMDriver: driving LLM returned empty response. "
                "This typically indicates a provider hiccup, a safety filter "
                "trigger on the driver itself, or a misconfigured model. "
                f"conversation_id={self._conversation_id}",
            )

        return PromptDecision(request=Request(prompt=prompt_text))

    def _assert_conversations_consistent(self, history: list[Turn]) -> None:
        """Verify agent-side history length matches driver-side memory state.

        The driver-side conversation (stored in PyRIT CentralMemory under
        self._conversation_id) must have exactly one user turn per
        completed agent-side turn. Divergence means the driver is being
        asked to continue a conversation it did not author — either it was
        reused across tests, or resumed from a history it did not replay.
        """
        if self._target is None:
            raise DriverError(
                "LLMDriver: driver not initialized. "
                "Call next_prompt_async before checking consistency.",
            )
        memory = CentralMemory.get_memory_instance()
        messages = memory.get_conversation(
            conversation_id=self._conversation_id,
        )
        user_turns_in_memory = sum(
            1 for m in messages if m.get_piece().api_role == "user"
        )
        if user_turns_in_memory != len(history):
            raise DriverError(
                f"LLMDriver state desync: agent-side history has "
                f"{len(history)} turns, but driver-side memory has "
                f"{user_turns_in_memory} user turns for conversation "
                f"{self._conversation_id}. Possible causes: the driver was "
                f"reused across tests (construct a new LLMDriver per test), "
                f"or a caller tried to resume a driver mid-conversation "
                f"without replaying history into memory.",
            )

    def _build_system_prompt(self) -> str:
        """Build the full system prompt from persona, objective, and injections.

        Renders ``prompts/llm_driver_system_prompt.yaml`` with the
        driver's construction-time parameters. All prompt text lives
        in the YAML template; Python only supplies data values.

        Injection metadata (id, format, description) is passed to the
        template. Raw payload content is never included.
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

    def _build_user_message(self, *, history: list[Turn]) -> str:
        """Build the user message for the driver-side conversation.

        Only sends newly-available information from the agent-side
        conversation — PyRIT maintains the full driver-side conversation
        via CentralMemory.
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

    async def _send_async(self, user_message: str) -> str:
        """Send a user message on the driver-side conversation via PyRIT."""
        if self._target is None or self._normalizer is None:
            raise DriverError(
                "LLMDriver: driver not initialized. "
                "Call next_prompt_async to initialize before sending.",
            )
        return await send_user_turn_async(
            normalizer=self._normalizer,
            target=self._target,
            conversation_id=self._conversation_id,
            user_message=user_message,
            labels={"rampart.component": "LLMDriver"},
        )
