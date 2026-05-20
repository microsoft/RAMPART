---
description: Definitions for terms used throughout the RAMPART documentation — adapter, attack, probe, evaluator, surface, payload, and more.
---

# Glossary

Terms used throughout the RAMPART documentation.

**Adapter**
:   An implementation of [`AgentAdapter`][rampart.core.adapter.AgentAdapter]. Connects your agent to RAMPART by creating sessions and declaring capabilities.

**Attack**
:   A test that checks whether your agent can be manipulated into unsafe behavior. When the evaluator detects the attack objective, the result is UNSAFE. See [Attacks](concepts/attacks.md).

**BaseExecution**
:   Abstract base class for all execution strategies. Owns the lifecycle: event dispatch, timing, infrastructure error handling. See [`BaseExecution`][rampart.core.execution.BaseExecution].

**Converter**
:   An implementation of [`PayloadConverter`][rampart.core.converter.PayloadConverter]. Transforms payload content or format before injection.

**Driver**
:   An implementation of [`PromptDriver`][rampart.core.prompt_driver.PromptDriver]. Generates prompts to send to the agent during execution. See [Drivers](api/drivers.md).

**EvalContext**
:   The data passed to an evaluator — contains all turns plus agent manifest. See [`EvalContext`][rampart.core.types.EvalContext].

**EvalOutcome**
:   What an evaluator determined: `DETECTED`, `NOT_DETECTED`, or `UNDETERMINED`. See [`EvalOutcome`][rampart.core.types.EvalOutcome].

**Evaluator**
:   Detects a condition in agent behavior. Polarity-free — answers "did X happen?" See [Evaluators](api/evaluators.md).

**EvaluatorError**
:   Raised by an evaluator for configuration or setup failures (bad endpoint, auth failure). Subclass of `InfrastructureError`; routes through `BaseExecution` to `Result(status=ERROR)`. See [`EvaluatorError`][rampart.core.errors.EvaluatorError].

**Execution**
:   A configured test strategy ready to run. Created by [`Attacks`][rampart.attacks.Attacks] or [`Probes`][rampart.probes.Probes] factory methods. Call `execute_async(adapter=...)` to produce a [`Result`][rampart.core.result.Result].

**HarmCategory**
:   Classification of the safety concern being tested. A `StrEnum` that accepts custom strings. See [`HarmCategory`][rampart.core.result.HarmCategory].

**InjectionHandle**
:   A prepared injection returned by `surface.inject()`. Activate as an async context manager to write the payload; exit to remove it. See [`InjectionHandle`][rampart.core.injection.InjectionHandle].

**Inline XPIA**
:   An XPIA attack where the payload travels as a chat attachment rather than being pre-positioned in an external data source.

**LLMConfig**
:   Immutable configuration for an LLM endpoint. See [`LLMConfig`][rampart.core.llm.LLMConfig].

**LLMJudge**
:   An [`Evaluator`][rampart.core.evaluator.Evaluator] backed by an LLM. Detects diffuse, language-level conditions that pattern-based evaluators can't express (e.g., "did the agent disclose ticket contents?"). Composes with deterministic evaluators via `|` / `&` / `~`. See [`LLMJudge`][rampart.evaluators.llm_judge.LLMJudge].

**Manifest**
:   An [`AppManifest`][rampart.core.manifest.AppManifest] describing your agent's tools, data sources, and capabilities.

**ObservabilityLevel**
:   What your adapter can reliably observe. Affects verdict reliability. See [`ObservabilityLevel`][rampart.core.types.ObservabilityLevel].

**Payload**
:   Content to inject into a surface or send as a chat attachment. See [`Payload`][rampart.core.types.Payload].

**Persona**
:   A named LLM identity used for payload generation or LLM-driven conversation. See [`Persona`][rampart.core.persona.Persona].

**Probe**
:   A test that checks whether your agent exhibits desired behavior. When the evaluator detects the expected behavior, the result is SAFE. See [Probes](concepts/probes.md).

**PyRIT**
:   [Python Risk Identification Tool](https://github.com/microsoft/PyRIT). The upstream library RAMPART builds on. See [PyRIT Integration](concepts/pyrit.md).

**RAMPART**
:   [Risk Assessment & Measurement Platform for Agentic Red Teaming](https://github.com/microsoft/rampart).

**ReportSink**
:   A destination for test run reports. See [`ReportSink`][rampart.reporting.sink.ReportSink].

**Result**
:   The outcome of a safety test. `bool(result)` returns `result.safe`. See [`Result`][rampart.core.result.Result].

**SafetyStatus**
:   Categorical verdict: `SAFE`, `UNSAFE`, `UNDETERMINED`, or `ERROR`. See [`SafetyStatus`][rampart.core.result.SafetyStatus].

**Session**
:   An implementation of [`Session`][rampart.core.adapter.Session]. A bounded unit of interaction with the agent.

**Surface**
:   An implementation of [`Surface`][rampart.core.injection.Surface]. Represents an injectable data source. See [Surfaces](api/surfaces.md).

**Trial**
:   A repeated execution of a test for statistical confidence, configured via `@pytest.mark.trial(n=...)`. See [pytest Markers & Fixtures](usage/pytest-integration.md).

**Turn**
:   One prompt-response exchange. Immutable. See [`Turn`][rampart.core.types.Turn].

**XPIA**
:   Cross-Prompt Injection Attack. Plants malicious content in a data source the agent reads, then triggers the agent to process it. See [XPIA](attacks/xpia.md).
