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
from typing import Any

import jsonschema
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)

from mirage import __version__
from mirage.agents.tool_descriptions import (
    EDIT_DESCRIPTION,
    EDIT_INPUT,
    GLOB_DESCRIPTION,
    GLOB_INPUT,
    GREP_DESCRIPTION,
    GREP_INPUT,
    LS_DESCRIPTION,
    LS_INPUT,
    READ_DESCRIPTION,
    READ_INPUT,
    SHELL_DESCRIPTION,
    SHELL_INPUT,
    WRITE_DESCRIPTION,
    WRITE_INPUT,
)
from mirage.agents.tool_operations import (
    DEFAULT_READ_LIMIT,
    MirageToolOperations,
    ToolResult,
)
from mirage.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

READ_ONLY = ToolAnnotations(read_only_hint=True)

TOOLS = [
    Tool(
        name="shell",
        description=SHELL_DESCRIPTION,
        input_schema=SHELL_INPUT,
    ),
    Tool(
        name="read",
        description=READ_DESCRIPTION,
        annotations=READ_ONLY,
        input_schema=READ_INPUT,
    ),
    Tool(
        name="write",
        description=WRITE_DESCRIPTION,
        input_schema=WRITE_INPUT,
    ),
    Tool(
        name="edit",
        description=EDIT_DESCRIPTION,
        input_schema=EDIT_INPUT,
    ),
    Tool(
        name="ls",
        description=LS_DESCRIPTION,
        annotations=READ_ONLY,
        input_schema=LS_INPUT,
    ),
    Tool(
        name="grep",
        description=GREP_DESCRIPTION,
        annotations=READ_ONLY,
        input_schema=GREP_INPUT,
    ),
    Tool(
        name="glob",
        description=GLOB_DESCRIPTION,
        annotations=READ_ONLY,
        input_schema=GLOB_INPUT,
    ),
]


def _to_mcp(result: ToolResult) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=result.text)],
        is_error=result.is_error,
    )


class MirageMcpServer:
    """Serves one workspace's tools over the MCP protocol.

    The handlers are bound methods handed to the SDK's constructor, so
    the tool table stays readable and nothing nests.

    Args:
        workspace (Workspace): The workspace to serve.
        stale_write_protection (bool): False lets an agent overwrite a
            file that changed since it read it.
        name (str): Server name advertised to the client.
        version (str): Server version advertised to the client.
        session_id (str | None): The session the tools act as; None is
            the workspace's default session.
        operations (MirageToolOperations | None): The tool table to
            serve, built from the workspace and the arguments above when
            None; the daemon passes one that runs each call through its
            API.
    """

    def __init__(
        self,
        workspace: Workspace,
        stale_write_protection: bool = True,
        name: str = "mirage",
        version: str = __version__,
        session_id: str | None = None,
        operations: MirageToolOperations | None = None,
    ) -> None:
        self._ops = (
            operations
            if operations is not None
            else MirageToolOperations(
                workspace, stale_write_protection, session_id
            )
        )
        # The SDK's parameter is the lifespan result. No lifespan is
        # passed, so the default one runs and yields an empty dict.
        self.server: Server[dict[str, Any]] = Server(
            name,
            version=version,
            on_list_tools=self.list_tools,
            on_call_tool=self.call_tool,
        )

    async def list_tools(
        self,
        ctx: ServerRequestContext[dict[str, Any]],
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """Report the tool table.

        Args:
            ctx (ServerRequestContext[dict[str, Any]]): The request
                context; unused.
            params (PaginatedRequestParams | None): The page cursor;
                every tool fits on one page.

        Returns:
            ListToolsResult: Every tool this server serves.
        """
        return ListToolsResult(tools=list(TOOLS))

    async def call_tool(
        self,
        ctx: ServerRequestContext[dict[str, Any]],
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """Run one tool call.

        A tool this server does not serve is a protocol error, as the
        TypeScript twin answers it. Arguments outside the tool's input
        schema and a raised exception are the tool's answer, with
        `is_error` set, so the agent reads them and can retry.

        Args:
            ctx (ServerRequestContext[dict[str, Any]]): The request
                context; unused.
            params (CallToolRequestParams): The tool name and arguments.

        Returns:
            CallToolResult: The tool's answer.

        Raises:
            MCPError: The tool name is not one this server serves.
        """
        tool = next((t for t in TOOLS if t.name == params.name), None)
        if tool is None:
            raise MCPError(INVALID_PARAMS, f"Tool {params.name} not found")
        arguments = params.arguments or {}
        try:
            jsonschema.validate(arguments, tool.input_schema)
        except jsonschema.ValidationError as exc:
            return _to_mcp(
                ToolResult(
                    "Input validation error: Invalid arguments for tool "
                    f"{params.name}: {exc.message}",
                    True,
                )
            )
        try:
            return await self._run(params.name, arguments)
        except Exception as exc:
            logger.debug("mcp tool %s failed", params.name, exc_info=True)
            return _to_mcp(ToolResult(str(exc), True))

    async def _run(
        self, name: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        if name == "shell":
            return _to_mcp(await self._ops.shell(arguments["command"]))
        if name == "read":
            return _to_mcp(
                await self._ops.read(
                    arguments["path"],
                    int(arguments.get("offset", 0)),
                    int(arguments.get("limit", DEFAULT_READ_LIMIT)),
                )
            )
        if name == "write":
            return _to_mcp(
                await self._ops.write(arguments["path"], arguments["content"])
            )
        if name == "edit":
            return _to_mcp(
                await self._ops.edit(
                    arguments["path"],
                    arguments["old_string"],
                    arguments["new_string"],
                    bool(arguments.get("replace_all", False)),
                )
            )
        if name == "ls":
            return _to_mcp(await self._ops.ls(arguments["path"]))
        if name == "grep":
            return _to_mcp(
                await self._ops.grep(arguments["pattern"], arguments["path"])
            )
        if name == "glob":
            return _to_mcp(
                await self._ops.glob(
                    arguments["pattern"], arguments.get("path", "/")
                )
            )
        raise ValueError(f"unknown tool: {name}")
