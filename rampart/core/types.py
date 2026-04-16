# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Core data types for the RAMPART framework.

All types in this module are the shared vocabulary of the entire framework —
evaluators, adapters, factories, and reporting all speak in these types.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from rampart.core.manifest import AppManifest


class ObservabilityLevel(Enum):
    """What the adapter can reliably observe during agent execution.

    Declared by the adapter to inform evaluators and reporting. When
    the adapter declares RESPONSE_ONLY, evaluators that require tool
    call data return UNDETERMINED rather than a false SAFE.
    """

    TOOL_AND_SIDE_EFFECTS = "tool_and_side_effects"
    TOOL_ONLY = "tool_only"
    RESPONSE_ONLY = "response_only"


class PayloadFormat(Enum):
    """Delivery format for a payload.

    Text formats deliver ``content`` directly. Binary formats
    deliver via ``artifact`` (a file on disk). Surfaces inspect
    format to decide how to upload or inject the content.

    The ``is_text`` and ``is_binary`` properties let converters,
    surfaces, and the store handle the two categories uniformly
    without listing every enum member.
    """

    # Text formats (content: str)
    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"

    # Binary formats (content: bytes | Path)
    IMAGE = "image"
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    AUDIO = "audio"

    @property
    def is_text(self) -> bool:
        """True if this format carries content as str."""
        return self in (
            PayloadFormat.TEXT,
            PayloadFormat.HTML,
            PayloadFormat.MARKDOWN,
        )

    @property
    def is_binary(self) -> bool:
        """True if this format carries content as bytes or Path."""
        return not self.is_text

    @property
    def extension(self) -> str:
        """File extension including the leading dot (e.g., '.png')."""
        return {
            PayloadFormat.TEXT: ".txt",
            PayloadFormat.HTML: ".html",
            PayloadFormat.MARKDOWN: ".md",
            PayloadFormat.IMAGE: ".png",
            PayloadFormat.PDF: ".pdf",
            PayloadFormat.DOCX: ".docx",
            PayloadFormat.XLSX: ".xlsx",
            PayloadFormat.AUDIO: ".wav",
        }.get(self, ".bin")


@dataclass(kw_only=True)
class Payload:
    """Content to inject into a surface or send alongside a prompt.

    ``content`` is always the semantic text — the attack instruction,
    the adversarial prompt, or a description of the payload's purpose.
    It is what reports display and what makes a payload reproducible.

    For text formats (TEXT, HTML, MARKDOWN), ``content`` is delivered
    directly — no artifact is needed. For binary formats (IMAGE, PDF,
    DOCX), ``artifact`` points to the file that surfaces and adapters
    deliver. The ``content`` field still holds the human-readable text
    for reporting and debugging.

    Args:
        content (str): The semantic text content. Always human-readable.
        id (str): Stable identifier for reproduction and cache keys.
        format (PayloadFormat): Delivery format. TEXT by default.
        artifact (Path | None): Path to a rendered binary file.
            Required for binary formats, must be None for text formats.
        metadata (dict[str, Any]): Provenance tracking (persona,
            template, variant index, generation params).
    """

    content: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    format: PayloadFormat = PayloadFormat.TEXT
    artifact: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate content-format-artifact consistency."""
        if self.format.is_binary and self.artifact is None:
            msg = (
                f"Binary format {self.format.value} requires an "
                f"artifact path. Provide artifact=Path(...) or "
                f"use a converter to render the payload."
            )
            raise TypeError(
                msg,
            )
        if self.format.is_text and self.artifact is not None:
            msg = (
                f"Text format {self.format.value} delivers content "
                f"directly — artifact must be None."
            )
            raise TypeError(
                msg,
            )
        if self.artifact is not None and not self.artifact.exists():
            msg = f"Artifact file does not exist: {self.artifact}"
            raise FileNotFoundError(
                msg,
            )

    def __str__(self) -> str:
        """Human-readable preview of the payload."""
        _preview_max_length = 200
        truncated = self.content[:_preview_max_length]
        suffix = "..." if len(self.content) > _preview_max_length else ""
        return truncated + suffix


@dataclass(kw_only=True)
class ToolCall:
    """A tool invocation observed during agent execution.

    Adapters populate this from whatever observability they have — API
    response fields, telemetry streams, log parsing.

    Args:
        name: Tool name as the agent reported it (e.g., "send_email").
        arguments: Parameters passed to the tool.
        result: Tool return value, if the adapter can observe it.
        timestamp: When the invocation occurred, if available.
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: str | None = None
    timestamp: datetime | None = None


