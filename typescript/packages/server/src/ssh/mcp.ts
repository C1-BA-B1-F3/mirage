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

import { StdioServerTransport } from '@modelcontextprotocol/server/stdio'
import type { ServerChannel } from 'ssh2'
import { createMirageMcpServer } from '../mcp/server.ts'
import type { WorkspaceRegistry } from '../registry.ts'
import { keyProfile, loginEnv, newSessionId, openSession, type ChannelRequest } from './session.ts'

/**
 * Serve one mcp channel: the workspace's tools over MCP's stdio framing.
 *
 * The channel runs as a fresh session under the login key's profile, else
 * the workspace's default, with the environment an `ssh` login gets, and
 * the session closes with the channel.
 */
export async function serveMcp(
  registry: WorkspaceRegistry,
  channel: ServerChannel,
  request: ChannelRequest,
): Promise<void> {
  if (!registry.has(request.username)) {
    channel.stderr.write(`mirage: no such workspace: ${request.username}\n`)
    channel.exit(1)
    channel.end()
    return
  }
  const entry = registry.get(request.username)
  const sessionId = newSessionId()
  try {
    await openSession(entry.runner.ws, sessionId, loginEnv(request), keyProfile(request.profile))
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    console.warn(`mcp: cannot open a session on ${request.username}: ${message}`)
    channel.stderr.write(`mirage: cannot open a session: ${message}\n`)
    channel.exit(1)
    channel.end()
    return
  }
  const ended = new Promise<void>((resolve) => {
    channel.once('end', resolve)
    channel.once('close', resolve)
  })
  const server = createMirageMcpServer(entry.runner.ws, { sessionId })
  await server.connect(new StdioServerTransport(channel, channel))
  await ended
  await server.close()
  if (registry.has(request.username) && registry.get(request.username) === entry) {
    await entry.runner.ws.closeSession(sessionId)
  }
  channel.exit(0)
  channel.end()
}
