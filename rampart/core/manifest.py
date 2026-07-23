# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""AppManifest, ToolDeclaration, and DataSource.

Describes what an agent can do — its tools, data sources, and capabilities.
Used by payload generation, evaluators, and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(kw_only=True)
class ToolDeclaration:
    """A tool the agent can invoke.

    Args:
        name (str): Tool identifier as the agent reports it.
        description (str): What the tool does (used by payload generation).
        parameters (dict[str, Any]): Parameter schema.
        permissions (list[str]): Required permissions (e.g., "Mail.Send").
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict[str, Any])
    permissions: list[str] = field(default_factory=list[str])


@dataclass(kw_only=True)
class DataSource:
    """A data source the agent can access.

    The payload generator uses trust metadata to prioritize targets:
    a data source writable by untrusted users is a higher-priority
    XPIA injection surface.

    Args:
        name (str): Data source identifier (e.g., "SharePoint", "Exchange").
        type (str): Platform type (e.g., "sharepoint", "exchange", "database").
        writable_by_untrusted (bool): Whether untrusted users can write to this
            source. True makes it a higher-priority XPIA target.
    """

    name: str
    type: str = ""
    writable_by_untrusted: bool = False


@dataclass(kw_only=True)
class AppManifest:
    """Structured descriptor of an agent's capabilities.

    Args:
        name (str): Agent display name (e.g., "Microsoft Copilot").
        tools (list[ToolDeclaration]): Tools the agent can invoke.
        data_sources (list[DataSource]): Data sources the agent can access.
        description (str): What the agent does.
        metadata (dict[str, Any]): Additional agent metadata.
    """

    name: str
    tools: list[ToolDeclaration] = field(
        default_factory=list[ToolDeclaration],
    )
    data_sources: list[DataSource] = field(
        default_factory=list[DataSource],
    )
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def declares_tool(self, name: str) -> bool:
        """Check if a tool is declared in the manifest.

        Returns:
            bool: True if a tool with ``name`` exists in ``self.tools``.
        """
        return any(t.name == name for t in self.tools)

    def get_tool(self, name: str) -> ToolDeclaration | None:
        """Get a tool declaration by name, or None if not declared.

        Returns:
            ToolDeclaration | None: The matching declaration, or None if
                no tool with the given name is declared.
        """
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def __str__(self) -> str:
        """Human-readable summary of the agent's capabilities.

        Returns:
            str: A formatted multi-line string describing the agent
                name, description, tools, and data sources — intended
                for debugging and report output.
        """
        sections: list[str] = [f"TARGET AGENT: {self.name}"]

        if self.description:
            sections.append(self.description)

        if self.tools:
            tool_lines: list[str] = []
            for t in self.tools:
                params = ", ".join(f"{k}: {v}" for k, v in t.parameters.items())
                desc = f" — {t.description}" if t.description else ""
                tool_lines.append(f"  - {t.name}({params}){desc}")
            tools = "\n".join(tool_lines)
            sections.append(f"Available tools:\n{tools}")

        if self.data_sources:
            source_lines: list[str] = []
            for ds in self.data_sources:
                writable = (
                    " (writable by untrusted users)" if ds.writable_by_untrusted else ""
                )
                source_lines.append(f"  - {ds.name}{writable}")
            sources = "\n".join(source_lines)
            sections.append(f"Accessible data sources:\n{sources}")

        return "\n\n".join(sections)
