import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from mirage import RAMVFS, MountMode, Workspace
from mirage.server.mcp.relay import McpRelay
from mirage.server.mcp.server import MirageMcpServer


def upstream_server() -> MirageMcpServer:
    return MirageMcpServer(Workspace({"/": RAMVFS()}, mode=MountMode.WRITE))


@pytest.mark.asyncio
async def test_relays_the_tool_table():
    async with Client(upstream_server().server) as upstream:
        upstream_tools = (await upstream.list_tools()).tools
        async with Client(McpRelay(upstream).server) as client:
            relayed = (await client.list_tools()).tools
    assert relayed == upstream_tools


@pytest.mark.asyncio
async def test_relays_a_tool_call():
    async with Client(upstream_server().server) as upstream:
        async with Client(McpRelay(upstream).server) as client:
            await client.call_tool("shell", {"command": "mkdir /d && cd /d"})
            result = await client.call_tool("shell", {"command": "pwd"})
    assert result.content[0].text == "/d\n"
    assert not result.is_error


@pytest.mark.asyncio
async def test_relays_a_protocol_error():
    async with Client(upstream_server().server) as upstream:
        async with Client(McpRelay(upstream).server) as client:
            with pytest.raises(MCPError) as caught:
                await client.call_tool("nope", {})
    assert caught.value.error.code == -32602
    assert caught.value.error.message == "Tool nope not found"
