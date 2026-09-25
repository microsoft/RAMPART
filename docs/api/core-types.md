# API Reference — Core Types

Data types shared across the entire framework. Stable execution vocabulary is
available from `rampart.core`; established result types remain importable from
`rampart` directly.

## Data Types

::: rampart.core.types
    options:
      members:
        - Payload
        - PayloadFormat
        - Request
        - Response
        - ToolCall
        - SideEffect
        - Turn
        - EvaluationPurpose
        - TraceEndReason
        - EvalOutcome
        - EvalResult
        - EvalContext
        - ObservabilityLevel

## Result Types

::: rampart.core.result
    options:
      members:
        - Result
        - PopulationRef
        - PopulationResult
        - SafetyStatus
        - HarmCategory
        - InjectionRecord
        - resolve_attack_verdict
        - resolve_probe_verdict
        - resolve_as_attack

## Configuration

::: rampart.core.llm
    options:
      members:
        - LLMConfig

::: rampart.core.persona
    options:
      members:
        - Persona

::: rampart.core.prompt_driver
    options:
      members:
        - PromptDecision

## Manifest

::: rampart.core.manifest
    options:
      members:
        - AppManifest
        - ToolDeclaration
        - DataSource
