// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
// ========= Copyright 2026 @ Strukto.AI All Rights Reserved. =========

import { resolveWorkspaceConfig } from '@struktoai/mirage-server/workspace_config'
import type { Command } from 'commander'
import { makeClient } from './client.ts'
import { fail, handleResponse } from './output.ts'
import { loadDaemonSettings } from './settings.ts'

export interface McpConfigResolutionOptions {
  cwd?: string
  env?: Record<string, string | undefined>
}

interface McpCommandOptions {
  workspace?: string
}

export function resolveMcpConfig(
  config: string | undefined,
  options: McpConfigResolutionOptions = {},
): string {
  return resolveWorkspaceConfig(config, {
    ...(options.cwd !== undefined ? { cwd: options.cwd } : {}),
    ...(options.env !== undefined ? { env: options.env } : {}),
    envNames: ['MIRAGE_MCP_CONFIG', 'MIRAGE_CONFIG'],
  })
}

/**
 * Serve a workspace's MCP tools over stdio. The tools are the daemon's:
 * this relays stdio to the workspace's `/v1/workspaces/:id/mcp`
 * endpoint, starting the daemon when it is not running. A workspace
 * loaded from a config lives as long as this process, as a stdio
 * server's state does; one named with `--workspace` is left as it was.
 */
async function runMcp(config: string | undefined, options: McpCommandOptions): Promise<void> {
  if (options.workspace !== undefined && config !== undefined) {
    fail('pass a config or --workspace, not both', 2)
  }
  let path: string | undefined
  if (options.workspace === undefined) {
    try {
      path = resolveMcpConfig(config)
    } catch (error) {
      fail(error instanceof Error ? error.message : String(error), 2)
    }
  }
  const client = makeClient(loadDaemonSettings())
  try {
    await client.ensureRunning({ allowSpawn: true })
  } catch (error) {
    fail(error instanceof Error ? error.message : String(error))
  }
  let workspaceId: string
  if (path !== undefined) {
    const { checkWorkspaceConfigFile } = await import('@struktoai/mirage-node/config')
    const body = JSON.stringify({ config: checkWorkspaceConfigFile(path) })
    const created = await handleResponse(await client.request('POST', '/v1/workspaces', { body }))
    workspaceId = (created as { id: string }).id
  } else {
    workspaceId = options.workspace ?? ''
    await handleResponse(await client.request('GET', `/v1/workspaces/${workspaceId}`))
  }
  const url = `${client.settings.url}/v1/workspaces/${workspaceId}/mcp`
  const token = client.settings.authToken
  const headers: Record<string, string> = token === '' ? {} : { Authorization: `Bearer ${token}` }
  const { relayStdio } = await import('@struktoai/mirage-server/mcp')
  try {
    await relayStdio(url, headers)
  } finally {
    if (path !== undefined) await client.request('DELETE', `/v1/workspaces/${workspaceId}`)
  }
}

export function registerMcpCommand(program: Command): void {
  program
    .command('mcp')
    .argument('[config]', 'Mirage workspace YAML config')
    .option('-w, --workspace <id>', 'Serve this daemon workspace instead of loading a config')
    .description("Serve a Mirage workspace's MCP tools over stdio.")
    .action(runMcp)
}
