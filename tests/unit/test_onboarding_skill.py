# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

from __future__ import annotations

from importlib.resources import files
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from _pytest.pytester import Pytester

pytest_plugins = ["pytester"]


def _skill_parts() -> tuple[dict[str, object], str]:
    skill = (
        files("rampart")
        .joinpath("skills", "rampartner", "SKILL.md")
        .read_text(encoding="utf-8")
    )
    assert skill.startswith("---\n"), "The skill needs YAML frontmatter"
    header, delimiter, body = skill.removeprefix("---\n").partition("\n---\n\n")
    assert delimiter, "The skill frontmatter must end before the instructions"
    metadata = yaml.safe_load(header)
    assert isinstance(metadata, dict)
    assert all(isinstance(key, str) for key in metadata)
    return metadata, body


def _smoke_test_source() -> str:
    _, instructions = _skill_parts()
    _, opening_fence, remainder = instructions.partition("```python\n")
    assert opening_fence, "The bundled onboarding skill needs a Python example"
    source, closing_fence, _ = remainder.partition("\n```")
    assert closing_fence, "The onboarding example must have a closing code fence"
    return source


def _skill_section(heading: str) -> str:
    _, body = _skill_parts()
    _, delimiter, remainder = body.partition(f"## {heading}\n")
    assert delimiter, f"The skill needs a {heading!r} section"
    section, _, _ = remainder.partition("\n## ")
    return " ".join(section.split())


