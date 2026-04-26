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

    def test_str_minimal(self) -> None:
        m = AppManifest(name="TestBot")
        assert "TARGET AGENT: TestBot" in str(m)

    def test_str_with_description(self) -> None:
        m = AppManifest(name="TestBot", description="A helpful bot")
        result = str(m)
        assert "TARGET AGENT: TestBot" in result
        assert "A helpful bot" in result

    def test_str_with_tools(self) -> None:
        m = AppManifest(
            name="Agent",
            tools=[
                ToolDeclaration(
                    name="send_email",
                    description="Send an email",
                    parameters={"to": "string"},
                ),
            ],
        )
        result = str(m)
        assert "send_email" in result
        assert "Send an email" in result
        assert "Available tools:" in result

    def test_str_with_data_sources(self) -> None:
        m = AppManifest(
            name="Agent",
            data_sources=[
                DataSource(name="SharePoint", writable_by_untrusted=True),
                DataSource(name="Exchange"),
            ],
        )
        result = str(m)
        assert "SharePoint" in result
        assert "writable by untrusted users" in result
        assert "Exchange" in result
        assert "Accessible data sources:" in result
