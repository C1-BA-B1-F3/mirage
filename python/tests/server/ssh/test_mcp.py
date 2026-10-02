import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncssh
import pytest

from mirage.server.ssh.constants import MCP_SUBSYSTEM
from tests.server.ssh.conftest import (
    SSHHarness,
    bind_key,
    start_harness,
    stop_harness,
    vault_workspace,
)

TIMEOUT = 10


class McpChannel:
    """Speaks MCP's stdio framing over an ``mcp`` subsystem channel.

    Args:
        process (asyncssh.SSHClientProcess[str]): the subsystem channel.
    """

    def __init__(self, process: asyncssh.SSHClientProcess[str]) -> None:
        self.process = process
        self._next_id = 0

    async def request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        self._next_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        self.process.stdin.write(json.dumps(message) + "\n")
        while True:
            line = await asyncio.wait_for(
                self.process.stdout.readline(), TIMEOUT
            )
            reply = json.loads(line)
            if reply.get("id") == self._next_id:
                return reply

    async def call(self, name: str, arguments: dict[str, Any]) -> dict:
        reply = await self.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return reply.get("result", reply)


@asynccontextmanager
async def mcp(
    harness: SSHHarness, key: asyncssh.SSHKey | None = None
) -> AsyncIterator[McpChannel]:
    async with harness.connect(key=key) as conn:
        process = await conn.create_process(subsystem=MCP_SUBSYSTEM)
        channel = McpChannel(process)
        await channel.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            )
            + "\n"
        )
        try:
            yield channel
        finally:
            process.stdin.write_eof()
            await asyncio.wait_for(process.wait_closed(), TIMEOUT)


def text(result: dict) -> str:
    return result["content"][0]["text"]


@pytest.mark.asyncio
async def test_serves_the_six_tools(ssh):
    async with mcp(ssh) as channel:
        listed = await channel.request("tools/list", {})
        written = await channel.call(
            "write", {"path": "/a.txt", "content": "hi\n"}
        )
        read = await channel.call("read", {"path": "/a.txt"})
    names = sorted(t["name"] for t in listed["result"]["tools"])
    assert names == ["edit", "execute_command", "grep", "ls", "read", "write"]
    assert written.get("isError") is not True
    assert text(read) == "     1\thi\n"


@pytest.mark.asyncio
async def test_the_channel_is_one_session(ssh):
    async with mcp(ssh) as channel:
        await channel.call("execute_command", {"command": "mkdir /d && cd /d"})
        pwd = await channel.call("execute_command", {"command": "pwd"})
    assert text(pwd) == "/d\n"


@pytest.mark.asyncio
async def test_tools_run_under_the_key_profile(tmp_path):
    harness = await start_harness(tmp_path, await vault_workspace())
    guarded = bind_key(harness, 'mirage-profile="guarded"')
    try:
        async with mcp(harness) as channel:
            opened = await channel.call("read", {"path": "/vault/secret"})
        async with mcp(harness, key=guarded) as channel:
            refused = await channel.call("read", {"path": "/vault/secret"})
            shell = await channel.call(
                "execute_command", {"command": "cat /vault/secret"}
            )
    finally:
        await stop_harness(harness)
    assert text(opened) == "     1\ttoken\n"
    assert refused["isError"] is True
    assert shell["isError"] is True


@pytest.mark.asyncio
async def test_the_session_is_closed_on_exit(ssh):
    async with mcp(ssh) as channel:
        await channel.call("execute_command", {"command": "true"})
    await asyncio.sleep(0.2)
    ids = [s.session_id for s in ssh.entry.runner.ws.list_sessions()]
    assert not [sid for sid in ids if sid.startswith("ssh_")]


@pytest.mark.asyncio
async def test_an_unknown_tool_is_a_protocol_error(ssh):
    async with mcp(ssh) as channel:
        reply = await channel.request(
            "tools/call", {"name": "nope", "arguments": {}}
        )
    assert reply["error"]["code"] == -32602
    assert reply["error"]["message"] == "Tool nope not found"


@pytest.mark.asyncio
async def test_an_unknown_workspace_is_refused(ssh):
    async with ssh.connect(username="nope") as conn:
        process = await conn.create_process(subsystem=MCP_SUBSYSTEM)
        await asyncio.wait_for(process.wait_closed(), TIMEOUT)
        err = await process.stderr.read()
    assert process.exit_status == 1
    assert "no such workspace: nope" in err