@dataclass(kw_only=True)
class SideEffect:
    """An observable side effect beyond tool invocations.

    Covers effects like HTTP requests, file system changes, or
    database writes that the adapter can observe but that are not
    modeled as tool calls in the agent's API.

    Args:
        kind: Effect category (e.g., "http_request", "file_write").
        details: Structured data about the effect.
    """

    kind: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class Response:
    """What the agent returned for a single prompt.

    The adapter populates every field it can observe.

    Args:
        text: The agent's text response.
        tool_calls: Tool invocations observed during this interaction.
        side_effects: Other observable effects.
        metadata: Adapter-specific diagnostic data.
    """

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    side_effects: list[SideEffect] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class Request:
    """What is sent to the agent in a single turn.

    Combines prompt text and inline payloads into a single object.
    At least one of ``prompt`` or ``attachments`` must be provided.

    Args:
        prompt: The text prompt to send. None when only
            attachments are sent (e.g., inline XPIA).
        attachments: Payloads sent alongside the prompt for
            inline delivery (e.g., poisoned documents).
    """

    prompt: str | None = None
    attachments: list[Payload] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate that the request carries some content."""
        if self.prompt is None and not self.attachments:
            msg = "Request must include at least a prompt or attachments."
            raise ValueError(
                msg,
            )


@dataclass(kw_only=True)
class Turn:
    """One prompt-response exchange.

    Args:
        request: What was sent to the agent.
        response: What the agent returned.
        turn_number: Position in the conversation (0-indexed).
        timestamp: When this exchange occurred.
        driver_reasoning: Why the driver chose this request.
    """

    request: Request
    response: Response
    turn_number: int = 0
    timestamp: datetime | None = None
    driver_reasoning: str = ""


class EvalOutcome(Enum):
    """What the evaluator determined.

    DETECTED: The condition was found.
    NOT_DETECTED: The condition was not found.
    UNDETERMINED: The evaluator could not make a determination.
    """

    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    UNDETERMINED = "undetermined"


@dataclass(kw_only=True)
class EvalResult:
    """What an evaluator returns — a raw condition detection signal.

    This is NOT a safety judgment. Whether DETECTED means "safe" or
    "unsafe" depends on context.

    Args:
        outcome: What the evaluator determined.
        confidence: How confident the evaluator is (0.0 to 1.0).
        evidence: Specific observations supporting the outcome.
        rationale: Human-readable explanation.
    """

    outcome: EvalOutcome
    confidence: float = 1.0
    evidence: list[str] = field(default_factory=list)
    rationale: str = ""

    @property
    def detected(self) -> bool:
        """Convenience: True when the condition was detected."""
        return self.outcome == EvalOutcome.DETECTED


@dataclass(kw_only=True)
class EvalContext:
    """Everything an evaluator needs to make a determination.

    Holds the full conversation as a flat list of turns. Provides
    convenience properties for common access patterns.

    Args:
        turns: All turns in the interaction, in chronological order.
        manifest: The agent's declared capabilities, if available.
        metadata: Additional context from the test setup.
    """

    turns: list[Turn]
    manifest: AppManifest | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def current_turn(self) -> Turn:
        """The most recent turn. Raises ValueError if no turns exist."""
        if not self.turns:
            msg = "No turns in context."
            raise ValueError(msg)
        return self.turns[-1]

    @property
    def text(self) -> str:
        """Current turn's response text."""
        return self.current_turn.response.text

    @property
    def all_tool_calls(self) -> list[ToolCall]:
        """Tool calls across ALL turns, in chronological order."""
        return [tc for turn in self.turns for tc in turn.response.tool_calls]

    @property
    def all_side_effects(self) -> list[SideEffect]:
        """Side effects across ALL turns, in chronological order."""
        return [se for turn in self.turns for se in turn.response.side_effects]

    @classmethod
    def from_response(
        cls,
        *,
        response: Response,
        prompt: str = "",
        manifest: AppManifest | None = None,
    ) -> EvalContext:
        """Build a context from a single response.

        Convenience for evaluating outside the factory flow.

        Args:
            response: The agent response to evaluate.
            prompt: The prompt that produced this response.
            manifest: Optional agent manifest.

        Returns:
            A single-turn evaluation context.
        """
        return cls(
            turns=[Turn(request=Request(prompt=prompt), response=response)],
            manifest=manifest,
        )
