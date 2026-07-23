---
description: API reference for RAMPART, auto-generated from source docstrings. Covers core types, protocols, attacks, probes, evaluators, drivers, payloads, surfaces, converters, reporting, and the pytest plugin.
---

# API Reference

API reference organized by RAMPART's package layout. Each page documents the public symbols in one module, auto-generated from source docstrings.


| Page | Contents |
|------|----------|
| [Core Types](core-types.md) | `Payload`, `Request`, `Response`, `Turn`, `Result`, `SafetyStatus`, `HarmCategory`, and more |
| [Core Protocols](core-protocols.md) | `Session`, `AgentAdapter`, `Evaluator`, `Surface`, `InjectionHandle`, and more |
| [Attacks](attacks.md) | `Attacks.xpia()`, `XPIAExecution` |
| [Probes](probes.md) | `Probes.behavior()`, `SingleTurnExecution` |
| [Evaluators](evaluators.md) | `ToolCalled`, `ResponseContains`, `SideEffectOccurred`, `LLMJudge`, `TranscriptScope` |
| [Drivers](drivers.md) | `StaticDriver`, `LLMDriver` |
| [Payloads](payloads.md) | `Payloads`, `PayloadTemplate`, `PayloadStore` |
| [Surfaces](surfaces.md) | `OneDriveSurface` |
| [Converters](converters.md) | `DocxConverter` |
| [Reporting](reporting.md) | `ReportSink`, `TestRunReport`, `JsonFileReportSink` |
| [pytest Plugin](pytest-plugin.md) | `record_result`, markers, hooks |
