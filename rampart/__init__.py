# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""RAMPART — pytest-native safety testing framework for agentic AI.

Public API re-exports for convenient top-level access.
"""

from importlib import import_module
from typing import TYPE_CHECKING

from rampart.core.adapter import AgentAdapter, Session
from rampart.core.errors import DriverError, EvaluatorError, InfrastructureError
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
from rampart.pytest_plugin._collection import record_result

if TYPE_CHECKING:
    from rampart.attacks import Attacks
    from rampart.drivers.llm import LLMDriver
    from rampart.evaluators import LLMJudge, TranscriptScope
    from rampart.probes import Probes

__lazy_imports__: dict[str, tuple[str, str]] = {
    "Attacks": ("rampart.attacks", "Attacks"),
    "LLMDriver": ("rampart.drivers.llm", "LLMDriver"),
    "LLMJudge": ("rampart.evaluators", "LLMJudge"),
    "Probes": ("rampart.probes", "Probes"),
    "TranscriptScope": ("rampart.evaluators", "TranscriptScope"),
}

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
    "EvaluatorError",
    "ExecutionEvent",
    "ExecutionEventData",
    "ExecutionEventHandler",
    "HarmCategory",
    "InfrastructureError",
    "InjectionHandle",
    "InjectionRecord",
    "LLMDriver",
    "LLMJudge",
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
    "TranscriptScope",
    "Turn",
    "record_result",
    "resolve_as_attack",
    "resolve_as_probe",
]


def __getattr__(name: str) -> object:
    """Load a PyRIT-backed public export only when requested.

    Args:
        name: Name of the requested module attribute.

    Returns:
        The requested public API object.

    Raises:
        AttributeError: If ``name`` is not a lazy public export.
    """
    try:
        module_name, attribute_name = __lazy_imports__[name]
    except KeyError:
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message) from None

    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return eager and lazy public module attributes."""
    return sorted({*globals(), *__all__})
