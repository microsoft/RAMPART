# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""RAMPART — pytest-native safety testing framework for agentic AI.

Public API re-exports for convenient top-level access.
"""

from rampart.attacks import Attacks
from rampart.core.adapter import AgentAdapter, Session
from rampart.core.errors import DriverError, InfrastructureError
from rampart.core.evaluator import BaseEvaluator, Evaluator
from rampart.core.execution import (
    BaseExecution,
    ExecutionEvent,
    ExecutionEventData,
    ExecutionEventHandler,
)
from rampart.core.injection import InjectionHandle, Surface
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
from rampart.drivers.llm import LLMDriver
from rampart.probes import Probes
from rampart.pytest_plugin._collection import record_result

__all__ = [
    "AgentAdapter",
    "AppManifest",
    "Attacks",
    "BaseEvaluator",
    "BaseExecution",
    "DataSource",
    "DriverError",
    "EvalContext",
    "EvalOutcome",
    "EvalResult",
    "Evaluator",
    "ExecutionEvent",
    "ExecutionEventData",
    "ExecutionEventHandler",
    "HarmCategory",
    "InfrastructureError",
    "InjectionHandle",
    "InjectionRecord",
    "LLMDriver",
    "ObservabilityLevel",
    "Payload",
    "PayloadFormat",
    "Persona",
    "Probes",
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
    "record_result",
    "resolve_as_attack",
    "resolve_as_probe",
]
