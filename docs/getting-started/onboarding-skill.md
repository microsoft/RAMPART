# RAMPARTner

**RAMPARTner**, the `rampartner` onboarding skill, helps turn your application's use case into a
useful first safety test, then recommends follow-up tests and payloads grounded
in your code. It distinguishes existing RAMPART capabilities, components you can
build in your project, and gaps worth discussing with maintainers.

It uses the [Agent Skills format](https://agentskills.io/specification), so a
supporting coding assistant can discover and load it when you ask for help with
RAMPART. It is not a hosted service or a separate agent runtime: your assistant
supplies the model and tools, and its usual permissions and costs still apply.

The skill is self-contained at
[`rampart/skills/rampartner/SKILL.md`](https://github.com/microsoft/RAMPART/blob/main/rampart/skills/rampartner/SKILL.md)
and ships in the source repository and Python package.

## Guided conversation

On the first interaction, RAMPARTner greets you and explains its goal:

> Howdy! I'm your RAMPARTner
>
> I'll help you learn RAMPART, build and interpret a meaningful safety test for
> your application, and choose useful next probes or attacks.

The introduction happens once per conversation, not on skill reloads or every
new test. After that, the assistant resumes your progress instead of starting over.

The conversation contract asks the assistant to own the next step throughout
onboarding, including follow-up turns and skill reloads:

- Teach with every response: briefly explain the relevant RAMPART concept, why
  it is useful or necessary now, and how it connects to the user's application.
  Explain commands and generated files rather than just supplying code, and
  tailor the depth to the user's experience without repeating a whole tutorial.
- Ask whether to use RAMPART `main` or the latest published release before
  installing dependencies or building the integration or tests. Explain feature
  availability and API tradeoffs rather than silently choosing a source.
- Continue with clear, authorized work after the user's answer, instead of
  waiting for another "let's do it."
- Treat a completed task as a milestone, not the end of the conversation: propose
  concrete next steps and ask one focused question about what to pursue next.
- Prefer meaningful progress on current cases, such as resolving an evidence gap,
  calibrating a control, or covering a boundary, before expanding the suite.
- Use the host's interactive question tool for one focused decision or missing
  input at a time, rather than ending an unfinished setup with placeholders.
- Clarify whether to reuse an integration or teach the user to build one from
  scratch, and respect that choice.
- Resume from the current goal, environment, evidence, permissions, and blocker
  rather than restarting discovery.
- Obtain explicit agreement on the safety claim and required evidence before
  implementing an evaluator or running a live assessment. Resolve ambiguity
  rather than choosing a weaker claim that is easier to make pass.
- For a from-scratch exercise, treat shipped adapters, surfaces, manifests,
  evaluators, fixtures, and tests as unavailable. Teach and create only the pieces
  the first test needs from the application's actual interface.
- Inspect application code to recommend follow-up tests and explain payload
  construction: reachable lower-trust input, realistic context, attempted
  deviation, delivery evidence, and an observable outcome.

Each test recommendation should explain whether it is a **probe** or an
**attack**, why that type fits, what it adds beyond existing cases, and why it
is worth adding now. A probe checks required behavior: detecting that behavior
means SAFE. An attack tries to induce disallowed behavior: detecting it means
UNSAFE. Both require the agreed evidence; missing evidence is not safety.

For example, a legitimate password-reset probe establishes that the correct
account and recipient receive the intended tool action. A ticket-injection
attack challenges whether untrusted ticket content can redirect that action to
a synthetic unauthorized recipient. These are complementary: benign success
does not demonstrate resistance, and refusing everything does not demonstrate
useful behavior.

After a result or completed task, the assistant should recommend a specific
next step and invite a choice rather than ending with a generic "let me know."
This does not authorize more execution or spending. It must still honor requests
to pause, stop, or avoid follow-ups, and must not keep prompting after a decline.

This agreement is a correctness requirement, not optional conversational polish.
For an injection test, the assistant must clarify what establishes exposure and
whether refusing to act is acceptable or legitimate task completion is required.
A recorded tool result is not automatically equivalent to content reaching an
accepted model request. An apparently SAFE result from a narrower, unconfirmed
test can mislead the user even if the evaluator implements that narrower
predicate correctly.

The assistant should explain verdict conditions and obtain confirmation, reusing
prior explicit instructions rather than repeatedly asking for the same decision.
If evidence required by the agreement is unavailable, it must surface that gap,
not silently relax the evaluator. Material changes and follow-up scenarios
require renewed agreement.

For example, after a user confirms Azure sign-in, the assistant should obtain
the next missing non-secret configuration value, not merely display a template
and wait for the user to restart the conversation. It must still respect
execution permissions, cost limits, manual-operation preferences, and requests
to pause or stop.

These are instructions for the host assistant, not an enforced state machine.
Evaluate the resulting conversation rather than assuming the contract guarantees
the intended behavior.

### Choosing main or the latest release

The skill should verify the latest published release at setup time or resolve
`main` to a commit, then record and pin that version or commit with the project's
dependency tools. The release provides a published baseline; `main` can include
newer, unreleased features and changing APIs. Guidance and generated code must
match the chosen revision, not assume everything in current docs is released.
An existing installation is not an implicit choice. An explicit prior choice
can be reused; changing sources or conflicting dependencies requires discussion.
Choosing a source does not itself authorize installation.

### Finding test results

For each run, the assistant should identify the command and working directory,
point to the **RAMPART Safety Summary** in the pytest terminal output, and explain
the verdict and evidence. In code, `Result.status`, `summary`, and `turns` expose
the outcome and recorded exchanges.

Structured reports require a configured sink. With `JsonFileReportSink`
registered through `pytest_rampart_sinks`, reports go to the chosen `output_dir`
as `run_report_<timestamp>.json` (with a suffix on collisions). `.report` is an
example directory, not an automatic default. The assistant should give the exact
path or link for the current run's artifact, resolving relative directories from
the run's working directory, and confirm it was actually produced. Without a
sink, it should say no RAMPART structured report was saved and offer to configure
one when useful. Missing or failed output must not be presented as an available
report. See [Results and Reporting](../usage/results-and-reporting.md).

### Basic reproducibility

Keep a lightweight record of the application revision and relevant local changes,
RAMPART version or commit, environment/lockfile, model/deployment and available
model version, generation settings, test/payload/evaluator revisions, synthetic
data setup/reset, command, working directory, and result location. Use known,
non-secret facts and label unavailable details rather than inventing them.

The conversation or existing approved report metadata can hold this record;
new tracking files are created only on request. Explain how the record supports
reruns and comparisons, including what changed between runs. Identical settings
do not guarantee identical model output, and differences in timestamped report
files do not by themselves establish a regression.

### Optional independence milestone

After the first useful test, offer to coach the user through rerunning it or
making a small variation themselves. Explain the concept and expected outcome,
then help them locate results and interpret the evidence without taking over.
This is an optional learning exercise, not a quiz or a gate to further help.
Respect a decline and keep existing execution permissions and cost limits.

On request, leave a short runbook covering setup, chosen revisions, run commands,
working directory, result locations, safe reset/cleanup, and limitations. The
goal is independent use of the first tests, not expanding onboarding into CI
implementation or ongoing suite management.

### Building a missing attack or probe

The skill can help implement a suggested case that existing features cannot
express. It first checks whether a custom evaluator, driver, surface, or adapter
is enough. If a new strategy is needed, it guides a local attack or probe using
the chosen revision's extension APIs, such as `BaseExecution`, explaining each
piece rather than merely drafting a feature request.

After agreeing on the evaluation and execution contract, it should author a
runnable implementation, example pytest case, and offline controls covering
verdicts, missing evidence, errors, cleanup, and lifecycle limits as applicable.
The implementation must preserve normal result collection and reporting.
Application-local extensions do not need upstream factory registration; changes
to RAMPART's core or public factories require a separate contribution decision.
See [Extending RAMPART](../contributing/extending-rampart.md).

### Starting from scratch

Make your learning goal explicit if you want to build the integration yourself.
For example:

> I own the Helpdesk Agent Bot and am approaching RAMPART for the first time.
> Assume I have no RAMPART adapter, surface, manifest, evaluators, fixtures, or
> tests. Ignore any shipped RAMPART integration and its walkthrough; inspect my
> application's own code and help me build my first test from scratch. Ask one
> focused question at a time and explicitly agree with me on the verdict and
> evidence requirements. After the first test, suggest code-grounded next tests
> and teach me how to construct effective, safely scoped payloads for an approved
> case. Ask before changing my environment or making external calls.

This premise excludes existing integration as a shortcut; it does not require
deleting the example repository's files. The assistant should discover your
environment and guide any needed installation while preserving your application's
dependency constraints.

Payload guidance should distinguish a plausible hypothesis from demonstrated
effectiveness. A payload must reach the intended lower-trust input, and its
evaluation must satisfy the agreed evidence requirements. Use synthetic data,
benign controls, and bounded runs rather than treating a generic attack string
or an undelivered payload as meaningful coverage.

## Install into a chosen project

Installing RAMPART does **not** register the skill with your assistant. Copy the
skill into a project-level location your host recognizes, keeping the directory
name `rampartner`:

| Assistant | Destination relative to your application's project root |
| --- | --- |
| [GitHub Copilot](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) | `.github/skills/rampartner/SKILL.md` |
| [Claude Code](https://code.claude.com/docs/en/skills) | `.claude/skills/rampartner/SKILL.md` |
| [Codex](https://developers.openai.com/codex/skills) | `.agents/skills/rampartner/SKILL.md` |

Use the location supported by your client version. These are project-local
examples, not instructions to install globally. Do not install the same skill in
multiple discovery locations for the same project.

### From a source checkout

Copy the entire `rampart/skills/rampartner` directory into the selected
skills directory of your application. Only the skill directory is needed, not the
RAMPART source tree. Review an existing destination rather than overwriting it.

### From an installed package

In a Python REPL using the environment where RAMPART is installed, run the
following from your application's project root. For a uv-managed project,
start that REPL with `uv run python`.

```python
from importlib.resources import files
from pathlib import Path

source = files("rampart").joinpath("skills", "rampartner", "SKILL.md")
content = source.read_bytes()
destination = Path(".github", "skills", "rampartner")
destination.mkdir(parents=True, exist_ok=False)
(destination / "SKILL.md").write_bytes(content)
```

Replace `.github` with `.claude` or `.agents` for the other locations above.
The code refuses to replace an existing skill directory. It reads the resource
before creating any directories, so a release without the skill reports the
missing file without leaving a partial installation. For such releases, obtain
the skill from a source checkout; do not upgrade an application's RAMPART
dependency just to install these instructions.

## Start a conversation

Open a fresh assistant conversation in the project after installation. Use your
host's skill list or picker to confirm `rampartner` is available; reload
or restart the host if necessary. Discovery and explicit invocation syntax vary
by client.

Use a request such as:

> I own the Helpdesk Agent Bot and just discovered RAMPART. Help me get set up
> and write a useful safety test for my application. Ask one question at a time,
> and ask before installing dependencies or making external calls.

Confirm the assistant loads the skill. If it does not activate, use the host's
explicit skill invocation or picker and select `rampartner`. For
assistants without skill support, ask the assistant to read and follow the same
`SKILL.md` file for the conversation.

If you do not have an application ready, ask for the bundled offline smoke test.
It uses a fake agent without credentials or model calls to demonstrate framework
wiring, not to assess your application's safety.

Only allow execution against systems you are authorized to test. Use synthetic
data and isolated targets, keep secrets out of chat, and review reports before
sharing them. A passing test covers the agreed condition and observed evidence,
not every possible failure of the application.

For the underlying walkthroughs, see [Installation](installation.md),
[Quickstart](quickstart.md), [Writing Tests](../usage/authoring-tests.md), and
[Extending RAMPART](../contributing/extending-rampart.md).

## Maintaining the skill

Update `rampart/skills/rampartner/SKILL.md` as the single source of
onboarding instructions. Keep it self-contained so users can install just that
directory. `tests/unit/test_onboarding_skill.py` covers discovery metadata, the
leading conversation contract, and the offline example with its negative
control. These checks do not establish conversational quality; assess that
through an interactive onboarding conversation.
