# API Reference — Core Types

Data types shared across the entire framework. All importable from `rampart` directly.

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
        - EvalOutcome
        - EvalResult
        - EvalContext
        - ObservabilityLevel

## Result Types

::: rampart.core.result
    options:
      members:
        - Result
        - SafetyStatus
        - HarmCategory
        - InjectionRecord
        - resolve_as_attack
        - resolve_as_probe

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