class TestOnboardingSkill:
    def test_metadata_supports_discovery(self) -> None:
        metadata, body = _skill_parts()
        skill_directory = files("rampart").joinpath("skills", "rampartner")
        description = metadata["description"]

        assert metadata["name"] == skill_directory.name == "rampartner"
        assert isinstance(description, str)
        assert 0 < len(description.strip()) <= 1024
        assert metadata["license"] == "MIT"
        assert set(metadata) == {"name", "description", "license"}
        assert len(body.splitlines()) < 500

    def test_first_interaction_introduces_rampartner_and_its_goal(self) -> None:
        _, body = _skill_parts()
        introduction, _, _ = body.partition("## Teach with every response\n")
        guidance = " ".join(introduction.split())

        assert "start your first user-facing reply with exactly" in guidance
        assert "`Howdy! I'm your RAMPARTner`" in guidance
        assert "briefly explain the goal: learn RAMPART" in guidance
        assert "interpret a meaningful application safety test" in guidance
        assert "choose useful next probes or attacks" in guidance
        assert (
            "only once per conversation, not on skill reloads or subsequent tasks"
            in guidance
        )

    def test_conversation_contract_precedes_framework_guidance(self) -> None:
        _, body = _skill_parts()
        contract, heading, _ = body.partition("# RAMPART guidance\n")

        assert heading
        assert contract.startswith("# Conversation contract\n")
        assert "## Teach with every response\n" in contract
        assert contract.index(
            "## Choose the RAMPART source before building\n"
        ) < contract.index("## Confirm the evaluation contract\n")
        assert contract.index("## Confirm the evaluation contract\n") < contract.index(
            "## Own the next step\n"
        )
        assert "## Own the next step\n" in contract
        assert "## Continue after completed tasks\n" in contract
        assert "## Ask focused interactive questions\n" in contract
        assert "## Resume from the current milestone\n" in contract
        assert "## Keep a basic run record\n" in contract
        assert "## Offer an independence milestone\n" in contract
        assert "## Derive next tests and payloads from application code\n" in contract

    def test_completed_tasks_lead_to_concrete_next_steps(self) -> None:
        guidance = _skill_section("Continue after completed tasks")

        assert "including after a task or test case is complete" in guidance
        assert "ask one focused interactive next-step question" in guidance
        assert "progress on the user's current cases" in guidance
        assert "does not authorize extra work, spending, or retries" in guidance
        assert "Honor explicit requests to pause, stop, or avoid follow-ups" in guidance

    def test_recommendations_distinguish_probes_and_attacks(self) -> None:
        guidance = _skill_section("Recommend the next tests")

        assert "**Probe** checks required behavior" in guidance
        assert "detection means SAFE" in guidance
        assert "**Attack** attempts to induce disallowed behavior" in guidance
        assert "detection means UNSAFE" in guidance
        assert "what it adds beyond existing cases" in guidance
        assert "why to prioritize it now" in guidance

    def test_every_response_teaches_the_current_concept(self) -> None:
        guidance = _skill_section("Teach with every response")

        assert "In every response" in guidance
        assert "why it is useful or necessary for this task" in guidance
        assert "connects to the user's application" in guidance
        assert "purpose of commands and generated files" in guidance

    def test_source_choice_is_explicit_before_building(self) -> None:
        guidance = _skill_section("Choose the RAMPART source before building")

        assert "before installing dependencies or building adapters" in guidance
        assert "use RAMPART `main` or the latest published release?" in guidance
        assert "Reuse a prior explicit choice" in guidance
        assert "Record and pin the chosen version or commit" in guidance
        assert "Source choice is not installation permission" in guidance

    def test_results_guidance_identifies_actual_outputs(self) -> None:
        guidance = _skill_section("Show where to find test results")

        assert "`RAMPART Safety Summary`" in guidance
        assert (
            "Without a configured sink, no RAMPART structured report is saved"
            in guidance
        )
        assert "`JsonFileReportSink` and `pytest_rampart_sinks`" in guidance
        assert "resolve relative paths against the run's working directory" in guidance
        assert "`run_report_<timestamp>.json`" in guidance
        assert "Verify artifacts belong to this run before linking them" in guidance

    def test_missing_strategies_get_a_local_implementation_path(self) -> None:
        guidance = _skill_section("Build a missing attack or probe")

        assert "First check the chosen revision" in guidance
        assert "build a new attack or probe in the user's project" in guidance
        assert "`BaseExecution`" in guidance
        assert "`resolve_as_attack` or `resolve_as_probe`" in guidance
        assert "Author a runnable local implementation" in guidance
        assert "offline tests for safe/unsafe outcomes, missing evidence" in guidance
        assert "collection/reporting through the normal lifecycle" in guidance

    def test_reproducibility_records_context_without_promising_determinism(
        self,
    ) -> None:
        guidance = _skill_section("Keep a basic run record")

        assert "application revision and relevant uncommitted changes" in guidance
        assert "resolved RAMPART version/commit" in guidance
        assert "model/deployment identity and exposed model version" in guidance
        assert (
            "generation settings, test/payload/evaluator IDs or revisions" in guidance
        )
        assert "Label unavailable details unknown" in guidance
        assert (
            "Never store secrets or create tracking files unless requested" in guidance
        )
        assert "does not guarantee deterministic model outputs" in guidance

    def test_independence_practice_is_optional_and_user_led(self) -> None:
        guidance = _skill_section("Offer an independence milestone")

        assert "After the first useful test" in guidance
        assert "offer an optional user-led rerun or small test variation" in guidance
        assert "Do not take over unless asked or treat this as a quiz" in guidance
        assert "Respect a decline" in guidance
        assert "does not authorize additional live calls" in guidance
        assert "If requested, provide a short runbook" in guidance
        assert "not an expansion into CI or ongoing suite management" in guidance


@pytest.mark.slow
class TestOnboardingSkillSmokeTest:
    def test_bundled_example_passes(self, pytester: Pytester) -> None:
        pytester.makeini("[pytest]")
        pytester.makepyfile(test_rampart_smoke=_smoke_test_source())

        result = pytester.runpytest_subprocess(
            "-p", "no:cacheprovider", "-q", timeout=180
        )

        result.assert_outcomes(passed=1)
        result.stdout.fnmatch_lines(["*PASS*Expected behavior detected*"])

    def test_negative_control_fails(self, pytester: Pytester) -> None:
        source = _smoke_test_source()
        original = 'Response(text="Please confirm before I change your calendar.")'
        assert source.count(original) == 1
        source = source.replace(
            original,
            'Response(text="I changed your calendar.")',
        )
        pytester.makeini("[pytest]")
        pytester.makepyfile(test_rampart_smoke=source)

        result = pytester.runpytest_subprocess(
            "-p", "no:cacheprovider", "-q", timeout=180
        )

        result.assert_outcomes(failed=1)
        assert result.ret == pytest.ExitCode.TESTS_FAILED
        result.stdout.fnmatch_lines(["*FAIL*UNSAFE*"])
