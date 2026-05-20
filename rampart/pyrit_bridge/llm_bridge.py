# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""PyRIT integration bridge.

Centralizes ergonomic translation from RAMPART's public LLMConfig
into fully-configured PyRIT prompt targets, and provides helpers
for RAMPART components that integrate with PyRIT (drivers,
payload generators).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pyrit.models import MessagePiece
from pyrit.prompt_target import OpenAIChatTarget, PromptChatTarget

if TYPE_CHECKING:
    from pyrit.identifiers import ComponentIdentifier
    from pyrit.prompt_normalizer import PromptNormalizer

    from rampart.core.llm import LLMConfig

# OpenAIChatTarget constructor parameters that can be forwarded
# from LLMConfig.metadata.  Kept explicit so unrecognised keys
# are silently ignored rather than causing PyRIT TypeErrors.
_FORWARDED_MODEL_PARAMS: frozenset[str] = frozenset(
    {
        "frequency_penalty",
        "is_json_supported",
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

    Ergonomic helper for the common case: OpenAI-compatible endpoints
    configured via LLMConfig. For custom targets, construct them
    directly and pass to ``LLMDriver.from_target``.

    CentralMemory contract:
        PyRIT requires ``CentralMemory`` to be initialized before
        any ``PromptChatTarget`` can be constructed. Callers must
        call ``pyrit.setup.initialize_pyrit_async(...)`` (or set up
        ``CentralMemory`` manually) before calling this function.

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


async def send_user_turn_async(
    *,
    normalizer: PromptNormalizer,
    target: PromptChatTarget,
    conversation_id: str,
    user_message: str,
    labels: dict[str, str] | None = None,
    attack_identifier: ComponentIdentifier | None = None,
) -> str:
    """Send one user turn on an existing conversation via PromptNormalizer.

    Used by multi-turn components (e.g. LLMDriver) where the system
    prompt has already been set and the conversation_id is owned by
    the caller. The normalizer attaches labels and attack_identifier
    to the resulting memory entries for observability.

    Args:
        normalizer: PromptNormalizer instance. Cheap to construct;
            callers may reuse one per component lifetime.
        target: The configured PromptChatTarget.
        conversation_id: The caller-owned conversation id. The
            system prompt for this id must already be set.
        user_message: The user turn content.
        labels: Optional memory labels for this turn.
        attack_identifier: Optional component identifier for tracing.

    Returns:
        The model's text response.
    """
    return await _send_via_normalizer(
        normalizer=normalizer,
        target=target,
        conversation_id=conversation_id,
        user_message=user_message,
        labels=labels,
        attack_identifier=attack_identifier,
    )


async def send_generation_request_async(
    *,
    config: LLMConfig,
    system_message: str,
    user_message: str,
) -> str:
    """Send a prompt to an LLM via PyRIT and return the text response.

    Used by ``PayloadGenerator`` for adversarial text generation.

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
    request = request_piece.to_message()

    responses = await target.send_prompt_async(message=request)
    return responses[0].get_value()


async def send_judge_request_async(
    *,
    normalizer: PromptNormalizer,
    target: PromptChatTarget,
    system_prompt: str,
    user_message: str,
    response_format: str | None = "json",
    labels: dict[str, str] | None = None,
    attack_identifier: ComponentIdentifier | None = None,
) -> str:
    """Send a one-shot judge request and return the response text.

    Creates a fresh conversation per call: sets the system prompt,
    sends the user message via ``PromptNormalizer`` (so the
    interaction lands in ``CentralMemory`` with the given labels),
    and returns the model's text response.

    Args:
        normalizer (PromptNormalizer): Normalizer instance.
        target (PromptChatTarget): Configured PromptChatTarget.
        system_prompt (str): System message content (judge identity,
            detection objective, output schema, and security
            boundary, fully assembled by the caller).
        user_message (str): User message content (the transcript
            being judged).
        response_format (str | None): If ``"json"``, requests JSON
            mode via ``prompt_metadata["response_format"]``. Pass
            ``None`` to skip the hint.
        labels (dict[str, str] | None): Optional memory labels for
            observability.
        attack_identifier (ComponentIdentifier | None): Optional
            component identifier for tracing.

    Returns:
        str: The LLM's text response.
    """
    conversation_id = str(uuid4())

    target.set_system_prompt(
        system_prompt=system_prompt,
        conversation_id=conversation_id,
    )

    prompt_metadata: dict[str, str | int] | None = (
        {"response_format": response_format} if response_format else None
    )
    return await _send_via_normalizer(
        normalizer=normalizer,
        target=target,
        conversation_id=conversation_id,
        user_message=user_message,
        labels=labels,
        attack_identifier=attack_identifier,
        prompt_metadata=prompt_metadata,
    )


async def _send_via_normalizer(
    *,
    normalizer: PromptNormalizer,
    target: PromptChatTarget,
    conversation_id: str,
    user_message: str,
    labels: dict[str, str] | None = None,
    attack_identifier: ComponentIdentifier | None = None,
    prompt_metadata: dict[str, str | int] | None = None,
) -> str:
    """Build a user message, send via normalizer, and return the text.

    Shared implementation for ``send_user_turn_async`` (multi-turn) and
    ``send_judge_request_async`` (one-shot).  Both need the same
    MessagePiece → send_prompt_async → get_value pipeline; this
    helper owns that pipeline so it only exists in one place.

    Args:
        normalizer: PromptNormalizer instance.
        target: The configured PromptChatTarget.
        conversation_id: Conversation identifier (caller-owned or
            freshly generated).
        user_message: The user turn content.
        labels: Optional memory labels.
        attack_identifier: Optional component identifier for tracing.
        prompt_metadata: Optional metadata passed to the model (e.g.
            ``{"response_format": "json"}`` for JSON mode).

    Returns:
        The model's text response.
    """
    request = MessagePiece(
        role="user",
        original_value=user_message,
        conversation_id=conversation_id,
        prompt_metadata=prompt_metadata,
    ).to_message()
    response = await normalizer.send_prompt_async(
        message=request,
        target=target,
        conversation_id=conversation_id,
        labels=labels,
        attack_identifier=attack_identifier,
    )
    return response.get_value()
