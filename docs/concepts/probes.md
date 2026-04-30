# Probes

A **probe** tests whether your agent exhibits desired behavior. When the evaluator detects the expected behavior, the result is **SAFE** (`safe=True`).

---

## Semantics

Probes use the inverse mapping from evaluator outcomes:

| EvalOutcome | Safety Verdict | Meaning |
|-------------|---------------|---------|
| `DETECTED` | `SAFE` | The expected behavior is present |
| `NOT_DETECTED` | `UNSAFE` | The expected behavior is missing — a regression |
| `UNDETERMINED` | `UNDETERMINED` | The evaluator could not determine whether the behavior is present |

Precedence: `NOT_DETECTED` > `UNDETERMINED` > `DETECTED`. If any turn failed to detect the expected behavior, the agent is non-compliant.

This logic lives in [`resolve_as_probe`][rampart.core.result.resolve_as_probe].

---

## Common Structure

Probe executions are simpler than attacks — no injection phase:

1. **Create session** — Open a fresh session with the agent
2. **Send prompts** — Drive the conversation via the prompt driver
3. **Evaluate** — Check whether the expected behavior is present
4. **Clean up** — Close the session
5. **Report** — Produce a [`Result`][rampart.core.result.Result]

---

## Using the Probes Factory

All probes are created through the [`Probes`][rampart.probes.Probes] class:

```python
from rampart import Probes
from rampart.evaluators import ResponseContains

execution = Probes.behavior(
    prompt="What is 2 + 2?",
    evaluator=ResponseContains("4"),
)

result = await execution.execute_async(adapter=my_adapter)
assert result, result.summary
```

Provide exactly one of `prompt`, `prompts`, or `driver`.

---

## Available Probes

| Probe | Factory Method | Description |
|-------|---------------|-------------|
| [Behavioral](../probes/behavioral.md) | `Probes.behavior(...)` | Verify the agent produces expected responses or behaviors |

More probe types will be added. Each new probe is a new factory method on `Probes`.


