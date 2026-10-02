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

import asyncio
from typing import Any

from fastapi import FastAPI
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_REQUEST,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
)
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from mirage import __version__
from mirage.server.mcp.server import MirageMcpServer
from mirage.server.registry import WorkspaceEntry, WorkspaceRegistry
from mirage.workspace.session.session import SessionState

MCP_PATH = "/v1/workspaces/{workspace_id}/mcp"


class McpDoor:
    """Serves every workspace's tools over MCP's streamable HTTP.

    The endpoint is stateless: each request runs in the workspace's
    default session, or the one ``?session_id=`` names, as ``/execute``
    picks its session. One tool table per workspace and live session outlives
    the requests, so the read one request stamps guards the edit the next
    one makes. The SDK's session manager starts on the first request, so
    the app serves MCP with or without ASGI lifespan events.

    Args:
        registry (WorkspaceRegistry): the daemon's workspaces.
    """

    def __init__(self, registry: WorkspaceRegistry) -> None:
        self._registry = registry
        self._served: dict[
            tuple[str, str],
            tuple[WorkspaceEntry, SessionState, MirageMcpServer],
        ] = {}
        self.server: Server[dict[str, Any]] = Server(
            "mirage",
            version=__version__,
            on_list_tools=self.list_tools,
            on_call_tool=self.call_tool,
        )
        self._manager = StreamableHTTPSessionManager(
            app=self.server, stateless=True
        )
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        try:
            await self._target(Request(scope, receive))
        except LookupError as exc:
            response = JSONResponse({"detail": exc.args[0]}, status_code=404)
            await response(scope, receive, send)
            return
        await self._start()
        await self._manager.handle_request(scope, receive, send)

    async def _start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._serve())
        await self._ready.wait()

    async def _serve(self) -> None:
        try:
            async with self._manager.run():
                self._ready.set()
                await self._stop.wait()
        finally:
            self._ready.set()

    async def close(self) -> None:
        """Stop the session manager, if a request started it."""
        if self._task is None:
            return
        self._stop.set()
        await self._task

    async def _target(self, request: Request) -> MirageMcpServer:
        """The tool table a request is for.

        Args:
            request (Request): the HTTP request.

        Returns:
            MirageMcpServer: the table for its workspace and session.

        Raises:
            LookupError: the workspace or the session does not exist.
        """
        for key, (entry, held, _) in list(self._served.items()):
            if (
                key[0] not in self._registry
                or self._registry.get(key[0]) is not entry
                or all(s is not held for s in entry.runner.ws.list_sessions())
            ):
                del self._served[key]
        workspace_id = request.path_params["workspace_id"]
        if workspace_id not in self._registry:
            raise LookupError("workspace not found")
        entry = self._registry.get(workspace_id)
        ws = entry.runner.ws
        await entry.runner.call(ws.ensure_sessions_loaded())
        session_id = (
            request.query_params.get("session_id") or ws.default_session_id
        )
        key = (workspace_id, session_id)
        session = next(
            (s for s in ws.list_sessions() if s.session_id == session_id), None
        )
        if session is None:
            self._served.pop(key, None)
            raise LookupError("session not found")
        served = self._served.get(key)
        if served is None or served[1] is not session:
            server = MirageMcpServer(
                ws, session_id=session_id, runner=entry.runner
            )
            self._served[key] = (entry, session, server)
            return server
        return served[2]

    async def _context_target(
        self, ctx: ServerRequestContext[dict[str, Any]]
    ) -> MirageMcpServer:
        if not isinstance(ctx.request, Request):
            raise MCPError(INVALID_REQUEST, "not an HTTP request")
        try:
            return await self._target(ctx.request)
        except LookupError as exc:
            raise MCPError(INVALID_REQUEST, exc.args[0]) from exc

    async def list_tools(
        self,
        ctx: ServerRequestContext[dict[str, Any]],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """Report the tool table of the request's workspace.

        Args:
            ctx (ServerRequestContext[dict[str, Any]]): the request
                context, carrying the HTTP request.
            params (PaginatedRequestParams | None): the page cursor.

        Returns:
            ListToolsResult: every tool the workspace serves.
        """
        target = await self._context_target(ctx)
        return await target.list_tools(ctx, params)

    async def call_tool(
        self,
        ctx: ServerRequestContext[dict[str, Any]],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """Run one tool call in the request's workspace and session.

        Args:
            ctx (ServerRequestContext[dict[str, Any]]): the request
                context, carrying the HTTP request.
            params (CallToolRequestParams): the tool name and arguments.

        Returns:
            CallToolResult: the tool's answer.
        """
        target = await self._context_target(ctx)
        return await target.call_tool(ctx, params)


def register_mcp_routes(app: FastAPI, registry: WorkspaceRegistry) -> McpDoor:
    """Serve MCP at ``/v1/workspaces/{workspace_id}/mcp``.

    The route sits behind the app's host check and auth, as every other
    route does.

    Args:
        app (FastAPI): the daemon app.
        registry (WorkspaceRegistry): the daemon's workspaces.

    Returns:
        McpDoor: the door, whose ``close`` the app's lifespan awaits.
    """
    door = McpDoor(registry)
    app.router.routes.append(
        Route(
            MCP_PATH,
            door,
            methods=["GET", "POST", "DELETE"],
            include_in_schema=False,
        )
    )
    return door
