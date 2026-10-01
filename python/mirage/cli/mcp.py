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
from pathlib import Path

import typer

from mirage.server.workspace_config import (
    build_workspace_from_config,
    resolve_workspace_config,
)

MCP_ENV_NAMES = ("MIRAGE_MCP_CONFIG", "MIRAGE_CONFIG")

app = typer.Typer(
    invoke_without_command=True,
    help="Serve a Mirage workspace as MCP tools over stdio.",
)


def resolve_mcp_config(
    config: str | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Find the config `mirage mcp` should serve.

    Args:
        config (str | None): explicit path, relative to cwd.
        cwd (str | Path | None): directory to resolve from.
        env (dict[str, str] | None): environment mapping to read.

    Returns:
        Path: the resolved config path.
    """
    return resolve_workspace_config(
        config, cwd=cwd, env=env, env_names=MCP_ENV_NAMES
    )


async def run_mcp_server(
    config: str | None, stale_write_protection: bool
) -> None:
    """Build the workspace and serve it until the client disconnects.

    Args:
        config (str | None): explicit config path, or None to discover.
        stale_write_protection (bool): False lets an agent overwrite a
            file that changed since it read it.
    """
    # Imported here, as the TypeScript twin awaits mirage-agents/mcp:
    # every other `mirage` verb would otherwise pay for the agents
    # package and the whole workspace on each spawn.
    from mirage.agents.mcp.server import serve_mirage_mcp

    workspace = await build_workspace_from_config(resolve_mcp_config(config))
    try:
        await serve_mirage_mcp(workspace, stale_write_protection)
    finally:
        await workspace.close()


@app.callback(invoke_without_command=True)
def mcp_cmd(
    config: str | None = typer.Argument(
        None, help="Mirage workspace YAML config."
    ),
    stale_write_protection: bool = typer.Option(
        True,
        "--stale-write-protection/--no-stale-write-protection",
        help="Refuse an edit when the file changed since it was read.",
    ),
) -> None:
    """Serve a Mirage workspace as MCP tools over stdio."""
    try:
        asyncio.run(run_mcp_server(config, stale_write_protection))
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise SystemExit(2) from e
