---
description: RAMPART is a pytest-native safety testing framework for agentic AI applications. Write attack and probe tests, orchestrate the interaction, and report results in CI.
---

![RAMPART](images/RAMPART.svg){ .hero-logo }

# RAMPART Documentation

**RAMPART**: Risk Assessment & Measurement Platform for Agentic Red Teaming.

RAMPART is a pytest-native safety testing framework for agentic AI applications. You write tests that attack or probe your agent, and RAMPART orchestrates the interaction, evaluates the outcome, and reports the results.

---

## Quick Navigation

| If you want to… | Start here |
|---|---|
| Install RAMPART and run your first test | [Getting Started](getting-started/index.md) |
| Explore runnable, end-to-end demos | [RAMPART Examples](https://github.com/microsoft/rampart-examples) |
| Understand how RAMPART works | [Concepts](concepts/overview.md) |
| Write an XPIA attack test | [XPIA Attack](attacks/xpia.md) |
| Write a behavioral probe | [Behavioral Probe](probes/behavioral.md) |
| Learn testing patterns and best practices | [Usage](usage/index.md) |
| Contribute back to the project | [Contributing](contributing/index.md) |
| Look up a class or function | [API Reference](api/index.md) |
| Find a term definition | [Glossary](glossary.md) |

---

## What RAMPART Does

You provide an **adapter** that connects your agent to the framework. RAMPART provides:

- **Execution strategies** — orchestrate injection, triggering, and evaluation lifecycles
- **Evaluators** — detect conditions in agent responses (tool calls, text patterns, side effects)
- **pytest integration** — markers for harm categorization and statistical trials, automatic result collection, terminal summaries
- **Parallel execution** — run tests across worker processes with `pytest-xdist`; RAMPART produces a single unified report
- **Reporting** — structured JSON output for CI dashboards
