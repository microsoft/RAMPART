# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Core types, protocols, and ABCs.

Re-exports all public core types for convenient access via rampart.core.
"""

from rampart.core.adapter import AgentAdapter, Session
from rampart.core.converter import PayloadConverter
from rampart.core.errors import DriverError, InfrastructureError
from rampart.core.evaluator import BaseEvaluator, Evaluator
from rampart.core.execution import (
    BaseExecution,
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
    ExecutionHandlerFactory,
    evaluate_turn_async,
    execute_trials_async,
)
from rampart.core.injection import InjectionHandle, Surface
from rampart.core.llm import LLMConfig
from rampart.core.manifest import AppManifest, DataSource, ToolDeclaration
from rampart.core.persona import Persona
from rampart.core.prompt_driver import PromptDecision, PromptDriver
from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
    PopulationRef,
    PopulationResult,
    Result,
    SafetyStatus,
    resolve_as_attack,
    resolve_attack_verdict,
    resolve_probe_verdict,
)
from rampart.core.trace import (
    EvaluationRecord,
    TraceRun,
    evaluate_terminal_async,
    run_trace_async,
)
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    EvaluationPurpose,
    ObservabilityLevel,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    TraceEndReason,
    Turn,
)

__all__ = [
    "AgentAdapter",
    "AppManifest",
    "BaseEvaluator",
    "BaseExecution",
    "DataSource",
    "DriverError",
    "EvalContext",
    "EvalOutcome",
    "EvalResult",
    "EvaluationPurpose",
    "EvaluationRecord",
    "Evaluator",
    "ExecutionEvent",
    "ExecutionEventData",
    "ExecutionEventHandler",
    "ExecutionHandlerFactory",
    "HarmCategory",
    "InfrastructureError",
    "InjectionHandle",
    "InjectionRecord",
    "LLMConfig",
    "ObservabilityLevel",
    "Payload",
    "PayloadConverter",
    "PayloadFormat",
    "Persona",
    "PopulationRef",
    "PopulationResult",
    "PromptDecision",
    "PromptDriver",
    "Request",
    "Response",
    "Result",
    "SafetyStatus",
    "Session",
    "SideEffect",
    "Surface",
    "ToolCall",
    "ToolDeclaration",
    "TraceEndReason",
    "TraceRun",
    "Turn",
    "evaluate_terminal_async",
    "evaluate_turn_async",
    "execute_trials_async",
    "resolve_as_attack",
    "resolve_attack_verdict",
    "resolve_probe_verdict",
    "run_trace_async",
]
