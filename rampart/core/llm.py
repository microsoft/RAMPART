# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""LLM configuration — public model-configuration type.

LLMConfig is the team-facing abstraction for specifying which LLM to
use for adversarial payload generation, multi-turn attack drivers, and
LLM-backed evaluators.  Teams construct it from environment variables
or programmatic values; the framework translates it to internal engine
types behind ``rampart._pyrit`` — no PyRIT type ever surfaces here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class LLMConfig:
    """Immutable configuration for an LLM endpoint.

    Args:
        model: Model identifier (e.g. ``"gpt-4o"``, ``"gpt-4"``).
        endpoint: API endpoint URL.
        api_key: API key for authentication.
        deployment: Azure deployment name, if applicable.
        metadata: Additional provider-specific configuration.
    """

    model: str
    endpoint: str
    api_key: str | None = field(default=None, repr=False)
    deployment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
