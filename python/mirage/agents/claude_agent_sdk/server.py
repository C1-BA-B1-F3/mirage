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

from typing import Any

try:
    from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool
except ImportError as exc:
    raise ImportError(
        "`claude-agent-sdk` not installed. "
        "Install with: pip install 'mirage-ai[claude-agent-sdk]'"
    ) from exc

from mirage import __version__
from mirage.agents.tool_descriptions import (
    EDIT_DESCRIPTION,
    EXECUTE_DESCRIPTION,
    GREP_DESCRIPTION,
    LS_DESCRIPTION,
    READ_DESCRIPTION,
    WRITE_DESCRIPTION,
)
from mirage.agents.tool_operations import (
    DEFAULT_READ_LIMIT,
    MirageToolOperations,
    ToolResult,
)
from mirage.workspace.workspace import Workspace


def _to_sdk(result: ToolResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": result.text}]
    }
    if result.is_error:
        payload["is_error"] = True
    return payload


class _MirageTools:
    """Unpacks the SDK's argument dicts onto the shared operations.

    Args:
        workspace (Workspace): The workspace to serve.
        stale_write_protection (bool): False lets an agent overwrite a
            file that changed since it read it.
    """

    def __init__(
        self, workspace: Workspace, stale_write_protection: bool = True
    ) -> None:
        self._ops = MirageToolOperations(workspace, stale_write_protection)

    async def execute_command(self, args: dict[str, Any]) -> dict[str, Any]:
        return _to_sdk(await self._ops.execute(args["command"]))

    async def read(self, args: dict[str, Any]) -> dict[str, Any]:
        offset = int(args.get("offset", 0))
        limit = int(args.get("limit", DEFAULT_READ_LIMIT))
        return _to_sdk(await self._ops.read(args["path"], offset, limit))

    async def write(self, args: dict[str, Any]) -> dict[str, Any]:
        return _to_sdk(await self._ops.write(args["path"], args["content"]))

    async def edit(self, args: dict[str, Any]) -> dict[str, Any]:
        replace_all = bool(args.get("replace_all", False))
        return _to_sdk(
            await self._ops.edit(
                args["path"],
                args["old_string"],
                args["new_string"],
                replace_all,
            )
        )

    async def ls(self, args: dict[str, Any]) -> dict[str, Any]:
        return _to_sdk(await self._ops.ls(args["path"]))

    async def grep(self, args: dict[str, Any]) -> dict[str, Any]:
        return _to_sdk(await self._ops.grep(args["pattern"], args["path"]))


def MirageServer(
    workspace: Workspace, stale_write_protection: bool = True
) -> Any:
    """Create an in-process Mirage server for the Claude Agent SDK.

    Args:
        workspace (Workspace): The workspace to serve.
        stale_write_protection (bool): False lets an agent overwrite a
            file that changed since it read it.

    Returns:
        Any: An SDK server object to pass to
            ClaudeAgentOptions(mcp_servers=...).
    """
    tools_impl = _MirageTools(workspace, stale_write_protection)
    return create_sdk_mcp_server(
        name="mirage",
        version=__version__,
        tools=[
            tool("execute_command", EXECUTE_DESCRIPTION, {"command": str})(
                tools_impl.execute_command
            ),
            tool(
                "read",
                READ_DESCRIPTION,
                {"path": str},
                annotations=ToolAnnotations(readOnlyHint=True),
            )(tools_impl.read),
            tool("write", WRITE_DESCRIPTION, {"path": str, "content": str})(
                tools_impl.write
            ),
            tool(
                "edit",
                EDIT_DESCRIPTION,
                {"path": str, "old_string": str, "new_string": str},
            )(tools_impl.edit),
            tool(
                "ls",
                LS_DESCRIPTION,
                {"path": str},
                annotations=ToolAnnotations(readOnlyHint=True),
            )(tools_impl.ls),
            tool(
                "grep",
                GREP_DESCRIPTION,
                {"pattern": str, "path": str},
                annotations=ToolAnnotations(readOnlyHint=True),
            )(tools_impl.grep),
        ],
    )
