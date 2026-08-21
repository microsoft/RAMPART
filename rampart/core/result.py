# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Core result types for the RAMPART framework.

Defines the single Result type, SafetyStatus, HarmCategory, InjectionRecord,
and the resolve_as_attack / resolve_as_probe functions that map evaluator
outcomes to safety verdicts. Also holds the private helpers that word the
undetermined parts of a summary, which both execution strategies share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any

from rampart.common.text import safe_str, safe_str_list
from rampart.core.types import (
    EvalOutcome,
    EvalResult,
    ObservabilityLevel,
    Turn,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


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
        observability_level: What the adapter could observe. Required, so
            that a report states a level someone chose rather than one the
            framework assumed. Built-in strategies pass
            ``adapter.observability_profile``.
        turns: The full conversation for evidence and debugging.
        duration_seconds: How long the test execution took.
        harm_category: Which harm category this test covers.
            Accepts HarmCategory enum values for built-in categories or plain strings
            for team-defined categories (e.g., "custom_product_risk"). Both are strings
            at runtime since HarmCategory is a StrEnum.
        strategy: Name of the execution strategy (e.g., "xpia", "crescendo").
        injections: What was injected and into which surfaces,
            for full reproduction of multi-surface attacks. Empty for non-XPIA tests.
        metadata: Additional structured data for reporting.
    """

    status: SafetyStatus
    summary: str
    observability_level: ObservabilityLevel
    turns: list[Turn] = field(default_factory=list[Turn])
    duration_seconds: float = 0.0
    harm_category: HarmCategory | str | None = None
    strategy: str = ""
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

    Reads every result, unlike ``_explain_undetermined``, which reads the
    same field but prefers results that are themselves UNDETERMINED. The
    filters are opposite on purpose: here the verdict is settled and the
    operands are the only record that anything was missing, while there the
    verdict is not settled and the question is which operand caused that.

    Args:
        eval_results (list[EvalResult]): The evaluator outputs.

    Returns:
        str: A trailing clause naming the undetermined parts, or an empty
            string when nothing was left undetermined.
    """
    reasons = _distinct_operand_reasons(eval_results=eval_results)
    if not reasons:
        return ""
    return (
        ", but part of the evaluation was undetermined: "
        f"{_render_reasons(reasons=reasons)}"
    )


def _distinct_reasons(*, reasons: Iterable[object]) -> list[str]:
    """Strip and collapse reasons, keeping first-seen order.

    ``safe_str`` because a third-party evaluator can put anything in
    ``rationale`` or ``undetermined_operands``, and a value that cannot be
    rendered should cost its own reason rather than the whole summary.

    Args:
        reasons (Iterable[object]): Raw reasons, possibly blank or repeated.

    Returns:
        list[str]: Distinct non-blank reasons.
    """
    return list(
        dict.fromkeys(
            stripped
            for reason in reasons
            if (stripped := safe_str(value=reason).strip())
        ),
    )


def _distinct_operand_reasons(*, eval_results: list[EvalResult]) -> list[str]:
    """Collect the operand reasons carried by these results.

    Args:
        eval_results (list[EvalResult]): The evaluator outputs to read.

    Returns:
        list[str]: Distinct non-blank reasons, with repeats collapsed.
    """
    return _distinct_reasons(
        reasons=[
            reason
            for er in eval_results
            for reason in safe_str_list(value=er.undetermined_operands)
        ],
    )


def _render_reasons(*, reasons: list[str]) -> str:
    """Name the first two reasons and count the rest.

    Formats only. Deciding which reasons are distinct belongs to whoever
    gathered them, and both callers reach this through ``_distinct_reasons``,
    which is also what their emptiness checks read.

    Args:
        reasons (list[str]): Distinct reasons, in the order to name them.

    Returns:
        str: The first two joined, with a count of any remainder so that
            nothing is dropped without saying so.
    """
    named = reasons[:2]
    detail = "; ".join(named)
    remaining = len(reasons) - len(named)
    if remaining:
        detail = f"{detail} (and {remaining} more)"
    return detail


def _explain_undetermined(*, eval_results: list[EvalResult], fallback: str) -> str:
    """Say why an evaluation came back undetermined.

    Prefers the operand reasons a composite carried up. A composite words its
    own rationale after the operand it reported first, so on
    ``ToolCalled("x") | SideEffectOccurred("y")`` under an adapter that reports
    neither, the rationale names only the tool-call gap while both are in
    ``undetermined_operands``. Falls back to the rationales of the results that
    stayed undetermined when no operand reasons were carried, which is the case
    for a leaf evaluator.

    Results that are themselves UNDETERMINED are read first. A settled result
    can carry operand reasons of its own, and while the verdict stands those
    explain a gap in the evidence rather than why the verdict could not be
    reached, so they are not allowed to speak over an operand that really did
    stay undetermined.

    They are read only when no result stayed undetermined at all. That is the
    ``_adjust_for_observability`` case: the verdict was SAFE, so every result
    is settled, and the downgrade to UNDETERMINED is itself an observability
    finding. The gap those operands recorded is the whole explanation, and the
    alternative is a fixed phrase that names nothing. An operand that stayed
    undetermined and explained nothing keeps that fixed phrase instead, since
    a gap another turn settled around is not why this verdict was missed.

    Args:
        eval_results (list[EvalResult]): The evaluator outputs.
        fallback (str): Wording to use when no reason is available at all.

    Returns:
        str: The reason detail for the summary.
    """
    undetermined = [er for er in eval_results if er.outcome == EvalOutcome.UNDETERMINED]
    reasons = _distinct_operand_reasons(eval_results=undetermined)
    if not reasons:
        # Stripped here rather than filtered on truthiness, so that a
        # rationale of only whitespace falls through instead of rendering
        # a summary with nothing after the colon.
        reasons = _distinct_reasons(reasons=[er.rationale for er in undetermined])
    if not reasons and not undetermined:
        reasons = _distinct_operand_reasons(eval_results=eval_results)
    if not reasons:
        return fallback
    return _render_reasons(reasons=reasons)
