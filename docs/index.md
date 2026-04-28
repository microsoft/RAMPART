<div style="text-align: center; margin-bottom: 1.5em;">
  <img src="images/RAMPART.png" alt="RAMPART" style="max-width: 400px;" />
</div>

# RAMPART Documentation

**RAMPART** is a pytest-native safety testing framework for agentic AI applications. You write tests that attack or probe your agent, and RAMPART orchestrates the interaction, evaluates the outcome, and reports the results.

---

## Quick Navigation

| If you want to… | Start here |
|---|---|
| Install RAMPART and run your first test | [Getting Started](getting-started/index.md) |
| Understand how RAMPART works | [Concepts](concepts/overview.md) |
| Write an XPIA attack test | [XPIA Attack](attacks/xpia.md) |
| Write a behavioral probe | [Behavioral Probe](probes/behavioral.md) |
| Learn testing patterns and best practices | [Guides](guides/index.md) |
| Look up a class or function | [API Reference](api/index.md) |
| Find a term definition | [Glossary](glossary.md) |

---

## What RAMPART Does

You provide an **adapter** that connects your agent to the framework. RAMPART provides:

- **Execution strategies** — orchestrate injection, triggering, and evaluation lifecycles
- **Evaluators** — detect conditions in agent responses (tool calls, text patterns, side effects)
- **pytest integration** — markers for harm categorization and statistical trials, automatic result collection, terminal summaries
- **Reporting** — structured JSON output for CI dashboards

RAMPART ships with the following **attacks** (more will be added):

- [XPIA](attacks/xpia.md) — Cross-Prompt Injection Attack

RAMPART ships with the following **probes** (more will be added):

- [Behavioral](probes/behavioral.md) — Verify expected agent behavior

---

## Project Info

| | |
|---|---|
| **Python** | ≥ 3.11 |
| **License** | MIT |
| **Dependencies** | [PyRIT](https://github.com/microsoft/PyRIT) v0.13.0, pytest ≥ 9.0 |
| **Source** | [github.com/microsoft/RAMPART](https://github.com/microsoft/RAMPART) |
