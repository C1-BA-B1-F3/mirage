# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import logging
from typing import cast

import anyio
import asyncssh
from mcp.server.stdio import stdio_server

from mirage.server.mcp.server import MirageMcpServer
from mirage.server.registry import WorkspaceRegistry
from mirage.server.ssh.session import (
    key_profile,
    login_env,
    new_session_id,
    open_session,
)

logger = logging.getLogger(__name__)


class ChannelWriter:
    """The channel's stdout as the SDK's stdio transport writes it.

    The transport awaits ``write`` and ``flush``; asyncssh writes
    synchronously and drains.

    Args:
        stdout (asyncssh.SSHWriter[str]): the channel's stdout.
    """

    def __init__(self, stdout: asyncssh.SSHWriter[str]) -> None:
        self._stdout = stdout

    async def write(self, text: str) -> None:
        """Queue one frame on the channel.

        Args:
            text (str): the serialized message and its newline.
        """
        self._stdout.write(text)

    async def flush(self) -> None:
        """Wait until the channel took the queued frames."""
        await self._stdout.drain()


async def serve_mcp(
    registry: WorkspaceRegistry, process: asyncssh.SSHServerProcess[str]
) -> None:
    """Serve one mcp channel: the workspace's tools over MCP's stdio framing.

    The channel runs as a fresh session under the login key's profile,
    else the workspace's default, with the environment an ``ssh`` login
    gets, and the session closes with the channel.

    Args:
        registry (WorkspaceRegistry): the daemon's workspaces.
        process (asyncssh.SSHServerProcess[str]): the channel's process.
    """
    workspace_id = process.get_extra_info("username")
    if workspace_id not in registry:
        process.stderr.write(f"mirage: no such workspace: {workspace_id}\n")
        process.exit(1)
        return
    entry = registry.get(workspace_id)
    session_id = new_session_id()
    runner = entry.runner
    try:
        profile = key_profile(process.channel.get_connection())
        await runner.call(
            open_session(runner.ws, session_id, login_env(process), profile)
        )
    except Exception as exc:
        logger.debug("mcp: cannot open a session on %s: %r", workspace_id, exc)
        process.stderr.write(f"mirage: cannot open a session: {exc}\n")
        process.exit(1)
        return
    server = MirageMcpServer(runner.ws, session_id=session_id, runner=runner)
    try:
        async with stdio_server(
            cast("anyio.AsyncFile[str]", process.stdin),
            cast("anyio.AsyncFile[str]", ChannelWriter(process.stdout)),
        ) as (read_stream, write_stream):
            await server.server.run(
                read_stream,
                write_stream,
                server.server.create_initialization_options(),
            )
    finally:
        if workspace_id in registry and registry.get(workspace_id) is entry:
            await runner.call(runner.ws.close_session(session_id))
    process.exit(0)
