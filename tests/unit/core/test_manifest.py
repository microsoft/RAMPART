# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""Tests for rampart.core.manifest — AppManifest, ToolDeclaration, DataSource."""

from rampart.core.manifest import AppManifest, DataSource, ToolDeclaration


class TestToolDeclaration:
    def test_construction_with_defaults(self) -> None:
        td = ToolDeclaration(name="send_email")
        assert td.name == "send_email"
        assert td.description == ""
        assert td.parameters == {}
        assert td.permissions == []

    def test_full_construction(self) -> None:
        td = ToolDeclaration(
            name="send_email",
            description="Send an email",
            parameters={"to": "string", "body": "string"},
            permissions=["Mail.Send"],
        )
        assert td.name == "send_email"
        assert td.description == "Send an email"
        assert td.parameters == {"to": "string", "body": "string"}
        assert td.permissions == ["Mail.Send"]


class TestDataSource:
    def test_construction_with_defaults(self) -> None:
        ds = DataSource(name="SharePoint")
        assert ds.name == "SharePoint"
        assert ds.type == ""
        assert ds.writable_by_untrusted is False

    def test_full_construction(self) -> None:
        ds = DataSource(
            name="SharePoint",
            type="sharepoint",
            writable_by_untrusted=True,
        )
        assert ds.writable_by_untrusted is True


class TestAppManifest:
    def test_construction_with_defaults(self) -> None:
        m = AppManifest(name="TestAgent")
        assert m.name == "TestAgent"
        assert m.tools == []
        assert m.data_sources == []
        assert m.description == ""
        assert m.metadata == {}

    def test_declares_tool_true(self) -> None:
        m = AppManifest(
            name="Agent",
            tools=[ToolDeclaration(name="send_email")],
        )
        assert m.declares_tool("send_email") is True

    def test_declares_tool_false(self) -> None:
        m = AppManifest(
            name="Agent",
            tools=[ToolDeclaration(name="send_email")],
        )
        assert m.declares_tool("delete_file") is False

    def test_declares_tool_empty_tools(self) -> None:
        m = AppManifest(name="Agent")
        assert m.declares_tool("send_email") is False

    def test_get_tool_found(self) -> None:
        td = ToolDeclaration(name="send_email", description="Send email")
        m = AppManifest(name="Agent", tools=[td])
        result = m.get_tool("send_email")
        assert result is td

    def test_get_tool_not_found(self) -> None:
        m = AppManifest(
            name="Agent",
            tools=[ToolDeclaration(name="send_email")],
        )
        assert m.get_tool("delete_file") is None

    def test_get_tool_empty_tools(self) -> None:
        m = AppManifest(name="Agent")
        assert m.get_tool("send_email") is None

    def test_multiple_tools(self) -> None:
        t1 = ToolDeclaration(name="send_email")
        t2 = ToolDeclaration(name="create_event")
        m = AppManifest(name="Agent", tools=[t1, t2])
        assert m.declares_tool("send_email") is True
        assert m.declares_tool("create_event") is True
        assert m.get_tool("send_email") is t1
        assert m.get_tool("create_event") is t2
