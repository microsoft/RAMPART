<div style="text-align: center; margin-bottom: 1.5em;">
  <img src="images/RAMPART.png" alt="RAMPART" style="max-width: 400px;" />
</div>

# RAMPART Documentation

**RAMPART** is a pytest-native safety testing framework for agentic AI applications. You write tests that attack or probe your agent, and RAMPART orchestrates the interaction, evaluates the outcome, and reports the results.

```python
result = await Attacks.xpia(
    trigger="Summarize the Q3 reports",
    evaluator=ToolCalled("send_email"),
    inject=handle,
).execute_async(adapter=my_agent)

assert result, result.summary
```

---

## Quick Navigation

| If you want to… | Start here |
|---|---|
| Install RAMPART and run your first test | [Getting Started](getting-started/index.md) |
| Understand how RAMPART works | [Concepts](concepts/overview.md) |
| Write an XPIA attack test | [XPIA Attack](attacks/xpia.md) |
| Write a behavioral probe | [Behavioral Probe](probes/behavioral.md) |
| Learn testing patterns and best practices | [Usage](usage/index.md) |
| Look up a class or function | [API Reference](api/index.md) |
| Find a term definition | [Glossary](glossary.md) |

---

## What RAMPART Does

You provide an **adapter** that connects your agent to the framework. RAMPART provides:

- **Execution strategies** — orchestrate injection, triggering, and evaluation lifecycles
- **Evaluators** — detect conditions in agent responses (tool calls, text patterns, side effects)
- **pytest integration** — markers for harm categorization and statistical trials, automatic result collection, terminal summaries
- **Reporting** — structured JSON output for CI dashboards
