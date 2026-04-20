# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""PyRIT LLM bridge — translates LLMConfig to PyRIT prompt targets.

This is the ONLY module that instantiates PyRIT prompt target types.
All other RAMPART code works with LLMConfig exclusively.  This isolation
means PyRIT version upgrades only require changes to this file.

Internal module — never imported by consumer code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from pyrit.models import Message, MessagePiece
from pyrit.prompt_target import OpenAIChatTarget, PromptChatTarget

if TYPE_CHECKING:
    from rampart.core.llm import LLMConfig

# OpenAIChatTarget constructor parameters that can be forwarded
# from LLMConfig.metadata.  Kept explicit so unrecognised keys
# are silently ignored rather than causing PyRIT TypeErrors.
_FORWARDED_MODEL_PARAMS: frozenset[str] = frozenset(
    {
        "frequency_penalty",
        "max_completion_tokens",
        "max_requests_per_minute",
        "max_tokens",
        "n",
        "presence_penalty",
        "seed",
        "temperature",
        "top_p",
    },
)


def create_prompt_target(config: LLMConfig) -> PromptChatTarget:
    """Translate a RAMPART LLMConfig into a PyRIT PromptChatTarget.

    This is the single translation point between RAMPART's public
    configuration type and PyRIT's internal target types.

    Azure deployment handling:
        When ``config.deployment`` is set, it becomes the PyRIT
        ``model_name`` (Azure routes by deployment name), and
        ``config.model`` is passed as ``underlying_model`` for
        identification and logging.  When deployment is not set,
        ``config.model`` is used directly as ``model_name``.

    Authentication:
        When ``config.api_key`` is provided, it is passed directly.
        When it is ``None`` and the endpoint is an Azure endpoint,
        PyRIT automatically uses Entra ID authentication.

    Args:
        config: RAMPART LLM configuration.

    Returns:
        A configured PyRIT ``PromptChatTarget``.

    Raises:
        ValueError: If ``config.model`` or ``config.endpoint`` is empty.
    """
    _validate(config)

    if config.deployment:
        model_name = config.deployment
        underlying_model: str | None = config.model
    else:
        model_name = config.model
        underlying_model = None

    model_params = _extract_model_params(config.metadata)

    return OpenAIChatTarget(
        model_name=model_name,
        endpoint=config.endpoint,
        api_key=config.api_key,
        underlying_model=underlying_model,
        **model_params,
    )


def _validate(config: LLMConfig) -> None:
    """Raise early with clear messages for missing required fields."""
    if not config.model:
        msg = "LLMConfig.model is required (e.g. 'gpt-4o')."
        raise ValueError(
            msg,
        )
    if not config.endpoint:
        msg = "LLMConfig.endpoint is required (e.g. 'https://api.openai.com/v1')."
        raise ValueError(
            msg,
        )


def _extract_model_params(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return the subset of *metadata* recognised as model parameters."""
    return {k: v for k, v in metadata.items() if k in _FORWARDED_MODEL_PARAMS}


async def send_generation_request_async(
    *,
    config: LLMConfig,
    system_message: str,
    user_message: str,
) -> str:
    """Send a prompt to an LLM via PyRIT and return the text response.

    Used by ``PayloadGenerator`` for adversarial text generation.
    This is the only function that translates between RAMPART's
    string-based prompt interface and PyRIT's message types.

    Creates a fresh conversation per call — sets the system prompt,
    sends the user message, and extracts the text response.

    For deterministic output, set ``seed`` in ``LLMConfig.metadata``.

    Args:
        config (LLMConfig): RAMPART LLM configuration.
        system_message (str): System prompt (persona identity).
        user_message (str): User prompt (generation instruction).

    Returns:
        str: The LLM's text response.
    """
    target = create_prompt_target(config)
    conversation_id = str(uuid4())

    target.set_system_prompt(
        system_prompt=system_message,
        conversation_id=conversation_id,
    )

    request_piece = MessagePiece(
        role="user",
        original_value=user_message,
        conversation_id=conversation_id,
    )

    # Can remove after bumping to PyRIT v0.13.0
    request = cast("Message", request_piece.to_message())  # pyright: ignore[reportUnknownMemberType]

    responses = await target.send_prompt_async(message=request)
    return responses[0].get_value()
