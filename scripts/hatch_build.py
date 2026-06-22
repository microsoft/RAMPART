# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
"""Hatchling metadata hooks for RAMPART package builds."""

from __future__ import annotations

import re
from pathlib import Path

from hatchling.metadata.plugin.interface import MetadataHookInterface

_GITHUB_IMAGE_URL_PATTERNS = (
    re.compile(r"(https://github\.com/microsoft/RAMPART/raw/)main(/docs/images/)"),
    re.compile(
        r"(https://raw\.githubusercontent\.com/microsoft/RAMPART/)main(/docs/images/)",
    ),
)
_RELATIVE_HTML_IMAGE_URL_PATTERNS = (
    re.compile(r'(<img\b[^>]*\bsrc=")(?:\./)?(docs/images/[^"]+)(")'),
    re.compile(r"(<img\b[^>]*\bsrc=')(?:\./)?(docs/images/[^']+)(')"),
)
_RELATIVE_MARKDOWN_IMAGE_URL_PATTERN = re.compile(
    r"(!\[[^\]]*\]\()(?:\./)?(docs/images/[^)]+)(\))",
)


def _readme_ref(version: str) -> str:
    """Return the Git ref to use for README image URLs."""
    if ".dev" in version or "+" in version:
        return "main"

    return f"v{version}"


def _raw_image_url(*, readme_ref: str, image_path: str) -> str:
    """Return an absolute GitHub raw URL for a README image."""
    return (
        f"https://raw.githubusercontent.com/microsoft/RAMPART/{readme_ref}/{image_path}"
    )


def _render_readme(*, root: Path, version: str) -> str:
    """Render README content for package metadata."""
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_ref = _readme_ref(version)

    for pattern in _GITHUB_IMAGE_URL_PATTERNS:
        readme = pattern.sub(rf"\g<1>{readme_ref}\g<2>", readme)

    for pattern in _RELATIVE_HTML_IMAGE_URL_PATTERNS:
        readme = pattern.sub(
            lambda match: (
                f"{match.group(1)}"
                f"{_raw_image_url(readme_ref=readme_ref, image_path=match.group(2))}"
                f"{match.group(3)}"
            ),
            readme,
        )

    return _RELATIVE_MARKDOWN_IMAGE_URL_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}"
            f"{_raw_image_url(readme_ref=readme_ref, image_path=match.group(2))}"
            f"{match.group(3)}"
        ),
        readme,
    )


class ReadmeMetadataHook(MetadataHookInterface):
    """Generate PyPI README metadata with release-pinned image URLs."""

    def update(self, metadata: dict[str, object]) -> None:
        """Update project metadata in-place."""
        metadata["readme"] = {
            "content-type": "text/markdown",
            "text": _render_readme(
                root=Path(self.root),
                version=str(metadata["version"]),
            ),
        }
