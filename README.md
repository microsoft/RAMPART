<p align="center">
  <img src="https://github.com/microsoft/RAMPART/raw/main/docs/images/RAMPART.svg" alt="RAMPART Logo" width="300"/>
</p>

<h1 align="center">RAMPART</h1>
<h3 align="center">Risk Assessment & Measurement Platform for Agentic Red Teaming</h3>

<p align="center">
  <strong>A pytest-native safety and security testing framework for agentic AI applications.</strong>
</p>

<p align="center">
  <a href="https://scorecard.dev/viewer/?uri=github.com/microsoft/RAMPART"><img alt="OpenSSF Scorecard" src="https://api.scorecard.dev/projects/github.com/microsoft/RAMPART/badge"></a>
  <a href="https://github.com/microsoft/RAMPART/actions/workflows/ci.yml"><img alt="GitHub CI" src="https://github.com/microsoft/RAMPART/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://pypi.org/project/RAMPART/"><img alt="PyPI - Version" src="https://img.shields.io/pypi/v/RAMPART"></a>
  <a href="https://pypi.org/project/RAMPART/"><img alt="PyPI - Python Version" src="https://img.shields.io/pypi/pyversions/RAMPART"></a>
  <a href="https://pypi.org/project/RAMPART/"><img alt="PyPI - License" src="https://img.shields.io/pypi/l/RAMPART"></a>
</p>

---

RAMPART provides a structured, developer-friendly way to write and run safety and security tests for AI agents -- covering **adversarial attacks**, **benign failures**, and a broad range of **harm categories**, all with evaluation-driven assertions and seamless integration with [pytest](https://docs.pytest.org/).

## Installation

```bash
pip install rampart
```

## Quick Start

```python
result = await Attacks.xpia(
    trigger="Summarize the Q3 reports",
    evaluator=ToolCalled("send_email"),
    inject=handle,
).execute_async(adapter=my_agent)

assert result, result.summary
```

See [Getting Started](https://microsoft.github.io/RAMPART/getting-started/) for the adapter pattern, installation prerequisites, and a complete first test.

## Documentation

Full documentation lives at **[microsoft.github.io/RAMPART](https://microsoft.github.io/RAMPART/)**:

* [Getting Started](https://microsoft.github.io/RAMPART/getting-started/): first test in 5 minutes
* [Concepts](https://microsoft.github.io/RAMPART/concepts/overview/): adapters, evaluators, execution model
* [XPIA Attack](https://microsoft.github.io/RAMPART/attacks/xpia/): cross-platform injection testing
* [Behavioral Probe](https://microsoft.github.io/RAMPART/probes/behavioral/): agent behaviour assertions
* [API Reference](https://microsoft.github.io/RAMPART/api/): class and function reference

## Contributing

Contributions are welcome. See the [Contributing Guide](https://microsoft.github.io/RAMPART/contributing/) for development setup, code style, testing standards, and the pull request process. The repository follows the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/) and most contributions require signing the [Microsoft CLA](https://cla.opensource.microsoft.com).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
