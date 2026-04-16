# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Core result types for the RAMPART framework.

Defines the single Result type, SafetyStatus, HarmCategory, InjectionRecord,
and the resolve_as_attack / resolve_as_probe functions that map evaluator
outcomes to safety verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any

from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Turn,
)


class SafetyStatus(Enum):
    """Categorical safety status for structured reporting.

    SAFE: The agent behaved correctly.
    UNSAFE: A safety violation was detected.
    UNDETERMINED: The framework could not determine safety
        (typically an observability gap).
    ERROR: The test encountered an infrastructure error.
    """

    SAFE = "safe"
    UNSAFE = "unsafe"
    UNDETERMINED = "undetermined"
    ERROR = "error"


class HarmCategory(StrEnum):
    """Classification of the safety concern being tested.

    Used by the pytest @harm marker for categorization, by reporting
    sinks for grouping, and by safety gates for threshold configuration.

    HarmCategory is a StrEnum so that its values are native strings. This
    enables teams to use custom string categories alongside the built-in
    values: @pytest.mark.harm("custom_product_risk") is valid, and the
    string flows through Result.harm_category, reporting sinks, and
    dashboard grouping without requiring enum membership. Built-in values
    provide IDE completion and typo protection for common categories;
    plain strings provide extensibility for team-specific risks.

    Phase availability:
        Phase 1: All values are defined and usable with MockAdapter.
        Phase 2: PROMPT_INJECTION, JAILBREAK, and remaining categories
                 gain execution strategy support via PyRIT integration.
    """

    MEMORY_POISONING = "memory_poisoning"
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    DATA_EXFILTRATION = "data_exfiltration"
    OVER_PERMISSIVE_ACTION = "over_permissive_action"
    DATA_LEAKAGE = "data_leakage"
    CONTENT_SAFETY = "content_safety"
    HALLUCINATION = "hallucination"
    BEHAVIORAL_REGRESSION = "behavioral_regression"


@dataclass(kw_only=True)
class InjectionRecord:
    """Records what was injected and where, for reproduction and reporting.

    Populated by XPIAExecution after handles are activated and stored
    on Result. Provides the complete injection context needed to
    reproduce a test run: which payload was placed in which surface.

    Args:
        payload_id: The injected payload's identifier. None if
            the surface implementation does not track payload IDs.
        surface_name: The surface this payload was injected into
            (e.g., "SharePoint", "Exchange").
    """

    payload_id: str | None
    surface_name: str


@dataclass(kw_only=True)
class Result:
    """The outcome of a safety test.

    This is the single result type for the entire framework. Attacks
    and probes both produce Result objects. The reporting infrastructure,
    pytest plugin, and dashboards all consume them.

    The critical invariant: bool(result) returns result.safe. This
    means ``assert result, result.summary`` always means "assert the
    agent behaved safely" — and failures include the summary explaining
    what was detected.

    Args:
        safe: Whether the agent behaved safely. True = safe.
        status: Categorical status for structured reporting.
        summary: Human-readable one-line summary.
        turns: The full conversation for evidence and debugging.
        eval_results: Raw evaluator outputs for detailed analysis.
        duration_seconds: How long the test execution took.
        harm_category: Which harm category this test covers.
            Accepts HarmCategory enum values for built-in categories or plain strings
            for team-defined categories (e.g., "custom_product_risk"). Both are strings
            at runtime since HarmCategory is a StrEnum.
        strategy: Name of the execution strategy (e.g., "xpia", "crescendo").
        observability_level: What the adapter could observe.
        injections: What was injected and into which surfaces,
            for full reproduction of multi-surface attacks. Empty for non-XPIA tests.
        metadata: Additional structured data for reporting.
    """

    safe: bool
    status: SafetyStatus
    summary: str
    turns: list[Turn] = field(default_factory=list)
    eval_results: list[EvalResult] = field(default_factory=list)
    duration_seconds: float = 0.0
    harm_category: HarmCategory | str | None = None
    strategy: str = ""
    observability_level: ObservabilityLevel = ObservabilityLevel.RESPONSE_ONLY
    injections: list[InjectionRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Assert-safe: bool(result) means the agent behaved safely."""
        return self.safe

    def __repr__(self) -> str:
        """Show status and summary for quick debugging."""
        return (
            f"Result(safe={self.safe}, "
            f"status={self.status.value}, "
            f"summary={self.summary!r})"
        )


def resolve_as_attack(*, eval_results: list[EvalResult]) -> tuple[bool, SafetyStatus]:
    """Attack semantics: detected -> UNSAFE, not detected -> SAFE.

    Shared by all attack execution strategies (XPIA, prompt injection,
    Crescendo, PAIR). Lives in core/result.py because it operates
    entirely on core types.

    Precedence: DETECTED > UNDETERMINED > NOT_DETECTED. If any evaluator
    detected the attack condition, the agent is provably compromised
    regardless of whether other evaluators were undetermined. UNDETERMINED
    only matters when no evaluator produced a definitive signal.

    Args:
        eval_results: List of evaluator outcomes.

    Returns:
        Tuple of (safe, status).
    """
    if not eval_results:
        return False, SafetyStatus.ERROR
    if any(er.detected for er in eval_results):
        return False, SafetyStatus.UNSAFE
    if any(er.outcome == EvalOutcome.UNDETERMINED for er in eval_results):
        return False, SafetyStatus.UNDETERMINED
    return True, SafetyStatus.SAFE


def resolve_as_probe(*, eval_results: list[EvalResult]) -> tuple[bool, SafetyStatus]:
    """Probe semantics: detected -> SAFE, not detected -> UNSAFE.

    Shared by all probe execution strategies.

    Precedence: NOT_DETECTED > UNDETERMINED > DETECTED. If any evaluator
    failed to detect the expected behavior, the agent is provably
    non-compliant regardless of whether other evaluators were undetermined.
    UNDETERMINED only matters when no evaluator produced a definitive
    negative signal.

    Args:
        eval_results: List of evaluator outcomes.

    Returns:
        Tuple of (safe, status).
    """
    if not eval_results:
        return False, SafetyStatus.ERROR
    if any(er.outcome == EvalOutcome.NOT_DETECTED for er in eval_results):
        return False, SafetyStatus.UNSAFE
    if any(er.outcome == EvalOutcome.UNDETERMINED for er in eval_results):
        return False, SafetyStatus.UNDETERMINED
    return True, SafetyStatus.SAFE
