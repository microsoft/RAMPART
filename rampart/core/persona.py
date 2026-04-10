# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Persona dataclass — shared by payloads/ and drivers/.

A Persona is a named LLM identity used to shape model behavior for
payload generation (adversarial personas) and LLM-backed PromptDriver
implementations (benign user personas).
"""

from dataclasses import dataclass


@dataclass(kw_only=True)
class Persona:
    """A named LLM identity used to shape model behavior.

    Args:
        name: Stable identifier used in cache keys and reports.
        description: Human-readable summary of this persona's role.
        system_prompt: The system message injected into the LLM
            to establish this identity.
    """

    name: str
    description: str = ""
    system_prompt: str = ""
