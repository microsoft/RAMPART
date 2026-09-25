# API Reference — Core Protocols

Protocols and ABCs that define RAMPART's extension points. Implement these to connect your agent, data sources, and custom logic to the framework.

## Session & Adapter

::: rampart.core.adapter
    options:
      members:
        - Session
        - AgentAdapter

## Evaluator

::: rampart.core.evaluator
    options:
      members:
        - Evaluator
        - BaseEvaluator

## Prompt Driver

::: rampart.core.prompt_driver
    options:
      members:
        - PromptDriver

## Surface & Injection

::: rampart.core.injection
    options:
      members:
        - Surface
        - InjectionHandle
        - sleep_until_ready_async

## Converter

::: rampart.core.converter
    options:
      members:
        - PayloadConverter

## Execution

::: rampart.core.execution
    options:
      members:
        - BaseExecution
        - ExecutionEvent
        - ExecutionEventData
        - ExecutionEventHandler
        - ExecutionHandlerFactory
        - register_default_handler_factory
        - clear_default_handler_factory

## Trace Execution

::: rampart.core.trace
    options:
      members:
        - EvaluationRecord
        - TraceRun
        - run_trace_async
        - evaluate_terminal_async

## Errors

::: rampart.core.errors
    options:
      show_source: false
