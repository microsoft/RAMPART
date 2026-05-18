# Extending RAMPART

This guide walks through the process of extending RAMPART with new attacks, probes, evaluators, prompt drivers, and attack surfaces.

Before reading this page, make sure you're familiar with the [execution lifecycle](../concepts/overview.md) and the [architecture](architecture.md).

## Shared conventions

These apply to every component type below:

- **Exports.** Add the new class to `__all__` in the relevant `rampart/<package>/__init__.py`. If it should be importable from the top-level `rampart` namespace, also re-export it from `rampart/__init__.py`.
- **Tests.** Place tests under `tests/unit/<package>/test_<name>.py`, mirroring the source tree. See [Testing Standards](testing.md#writing-tests-for-new-components) for required patterns.
- **Coding style.** Follow the rules in [Code Style & Linting](code-style.md) (copyright header, `_async` suffix, keyword-only args, full type annotations, Google-style docstrings).
- **Documentation.** Each new component needs a doc page under `docs/` and a nav entry in `mkdocs.yml` — see the [Summary Checklist](#summary-checklist). Preview your changes locally with [`uv run mkdocs serve`](development-setup.md#preview-the-documentation).


## Attack

Attacks test for *bad* behavior. When the evaluator detects the attack objective, the result is **UNSAFE**.

### 1. Create the Execution Class

Create a new file in `rampart/attacks/` (prefixed with `_` to mark it as internal):

```python
# rampart/attacks/_my_attack.py

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""MyAttackExecution — description of the attack strategy."""

from __future__ import annotations

from rampart.core import (
    AgentAdapter,
    BaseExecution,
    Evaluator,
    ExecutionEventHandler,
    PromptDriver,
    Result,
    Turn,
    evaluate_turn_async,
    resolve_as_attack,
)


class MyAttackExecution(BaseExecution):
    """Executes the my-attack lifecycle.

    Args:
        driver (PromptDriver): How to drive the conversation.
        evaluator (Evaluator): What condition to check for.
        max_turns (int): Maximum prompt-response exchanges.
        event_handlers (list[ExecutionEventHandler] | None): Additional handlers.
    """

    def __init__(
        self,
        *,
        driver: PromptDriver,
        evaluator: Evaluator,
        max_turns: int = 25,
        event_handlers: list[ExecutionEventHandler] | None = None,
    ) -> None:
        super().__init__(event_handlers=event_handlers)
        self._driver = driver
        self._evaluator = evaluator
        self._max_turns = max_turns

    @property
    def strategy_name(self) -> str:
        """Short identifier for this strategy (used in Result.strategy)."""
        return "my_attack"

    async def _execute_async(self, *, adapter: AgentAdapter) -> Result:
        """Core execution logic.

        Args:
            adapter (AgentAdapter): The agent to test.

        Returns:
            Result: Safety verdict.
        """
        turns: list[Turn] = []

        async with await adapter.create_session_async() as session:
            for turn_index in range(self._max_turns):
                decision = await self._driver.next_prompt_async(history=turns)
                if decision is None:
                    break

                response = await session.send_async(decision.request)
                turn = await evaluate_turn_async(
                    evaluator=self._evaluator,
                    history=turns,
                    request=decision.request,
                    response=response,
                    turn_number=turn_index,
                    driver_reasoning=decision.reasoning,
                    manifest=adapter.manifest,
                )
                turns.append(turn)

                if turn.eval_result and turn.eval_result.detected:
                    break

        # Use resolve_as_attack: detected → UNSAFE
        eval_results = [t.eval_result for t in turns if t.eval_result is not None]
        safe, status = resolve_as_attack(eval_results=eval_results)

        return Result(
            safe=safe,
            status=status,
            summary="...",
            turns=turns,
            strategy=self.strategy_name,
            observability_level=adapter.observability_profile,
        )
```

Key points:

- **Subclass `BaseExecution`** — it owns the lifecycle skeleton (event dispatch, timing, error handling)
- **Implement `_execute_async`** — this is your strategy-specific logic
- **Implement `strategy_name`** — a short identifier used in `Result.strategy`
- **Use `resolve_as_attack`** — this maps evaluator outcomes to safety verdicts with attack semantics (detected = UNSAFE)
- **Don't wrap `_execute_async` in a broad `try/except`** — `BaseExecution.execute_async` already catches every exception from `_execute_async` and converts it to a `SafetyStatus.ERROR` result.

### 2. Add a Factory Method to `Attacks`

Add a static method to the `Attacks` class in `rampart/attacks/__init__.py`:

```python
@staticmethod
def my_attack(
    *,
    trigger: str | list[str] | Request | list[Request] | PromptDriver,
    evaluator: Evaluator,
    max_turns: int = 25,
    event_handlers: list[ExecutionEventHandler] | None = None,
) -> BaseExecution:
    """Create a my-attack execution.

    Args:
        trigger: User prompt(s) or a PromptDriver.
        evaluator (Evaluator): What condition to check for.
        max_turns (int): Maximum exchanges. Defaults to 25.
        event_handlers: Optional additional handlers.

    Returns:
        BaseExecution: Ready to execute with ``execute_async(adapter=...)``.
    """
    driver = coerce_driver(trigger)
    return MyAttackExecution(
        driver=driver,
        evaluator=evaluator,
        max_turns=max_turns,
        event_handlers=event_handlers,
    )
```

### 3. Write Tests

Attack tests should cover:

- Execution lifecycle (session creation, prompt driving, evaluation)
- Result resolution (detected → UNSAFE, not detected → SAFE)
- Edge cases (max turns reached, early stopping, empty responses)
- Error handling (infrastructure errors → `SafetyStatus.ERROR`)


## Probe

Probes test for the *presence* of desired behavior. When the evaluator detects the expected behavior, the result is **SAFE**.

The process mirrors the [Attack](#attack) walkthrough. The differences are summarized below; only the steps that diverge are repeated.

| | Attack | Probe |
|---|---|---|
| **Location** | `rampart/attacks/_name.py` | `rampart/probes/_name.py` |
| **Factory class** | `Attacks` | `Probes` |
| **Resolution function** | `resolve_as_attack` | `resolve_as_probe` |
| **Detected means** | UNSAFE | SAFE |
| **Injection phase** | Often yes | No |

### 1. Create the Execution Class

The file structure mirrors the [Attack walkthrough](#1-create-the-execution-class) — same imports, `__init__`, and `_execute_async` loop. The diff from `MyAttackExecution` is:

```diff
-from rampart.core import (..., resolve_as_attack)
+from rampart.core import (..., resolve_as_probe)

-class MyAttackExecution(BaseExecution):
+class MyProbeExecution(BaseExecution):

-    return "my_attack"
+    return "my_probe"

-    safe, status = resolve_as_attack(eval_results=eval_results)
+    safe, status = resolve_as_probe(eval_results=eval_results)
```

Place the file in `rampart/probes/` (e.g. `_my_probe.py`). Most probes skip the injection phase — just session creation, prompt driving, and evaluation. For a complete working reference, see [`rampart/probes/_single_turn.py`](https://github.com/microsoft/RAMPART/blob/main/rampart/probes/_single_turn.py).

### 2. Add a Factory Method to `Probes`

Add a static method to the `Probes` class in `rampart/probes/__init__.py`, mirroring the `Attacks.my_attack` example. See [`rampart/probes/__init__.py`](https://github.com/microsoft/RAMPART/blob/main/rampart/probes/__init__.py) for the existing `Probes.behavior` factory as a reference.

### 3. Write Tests

Probe tests have the same surface as attack tests, with two differences:

- **No injection phase** to test.
- **Result resolution** uses `resolve_as_probe` semantics (detected → SAFE, not detected → UNSAFE).


## Evaluator

Evaluators answer "did X happen?" They are **polarity-free** — the same evaluator can be used in both attacks and probes. The `Attacks`/`Probes` factories handle the mapping from detection to safety verdict.

Create a new file in `rampart/evaluators/`:

```python
# rampart/evaluators/my_evaluator.py

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""MyEvaluator — description of what this evaluator checks."""

from __future__ import annotations

from rampart.core.evaluator import BaseEvaluator
from rampart.core.types import EvalContext, EvalOutcome, EvalResult


class MyEvaluator(BaseEvaluator):
    """Checks whether <condition>.

    Args:
        target (str): What to look for.
    """

    def __init__(self, *, target: str) -> None:
        self._target = target

    async def evaluate_async(self, *, context: EvalContext) -> EvalResult:
        """Evaluate the latest turn for the target condition.

        Args:
            context (EvalContext): The evaluation context with turn history.

        Returns:
            EvalResult: Whether the condition was detected, with evidence.
        """
        latest_turn = context.turns[-1]
        detected = self._target in latest_turn.response.text

        return EvalResult(
            outcome=EvalOutcome.DETECTED if detected else EvalOutcome.NOT_DETECTED,
            evidence=[f"Found '{self._target}'"] if detected else [],
            rationale="Target string found in response" if detected else "Not found",
        )
```

Evaluator tests should cover detection, non-detection, edge cases (empty response, missing data), and that `evidence` / `rationale` are populated correctly.


## Prompt Driver

Prompt drivers decide **what** to send to the agent at each turn. They consume conversation history and return a `PromptDecision` (a `Request` plus optional reasoning), or `None` to stop. See the [`PromptDriver` protocol](https://github.com/microsoft/RAMPART/blob/main/rampart/core/prompt_driver.py).

### 1. Implement the Protocol

Create a new file in `rampart/drivers/`:

```python
# rampart/drivers/my_driver.py

# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""MyDriver — description of how this driver picks the next prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rampart.core.prompt_driver import PromptDecision
from rampart.core.types import Request

if TYPE_CHECKING:
    from rampart.core.types import Turn


class MyDriver:
    """Drives the conversation based on <strategy>.

    Args:
        seed_prompt (str): Where to start the conversation.
    """

    def __init__(self, *, seed_prompt: str) -> None:
        self._seed_prompt = seed_prompt

    async def next_prompt_async(
        self,
        *,
        history: list[Turn],
    ) -> PromptDecision | None:
        """Return the next prompt, or None to stop."""
        if not history:
            return PromptDecision(
                request=Request(prompt=self._seed_prompt),
                reasoning="seed prompt",
            )

        # ... decide based on history ...
        return None
```

Key points:

- **Return `None` to stop** — the execution loop ends the conversation.
- **Populate `reasoning`** for LLM-backed drivers so post-test diagnostics can explain choices. Deterministic drivers may leave it empty.
- **No inheritance required** — `PromptDriver` is a `@runtime_checkable` protocol. Any class with `next_prompt_async` satisfies it.

For reference implementations, see [`StaticDriver`](https://github.com/microsoft/RAMPART/blob/main/rampart/drivers/static.py) and [`LLMDriver`](https://github.com/microsoft/RAMPART/blob/main/rampart/drivers/llm.py).


## Attack Surface

Attack surfaces are the data sources where XPIA payloads get planted (OneDrive, SharePoint, Slack, etc.). A surface implementation pairs a `Surface` (fully configured target) with an `InjectionHandle` (an async context manager that activates and cleans up the injection). See the [`Surface` and `InjectionHandle` protocols](https://github.com/microsoft/RAMPART/blob/main/rampart/core/injection.py).

For the basic protocol skeleton, see [Implementing Surfaces](../usage/authoring-tests.md#implementing-surfaces) in the user-facing guide. When contributing a surface to RAMPART itself (under `rampart/surfaces/`), keep these contributor-specific requirements in mind:

- **`Surface.inject` does not activate** — it only prepares the handle. Activation happens when an execution strategy enters the handle as an async context manager.
- **`__aexit__` must be idempotent and must not raise** — cleanup runs even on exceptions, and a failing cleanup must not mask the original error.
- **`wait_until_ready` should bound itself** with `TimeoutError` rather than block indefinitely. For simple delay-based waits, call `sleep_until_ready` from `rampart.core.injection`.
- **Raise `InfrastructureError`** for transient, external failures (timeouts, rate limits, service outages). It's the documented convention for surfaces and adapters to signal "not a safety signal" — `BaseExecution` catches all exceptions and produces an `ERROR` result either way, but the exception type is preserved in metadata for triage.

For a complete reference, see [`OneDriveSurface`](https://github.com/microsoft/RAMPART/blob/main/rampart/surfaces/onedrive.py).


## Summary Checklist

When adding a new component:

- [ ] Implementation file created in the correct package
- [ ] Factory method added (for attacks/probes)
- [ ] Exports updated in `__init__.py`
- [ ] Unit tests written with good coverage
- [ ] Documentation added under `docs/` (e.g. `docs/attacks/<name>.md`, `docs/probes/<name>.md`, or the matching `docs/api/*.md` page) and linked in `mkdocs.yml`
- [ ] `pre-commit run --all-files` passes
- [ ] All CI checks pass
