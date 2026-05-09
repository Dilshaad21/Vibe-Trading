"""Verify the INDMoney tools are wired into both the agent registry AND
the vibe-trading-mcp surface.

The v2 PR shipped with a real bug we missed: tools auto-register in the
agent's in-process registry via __subclasses__() discovery, but the MCP
surface is hand-curated via @mcp.tool decorators. Registry membership
alone does NOT expose a tool over MCP. The earlier version of this file
checked only the agent registry — false-positive — so this rewrite asserts
the actual FastMCP surface to prevent the regression from recurring.
"""

from __future__ import annotations

import asyncio
import importlib

_INDMONEY_TOOLS = {"indmoney_holdings", "indmoney_sync"}


def test_indmoney_tools_in_local_registry():
    """Both tools auto-register in the agent's in-process tool registry."""
    from src.tools import build_registry
    reg = build_registry()
    names = set(reg.tool_names)
    assert _INDMONEY_TOOLS <= names
    # The dropped transactions tool must NOT appear.
    assert "indmoney_transactions" not in names


def test_indmoney_tools_have_openai_schema():
    """Both tools serialise to the OpenAI function-calling schema cleanly."""
    from src.tools import build_registry
    reg = build_registry()
    for name in _INDMONEY_TOOLS:
        tool = reg.get(name)
        assert tool is not None
        schema = tool.to_openai_schema()
        assert schema["function"]["name"] == name
        assert "parameters" in schema["function"]


def test_indmoney_and_macro_tools_exposed_via_fastmcp_surface():
    """REGRESSION GUARD: assert the FastMCP server actually advertises the
    INDMoney tools AND the macro_snapshot tool. The earlier version of
    this test only checked the in-process agent registry, which let the
    indmoney v2 PR ship without @mcp.tool wrappers. ``mcp.list_tools()``
    is the public FastMCP API and matches what an MCP client (e.g.
    Claude Code via vibe-trading-mcp) actually sees on tools/list.
    """
    mcp_module = importlib.import_module("mcp_server")
    tools = asyncio.run(mcp_module.mcp.list_tools())
    names = {t.name for t in tools}
    expected = _INDMONEY_TOOLS | {"macro_snapshot"}
    assert expected <= names, (
        f"Required tools missing from FastMCP surface. Saw: {sorted(names)}"
    )
    # Sanity: dropped transactions tool must NOT have re-appeared.
    assert "indmoney_transactions" not in names
