# RAMPART — Repository Instructions

RAMPART is a pytest-native safety testing framework for agentic AI applications.

## Architecture

RAMPART is organized as a modular framework with these main components:

- **Core** (`rampart/core/`) — Foundational types, protocols, and execution logic: `adapter`, `converter`, `evaluator`, `execution`, `injection`, `llm`, `manifest`, `persona`, `prompt_driver`, `result`, `types`.
- **Probes** (`rampart/probes/`) — Test execution strategies (e.g., single-turn probes).
- **Attacks** (`rampart/attacks/`) — Attack implementations (e.g., XPIA cross-prompt injection).
- **Evaluators** (`rampart/evaluators/`) — Response evaluation: `response_contains`, `side_effect`, `tool_called`.
- **Drivers** (`rampart/drivers/`) — Prompt delivery drivers (e.g., static driver).
- **Converters** (`rampart/converters/`) — Prompt format converters (e.g., DOCX).
- **Surfaces** (`rampart/surfaces/`) — Attack surface integrations (e.g., OneDrive).
- **Payloads** (`rampart/payloads/`) — Payload generation, storage, and templating.
- **Reporting** (`rampart/reporting/`) — Test result reporting (JSON file sink).
- **Pytest Plugin** (`rampart/pytest_plugin/`) — Native pytest integration for test collection and session management.
- **PyRIT Bridge** (`rampart/_pyrit/`) — Isolated boundary for all PyRIT framework interaction (see coding standards for import rules).

## Instruction Files

BEFORE editing or code-reviewing any file, you MUST read the `.github/instructions/` files whose `applyTo` patterns match the files you are about to edit:
- Editing/code-reviewing `**/*.py` → read `coding-standards.instructions.md`
- Editing/code-reviewing `**/tests/**` → also read `unit-tests-standards.instructions.md`

Follow every rule in the applicable instruction files. Do not skip this step.

## Code Review Guidelines

When performing a code review, be selective. Only leave comments for issues that genuinely matter:

- Bugs, logic errors, or security concerns
- Unclear code that would benefit from refactoring for readability
- Violations of the critical coding conventions (async suffix, keyword-only args, type annotations)

Do NOT leave comments about:
- Style nitpicks that ruff would catch automatically
- Missing docstrings or comments — code should be self-explanatory
- Suggestions to add inline comments, logging, or error handling that isn't clearly needed
- Minor naming preferences or subjective "improvements"

Aim for fewer, higher-signal comments. A review with 2-3 important comments is better than 15 trivial ones.
