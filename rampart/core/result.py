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

    ``safe`` is a derived property (``status is SafetyStatus.SAFE``),
    not a stored field, so it can never drift out of sync with ``status``.

    Args:
        status: Categorical status for structured reporting.
        summary: Human-readable one-line summary.
        turns: The full conversation for evidence and debugging.
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

    status: SafetyStatus
    summary: str
    turns: list[Turn] = field(default_factory=list[Turn])
    duration_seconds: float = 0.0
    harm_category: HarmCategory | str | None = None
    strategy: str = ""
    observability_level: ObservabilityLevel = ObservabilityLevel.RESPONSE_ONLY
    injections: list[InjectionRecord] = field(
        default_factory=list[InjectionRecord],
    )
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def safe(self) -> bool:
        """Whether the agent behaved safely (``status is SafetyStatus.SAFE``).

        Returns:
            bool: True when the status is SAFE.
        """
        return self.status is SafetyStatus.SAFE

    @property
    def eval_results(self) -> list[EvalResult]:
        """Evaluator outcomes derived from turns."""
        return [t.eval_result for t in self.turns if t.eval_result is not None]

    def __bool__(self) -> bool:
        """Assert-safe: bool(result) means the agent behaved safely.

        Returns:
            bool: ``self.safe`` (True when the agent behaved safely).
        """
        return self.safe

    def __repr__(self) -> str:
        """Show status and summary for quick debugging.

        Returns:
            str: A compact representation including safe, status, and
                summary fields.
        """
        return (
            f"Result(safe={self.safe}, "
            f"status={self.status.value}, "
            f"summary={self.summary!r})"
        )


def resolve_as_attack(*, eval_results: list[EvalResult]) -> SafetyStatus:
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
        SafetyStatus: The resolved status.
    """
    if not eval_results:
        return SafetyStatus.ERROR
    if any(er.detected for er in eval_results):
        return SafetyStatus.UNSAFE
    if any(er.outcome == EvalOutcome.UNDETERMINED for er in eval_results):
        return SafetyStatus.UNDETERMINED
    return SafetyStatus.SAFE


def resolve_as_probe(*, eval_results: list[EvalResult]) -> SafetyStatus:
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
        SafetyStatus: The resolved status.
    """
    if not eval_results:
        return SafetyStatus.ERROR
    if any(er.outcome == EvalOutcome.NOT_DETECTED for er in eval_results):
        return SafetyStatus.UNSAFE
    if any(er.outcome == EvalOutcome.UNDETERMINED for er in eval_results):
        return SafetyStatus.UNDETERMINED
    return SafetyStatus.SAFE


def _summarize_undetermined_operands(*, eval_results: list[EvalResult]) -> str:
    """Describe the parts of an evaluation that never reached a determination.

    A composition settled by a definitive operand keeps that outcome when
    another operand came back UNDETERMINED, so a verdict can be definitive
    while part of the evidence it asked for was never observable. Reporting
    that verdict on its own would read as more assurance than the run
    produced. Lives here, next to the resolvers, because both the attack and
    the probe summary need it and it operates entirely on core types.

    Repeated reasons are collapsed, since a gap in the adapter recurs on
    every turn of a multi-turn run, and anything past the first two is
    counted rather than dropped silently. Private because it words the
    built-in summaries; a strategy that words its own can read the same
    reasons off ``Result.eval_results``.

    Args:
        eval_results (list[EvalResult]): The evaluator outputs.

    Returns:
        str: A trailing clause naming the undetermined parts, or an empty
            string when nothing was left undetermined.
    """
    reasons = list(
        dict.fromkeys(
            stripped
            for er in eval_results
            for reason in er.undetermined_operands
            if (stripped := reason.strip())
        ),
    )
    if not reasons:
        return ""
    named = reasons[:2]
    detail = "; ".join(named)
    remaining = len(reasons) - len(named)
    if remaining:
        detail = f"{detail} (and {remaining} more)"
    return f", but part of the evaluation was undetermined: {detail}"
