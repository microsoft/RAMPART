# API Reference — Evaluators

Built-in evaluators. All extend `BaseEvaluator` and support composition via `|`, `&`, `~`.

::: rampart.evaluators
    options:
      members:
        - ToolCalled
        - ResponseContains
        - ResponseScope
        - SideEffectOccurred
        - LLMJudge
        - TranscriptScope
        - NEUTRAL_EVALUATOR
