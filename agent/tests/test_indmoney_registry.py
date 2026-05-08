"""Verify the two INDMoney tools are auto-discovered and MCP-published.

The transactions tool was dropped in v2 — INDMoney's MCP has no
transaction-history endpoint, so the only tools that ship are
indmoney_holdings and indmoney_sync.
"""

from __future__ import annotations

_INDMONEY_TOOLS = {"indmoney_holdings", "indmoney_sync"}


def test_indmoney_tools_in_local_registry():
    from src.tools import build_registry
    reg = build_registry()
    names = set(reg.tool_names)
    assert _INDMONEY_TOOLS <= names
    # The dropped transactions tool must NOT appear.
    assert "indmoney_transactions" not in names


def test_indmoney_tools_have_openai_schema():
    from src.tools import build_registry
    reg = build_registry()
    for name in _INDMONEY_TOOLS:
        tool = reg.get(name)
        assert tool is not None
        schema = tool.to_openai_schema()
        assert schema["function"]["name"] == name
        assert "parameters" in schema["function"]


def test_mcp_server_enumerates_indmoney_tools():
    """mcp_server.py builds the same registry; smoke check that import works
    and both tools surface in the underlying registry."""
    import importlib
    mcp_module = importlib.import_module("mcp_server")
    from src.tools import build_registry
    names = set(build_registry().tool_names)
    assert _INDMONEY_TOOLS <= names
    assert hasattr(mcp_module, "_get_registry") or hasattr(mcp_module, "build_registry")
