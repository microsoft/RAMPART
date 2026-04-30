# PyRIT Integration

RAMPART builds on [PyRIT](https://github.com/microsoft/PyRIT) (Python Risk Identification Tool) for LLM interaction, prompt normalization, and conversation memory. RAMPART uses PyRIT under the hood and avoids exposing PyRIT-specific types in its public API.

---

## What RAMPART Uses from PyRIT

| Capability | PyRIT Component | RAMPART Wrapper |
|-----------|-----------------|-----------------|
| LLM communication | `PromptChatTarget`, `OpenAIChatTarget` | [`LLMConfig`][rampart.core.llm.LLMConfig] + `create_prompt_target()` |
| Prompt normalization | `PromptNormalizer` | Used internally by [`LLMDriver`][rampart.drivers.llm.LLMDriver] |
| Conversation memory | `CentralMemory` | Used internally by `LLMDriver` for driver-side conversation tracking |
| Document conversion | `WordDocConverter` | [`DocxConverter`][rampart.converters.docx.DocxConverter] |

---

## The Boundary

RAMPART uses PyRIT internally but aims to keep PyRIT-specific types out of its public API:

- **Common bridge utilities** live in `rampart.pyrit_bridge`, which translates between RAMPART types and PyRIT types
- **Public types** like [`LLMConfig`][rampart.core.llm.LLMConfig], [`Persona`][rampart.core.persona.Persona], and [`Payload`][rampart.core.types.Payload] are RAMPART's own — as a consumer, you generally don't need to import from `pyrit` directly
- The one exception is [`LLMDriver.from_target()`][rampart.drivers.llm.LLMDriver.from_target], which accepts a PyRIT `PromptChatTarget` for custom LLM providers not covered by `LLMConfig`

---

## When You Might See PyRIT

- **Installation**: PyRIT is a direct dependency (`pyrit==0.13.0`). It installs automatically with RAMPART.
- **Error messages**: [`DriverError`][rampart.core.errors.DriverError] may wrap PyRIT exceptions — the original error appears in the message.

---

## What RAMPART Adds on Top

RAMPART is not a thin wrapper around PyRIT. It adds:

- **Safety-test semantics** — attack/probe distinction, safety verdicts, [`Result`][rampart.core.result.Result] with `safe`/`status`
- **Execution orchestration** — injection → trigger → evaluate lifecycle, early stopping, `AsyncExitStack` cleanup
- **pytest integration** — markers, result collection, trial repetition, terminal summary, report sinks
- **Evaluator composition** — `|`, `&`, `~` operators for combining evaluators
- **Type-safe protocols** — [`AgentAdapter`][rampart.core.adapter.AgentAdapter], [`Session`][rampart.core.adapter.Session], [`Surface`][rampart.core.injection.Surface], [`InjectionHandle`][rampart.core.injection.InjectionHandle]

For PyRIT's own documentation, see the [PyRIT docs](https://microsoft.github.io/PyRIT/).


