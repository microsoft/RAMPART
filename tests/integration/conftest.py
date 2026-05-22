# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Shared scaffolding for integration tests.

Everything under ``tests/integration/`` exercises real external
dependencies — most commonly a live LLM endpoint. Two responsibilities
live here:

1. Initialize PyRIT in-memory once per session, pointing PyRIT's
   own dotenv loader at ``tests/integration/.env.local`` when it
   exists. In CI (ADO, GitHub Actions) the file is absent and the
   pipeline's injected environment variables are used as-is.
2. Provide a single ``llm_config`` fixture that reads the
   ``RAMPART_TEST_OPENAI_*`` environment variables and returns an
   ``LLMConfig`` configured with ``temperature=0`` for reproducible
   outputs. When a required variable is missing the fixture issues
   one consolidated ``pytest.skip`` so individual tests do not
   duplicate the env-presence check.

   Authentication: ``RAMPART_TEST_OPENAI_KEY`` is optional *only*
   for Azure endpoints. When omitted there, the underlying PyRIT
   target falls back to ``DefaultAzureCredential``, which covers
   ``az login`` locally as well as managed identity and workload
   identity federation in CI. For non-Azure providers (OpenAI,
   Ollama, self-hosted gateways), the key is required.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from pyrit.setup import IN_MEMORY, initialize_pyrit_async

from rampart.core.llm import LLMConfig

_ENV_LOCAL = Path(__file__).parent / ".env.local"

# Environment variables read by the ``llm_config`` fixture below.
_ENDPOINT_VAR = "RAMPART_TEST_OPENAI_ENDPOINT"
_MODEL_VAR = "RAMPART_TEST_OPENAI_MODEL"
_KEY_VAR = "RAMPART_TEST_OPENAI_KEY"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def pyrit_session_async() -> None:
    """Initialize PyRIT in-memory once per session (autouse).

    Passes ``tests/integration/.env.local`` to PyRIT's dotenv loader
    when the file exists locally. ``initialize_pyrit_async`` validates
    that any path supplied via ``env_files`` exists, so the argument
    is only provided when the file is on disk; in CI it is absent and
    process-injected environment variables are used directly.
    """
    env_files = [_ENV_LOCAL] if _ENV_LOCAL.exists() else None
    await initialize_pyrit_async(memory_db_type=IN_MEMORY, env_files=env_files)


@pytest.fixture
def llm_config() -> LLMConfig:
    """Build an ``LLMConfig`` from ``RAMPART_TEST_OPENAI_*`` env vars.

    Required:
        - ``RAMPART_TEST_OPENAI_ENDPOINT``
        - ``RAMPART_TEST_OPENAI_MODEL`` (for Azure with the
          ``/openai/v1`` URL format, this is the deployment name)

    Optional:
        - ``RAMPART_TEST_OPENAI_KEY`` — API key. When omitted on an
          Azure endpoint, PyRIT authenticates via
          ``DefaultAzureCredential``.

    Returns:
        LLMConfig: A configuration ready to inject into any
            RAMPART component built on the PyRIT bridge.

    The test is skipped with a consolidated message when any required
    variable is missing. ``temperature=0`` is set so model outputs are
    reproducible across runs; tests that need non-deterministic
    behaviour (e.g. variance probes) should construct their own
    ``LLMConfig`` rather than reuse this fixture.
    """
    endpoint = os.environ.get(_ENDPOINT_VAR)
    model = os.environ.get(_MODEL_VAR)

    missing = [
        name
        for name, value in ((_ENDPOINT_VAR, endpoint), (_MODEL_VAR, model))
        if not value
    ]
    if missing:
        pytest.skip(
            "Integration tests require a live LLM endpoint. "
            f"Missing env var(s): {', '.join(missing)}. "
            "See tests/integration/.env.local.example.",
        )
    # ``pytest.skip`` ends the test, but the project's type checker does
    # not recognise it as ``NoReturn``. Narrow explicitly.
    assert endpoint is not None
    assert model is not None

    # Treat ``KEY=`` (empty string) as "unset" so PyRIT falls back to
    # ``DefaultAzureCredential`` on Azure endpoints.
    api_key = os.environ.get(_KEY_VAR) or None

    return LLMConfig(
        model=model,
        endpoint=endpoint,
        api_key=api_key,
        metadata={"temperature": 0.0},
    )
