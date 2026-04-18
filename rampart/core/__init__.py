# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Core types, protocols, and ABCs.

Re-exports all public core types for convenient access via rampart.core.
"""

from rampart.core.adapter import AgentAdapter, Session
from rampart.core.converter import PayloadConverter
from rampart.core.errors import InfrastructureError
from rampart.core.evaluator import BaseEvaluator, Evaluator
from rampart.core.execution import (
    BaseExecution,
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
    ExecutionHandlerFactory,
)
from rampart.core.injection import InjectionHandle, Surface
from rampart.core.llm import LLMConfig
from rampart.core.manifest import AppManifest, DataSource, ToolDeclaration
from rampart.core.persona import Persona
from rampart.core.prompt_driver import PromptDecision, PromptDriver
from rampart.core.result import (
    HarmCategory,
    InjectionRecord,
    Result,
    SafetyStatus,
    resolve_as_attack,
    resolve_as_probe,
)
from rampart.core.types import (
    EvalContext,
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Payload,
    PayloadFormat,
    Request,
    Response,
    SideEffect,
    ToolCall,
    Turn,
)

__all__ = [
    "AgentAdapter",
    "AppManifest",
    "BaseEvaluator",
    "BaseExecution",
    "DataSource",
    "EvalContext",
    "EvalOutcome",
    "EvalResult",
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
    "Turn",
    "resolve_as_attack",
    "resolve_as_probe",
]
