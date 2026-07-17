# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for the packaging README metadata hook in ``scripts/hatch_build.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import hatch_build

if TYPE_CHECKING:
    from pathlib import Path

RAW = "https://raw.githubusercontent.com/microsoft/RAMPART"


def _write_readme(root: Path, body: str) -> None:
    (root / "README.md").write_text(body, encoding="utf-8")


class TestReadmeRef:
    """_readme_ref pins released versions and falls back to main otherwise."""

    def test_release_version_uses_tag(self) -> None:
        assert hatch_build._readme_ref("0.1.0") == "v0.1.0"

    def test_dev_version_uses_main(self) -> None:
        assert hatch_build._readme_ref("0.1.1.dev35") == "main"

    def test_local_version_uses_main(self) -> None:
        assert hatch_build._readme_ref("0.1.0+g1234567") == "main"


class TestRawImageUrl:
    """_raw_image_url builds a ref-pinned raw GitHub URL."""

    def test_builds_pinned_url(self) -> None:
        url = hatch_build._raw_image_url(
            readme_ref="v0.1.0",
            image_path="docs/images/RAMPART.svg",
        )
        assert url == f"{RAW}/v0.1.0/docs/images/RAMPART.svg"


class TestRenderReadme:
    """_render_readme rewrites docs/images references for the release ref."""

    def test_relative_html_image_rewritten(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, '<img src="docs/images/RAMPART.svg" alt="logo"/>')
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert f'src="{RAW}/v0.1.0/docs/images/RAMPART.svg"' in out

    def test_dotslash_html_image_rewritten(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, '<img src="./docs/images/RAMPART.svg"/>')
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert f"{RAW}/v0.1.0/docs/images/RAMPART.svg" in out
        assert "./docs/images" not in out

    def test_markdown_image_rewritten(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, "![logo](docs/images/RAMPART.svg)")
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert out == f"![logo]({RAW}/v0.1.0/docs/images/RAMPART.svg)"

    def test_titled_markdown_image_preserves_title(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, '![logo](docs/images/RAMPART.svg "RAMPART logo")')
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert out == f'![logo]({RAW}/v0.1.0/docs/images/RAMPART.svg "RAMPART logo")'

    def test_absolute_github_raw_main_repinned(self, tmp_path: Path) -> None:
        _write_readme(
            tmp_path,
            '<img src="https://github.com/microsoft/RAMPART/raw/main/docs/images/RAMPART.svg"/>',
        )
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert "raw/v0.1.0/docs/images/RAMPART.svg" in out
        assert "raw/main/docs/images" not in out

    def test_absolute_raw_host_main_repinned(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, f"{RAW}/main/docs/images/RAMPART.svg")
        out = hatch_build._render_readme(root=tmp_path, version="0.1.0")
        assert f"{RAW}/v0.1.0/docs/images/RAMPART.svg" in out
        assert f"{RAW}/main/docs/images" not in out

    def test_dev_version_keeps_main_ref(self, tmp_path: Path) -> None:
        _write_readme(tmp_path, "![logo](docs/images/RAMPART.svg)")
        out = hatch_build._render_readme(root=tmp_path, version="0.1.1.dev35")
        assert out == f"![logo]({RAW}/main/docs/images/RAMPART.svg)"

    def test_no_image_passthrough(self, tmp_path: Path) -> None:
        body = "# RAMPART\n\nNo images, only [a link](https://example.com).\n"
        _write_readme(tmp_path, body)
        assert hatch_build._render_readme(root=tmp_path, version="0.1.0") == body
