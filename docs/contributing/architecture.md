# Architecture for Contributors

This page supplements the [Concepts Overview](../concepts/overview.md) with contributor-focused guidance: package layout, extension points, and key design decisions to understand before making changes. Read the **Concepts Overview** first for the component model and execution lifecycle.

---

## Package Layout

The `rampart/` source tree is organized by concern: foundational types live in `core/`, while each extension point gets its own subpackage (`attacks/`, `probes/`, `evaluators/`, `drivers/`, `converters/`, `surfaces/`, `payloads/`, `reporting/`). The `pyrit_bridge/` package groups common PyRIT integration code (see [PyRIT Bridge](#pyrit-bridge) below), and `pytest_plugin/` provides the pytest integration.

- For the component model and how the pieces fit together at runtime, see the [Concepts Overview](../concepts/overview.md).
- For the public symbols exported from each package, see the [API Reference index](../api/index.md).
- For where to put new code, see [Extension Points](#extension-points) below.
- The authoritative layout is always the source tree itself — browse [`rampart/` on GitHub](https://github.com/microsoft/RAMPART/tree/main/rampart).

---

## Key Design Decisions

### Protocols Over ABCs

RAMPART uses `@runtime_checkable` protocols for extension points that consumers implement (`AgentAdapter`, `Session`, `Evaluator`, `Surface`, `PromptDriver`). This means:

- **No inheritance required** — any class with the right methods satisfies the protocol
- **Type-checked at development time** by Pyright in strict mode
- **Verifiable at runtime** with `isinstance` checks

`BaseExecution` is the exception — it's an ABC because it owns the lifecycle skeleton and subclasses share real implementation.

### Factory Classes (`Attacks`, `Probes`)

`Attacks` and `Probes` are **static factory classes** that construct execution objects. They:

- Provide a clean, discoverable API: `Attacks.xpia(...)`, `Probes.behavior(...)`
- Handle input coercion (e.g., `coerce_driver` for flexible trigger input)
- Return `BaseExecution`, hiding the concrete execution class

When adding a new attack or probe, you add a static factory method — not a new class that users instantiate directly.

### Evaluator Polarity

Evaluators are **polarity-free**. They report whether a condition was detected, not whether it's good or bad. The attack/probe factory applies the correct polarity:

- `resolve_as_attack`: detected → UNSAFE
- `resolve_as_probe`: detected → SAFE

This allows the same evaluator (e.g., `ToolCalled`) to be used in both attack and probe contexts.

### Execution Lifecycle Ownership

`BaseExecution` owns all cross-cutting concerns:

- **Event dispatch** — ON_PRE_EXECUTE, ON_POST_EXECUTE, ON_ERROR
- **Timing** — wall-clock duration
- **Error handling** — all exceptions from `_execute_async` are caught and converted to ERROR results
- **Handler registration** — framework-level handlers (result collection) are injected automatically

Subclasses implement only `_execute_async` and `strategy_name`. They should **not** catch `InfrastructureError` — the base class handles it.

### PyRIT Bridge

PyRIT is RAMPART's upstream dependency for converters and prompt generation. Its import chain is heavy, so:

- PyRIT-related logic is grouped under `rampart/pyrit_bridge/`
- Lazy imports inside functions are used to defer the cost
- This boundary keeps RAMPART's core import fast

---

## Extension Points

| Extension Point | Protocol/ABC | Where to add |
|----------------|-------------|--------------|
| New attack strategy | Subclass `BaseExecution` | `rampart/attacks/` |
| New probe strategy | Subclass `BaseExecution` | `rampart/probes/` |
| New evaluator | Implement `Evaluator` protocol | `rampart/evaluators/` |
| New prompt driver | Implement `PromptDriver` protocol | `rampart/drivers/` |
| New attack surface | Implement `Surface` protocol | `rampart/surfaces/` |
| New converter | Implement `PayloadConverter` protocol | `rampart/converters/` |
| New report sink | Implement `ReportSink` protocol | `rampart/reporting/` |
| New payload format | Extend payload system | `rampart/payloads/` |

See [Extending RAMPART](extending-rampart.md) for step-by-step guides.

---

## Module Import Conventions

- Import from the package root (`rampart.core`, `rampart.attacks`) when the symbol is exported in `__init__.py`
- Within the same package, import from the specific module to avoid circular imports
- Internal modules are prefixed with `_` (e.g., `_xpia.py`, `_single_turn.py`) — they are not part of the public API
