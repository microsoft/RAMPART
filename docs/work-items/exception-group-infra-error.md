# Broaden `BaseExecution` error handling to produce clean error results for all exceptions

## Problem

`BaseExecution.execute_async` only catches `InfrastructureError` and converts it to a clean `Result(status=SafetyStatus.ERROR)`. All other exceptions — including `TimeoutError`, `ExceptionGroup` (from `asyncio.TaskGroup`), `ConnectionError`, and any unexpected runtime failure — propagate unhandled, crashing the test run instead of producing a reportable result.

This is a gap in the base class's role as the cross-cutting error handler for all execution strategies. Any exception raised during `_execute_async` that isn't an `InfrastructureError` bypasses the error-result path entirely, even when it represents a transient, non-diagnostic failure that should be reported the same way.

## Impact

- **Test runs crash on transient failures.** Any non-`InfrastructureError` exception from a surface, adapter, readiness check, or evaluator aborts the run instead of recording an error result.
- **`asyncio.TaskGroup` amplifies the problem.** Strategies using `TaskGroup` (e.g., XPIA concurrent readiness) will have their exceptions wrapped in `ExceptionGroup`, which the current handler doesn't catch at all.
- **Surface authors must know framework internals.** Today, surfaces must raise `InfrastructureError` specifically, or their failures crash the run. The base class should be resilient to any exception type, not just the framework's own.
- **Inconsistent reporting.** Some failures produce clean error results (those that raise `InfrastructureError`) while equivalent failures from other exception types produce stack traces and test run crashes.

## Proposed Fix

Broaden `BaseExecution.execute_async` to produce clean `Result(status=SafetyStatus.ERROR)` for all non-safety-diagnostic exceptions, not just `InfrastructureError`. Currently, only `InfrastructureError` is caught and converted to an error result — any other exception (including `ExceptionGroup`, `TimeoutError`, `ConnectionError`, etc.) propagates unhandled and crashes the test run.

The fix should be in `BaseExecution.execute_async` so that all execution strategies benefit uniformly, rather than requiring each strategy to catch and re-raise as `InfrastructureError`.

Possible approaches:
1. Widen the `except` clause in `execute_async` to catch `Exception` (and/or `BaseExceptionGroup`) and produce `SafetyStatus.ERROR` for any failure, while still firing `ON_ERROR` for observability.
2. Add an explicit `except ExceptionGroup` / `except* TimeoutError` handler alongside the existing `except InfrastructureError` handler.

The chosen approach should preserve the existing `ON_ERROR` event dispatch so handlers are still notified, while ensuring the test run is never crashed by a transient failure from a surface, adapter, or readiness check.

## Acceptance Criteria

- [ ] `BaseExecution.execute_async` produces `Result(status=SafetyStatus.ERROR)` for exceptions beyond `InfrastructureError`, including `ExceptionGroup` and `TimeoutError`.
- [ ] When any handle's `wait_until_ready()` raises `TimeoutError` (wrapped in `ExceptionGroup` by `TaskGroup`), the test produces a clean error result — not an unhandled exception.
- [ ] `ON_ERROR` event handlers are still notified when a non-`InfrastructureError` exception is caught and converted to an error result.
- [ ] Individual execution strategies (e.g., `XPIAExecution`) do not need to catch and translate exceptions — the base class handles it as a cross-cutting concern.
- [ ] Unit tests in `test_execution.py` verify the broadened error handling for `ExceptionGroup`, `TimeoutError`, and other non-`InfrastructureError` exceptions.
- [ ] Existing tests continue to pass (no regression).
