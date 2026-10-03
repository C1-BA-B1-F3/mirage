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

from mirage.cli.client import DaemonUnreachable, make_client
from mirage.cli.output import fail, handle_response
from mirage.cli.workspace import resolve_config
from mirage.server.workspace_config import resolve_workspace_config

MCP_ENV_NAMES = ("MIRAGE_MCP_CONFIG", "MIRAGE_CONFIG")

app = typer.Typer(
    invoke_without_command=True,
    help="Serve a Mirage workspace's MCP tools over stdio.",
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


@app.callback(invoke_without_command=True)
def mcp_cmd(
    config: str | None = typer.Argument(
        None, help="Mirage workspace YAML config."
    ),
    workspace_id: str | None = typer.Option(
        None,
        "--workspace",
        "-w",
        help="Serve this daemon workspace instead of loading a config.",
    ),
) -> None:
    """Serve a Mirage workspace's MCP tools over stdio.

    The tools are the daemon's: this relays stdio to the workspace's
    ``/v1/workspaces/{id}/mcp`` endpoint, starting the daemon when it is
    not running. A workspace loaded from a config lives as long as this
    process, as a stdio server's state does; one named with
    ``--workspace`` is left as it was.
    """
    if workspace_id is not None and config is not None:
        fail("pass a config or --workspace, not both", exit_code=2)
    try:
        path = None if workspace_id is not None else resolve_mcp_config(config)
    except FileNotFoundError as e:
        fail(str(e), exit_code=2)
    with make_client() as client:
        try:
            client.ensure_running()
        except DaemonUnreachable as e:
            fail(str(e))
        if path is not None:
            body = {"config": resolve_config(path)}
            created = handle_response(
                client.request("POST", "/v1/workspaces", json=body)
            )
            if not isinstance(created, dict):
                fail(f"unexpected daemon response: {created!r}")
            workspace_id = str(created["id"])
        else:
            handle_response(
                client.request("GET", f"/v1/workspaces/{workspace_id}")
            )
        url = f"{client.settings.url}/v1/workspaces/{workspace_id}/mcp"
        token = client.settings.auth_token
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # Imported here, as the TypeScript twin awaits mirage-server/mcp:
    # every other `mirage` verb would otherwise pay for the MCP SDK on
    # each spawn.
    from mirage.server.mcp.relay import relay_stdio

    try:
        asyncio.run(relay_stdio(url, headers))
    finally:
        if path is not None:
            with make_client() as client:
                client.request("DELETE", f"/v1/workspaces/{workspace_id}")
