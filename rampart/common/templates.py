# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""YAML prompt-template loader shared by drivers and evaluators.

RAMPART keeps prompt text in YAML files under per-package ``prompts/``
directories.  Each file has a ``value`` key whose content is a Jinja2
template string.  This module provides a single function to load,
parse, and compile those templates so that every consumer uses the
same logic and the same error surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from jinja2 import Template

if TYPE_CHECKING:
    from pathlib import Path


def load_prompt_template(path: Path) -> Template:
    """Load and compile a YAML prompt template as a Jinja2 ``Template``.

    The YAML file is expected to contain at least a ``value`` key whose
    string content is valid Jinja2 markup.  Other metadata keys (e.g.
    ``name``, ``description``, ``parameters``) are ignored by this
    loader — they exist for human documentation.

    Args:
        path: Absolute path to the YAML template file
            (e.g. ``.../prompts/llm_judge.yaml``).

    Returns:
        Template: A compiled Jinja2 ``Template`` ready for ``.render()``.

    Raises:
        FileNotFoundError: If *path* does not exist.
        KeyError: If the YAML file does not contain a ``value`` key.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Template(data["value"])
