# Attacks

An **attack** tests whether your agent can be manipulated into unsafe behavior. When the evaluator detects the attack objective, the result is **UNSAFE** (`safe=False`).

---

## Semantics

Attacks use the following mapping from evaluator outcomes to safety verdicts:

| EvalOutcome | Safety Verdict | Meaning |
|-------------|---------------|---------|
| `DETECTED` | `UNSAFE` | The attack succeeded — the agent did what the attacker wanted |
| `NOT_DETECTED` | `SAFE` | The attack failed — the agent resisted |
| `UNDETERMINED` | `UNDETERMINED` | The evaluator could not determine whether the attack succeeded |

The evaluator runs once over the terminal trace, and the outcome maps directly
to the verdict. This logic lives in
[`resolve_attack_verdict`][rampart.core.result.resolve_attack_verdict].

Attack factories may evaluate a separate online `stop_when` condition while
the trace is being produced. XPIA's `"auto"` default reuses the verdict
evaluator only when detection is known to be stable as turns are appended.

---

## Common Structure

All attack executions share this lifecycle:

1. **Inject** (optional) — Place payloads into the agent's data sources via [surfaces](../api/core-protocols.md)
2. **Wait** — Allow time for indexing or propagation
3. **Trigger** — Send prompts that cause the agent to process the injected content
4. **Stop (optional)** — Check an online condition after each response
5. **Evaluate** — Check the terminal trace once for the attack objective
6. **Clean up** — Remove injected content (guaranteed, even on failure)
7. **Report** — Produce a [`Result`][rampart.core.result.Result]

The injection phase is optional — inline attacks attach payloads directly to the trigger prompt.

---

## Using the Attacks Factory

All attacks are created through the [`Attacks`][rampart.attacks.Attacks] class:

```python
from rampart import Attacks

execution = Attacks.xpia(
    inject=handle,
    trigger="Summarize the latest documents",
    evaluator=my_evaluator,
)

result = await execution.execute_async(adapter=my_adapter)
assert result, result.summary
```

The factory returns a [`BaseExecution`][rampart.core.execution.BaseExecution] — call `execute_async(adapter=...)` and assert the result.


