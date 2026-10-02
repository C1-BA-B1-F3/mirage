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

import { createMcpHandler, type McpHttpHandler } from '@modelcontextprotocol/server'
import { MirageToolOperations } from '@struktoai/mirage-agents/tool_operations'
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify'
import type { WorkspaceEntry, WorkspaceRegistry } from '../registry.ts'
import { createMirageMcpServer } from './server.ts'

export const MCP_PATH = '/v1/workspaces/:workspaceId/mcp'

/**
 * Serves every workspace's tools over MCP's streamable HTTP.
 *
 * The endpoint is stateless: each request runs in the workspace's default
 * session, or the one `?sessionId=` names, as `/execute` picks its
 * session. One tool table per workspace and session outlives the requests,
 * so the read one request stamps guards the edit the next one makes; the
 * SDK builds a server per request around it.
 */
export class McpDoor {
  private readonly served = new Map<string, { entry: WorkspaceEntry; handler: McpHttpHandler }>()

  constructor(private readonly registry: WorkspaceRegistry) {}

  async handle(
    req: FastifyRequest<{ Params: { workspaceId: string }; Querystring: { sessionId?: string } }>,
    reply: FastifyReply,
  ): Promise<FastifyReply> {
    await this.dropStale()
    const { workspaceId } = req.params
    if (!this.registry.has(workspaceId)) {
      return reply.status(404).send({ detail: 'workspace not found' })
    }
    const entry = this.registry.get(workspaceId)
    const ws = entry.runner.ws
    await ws.ensureSessionsLoaded()
    const sessionId = req.query.sessionId ?? ws.defaultSessionId
    const key = `${workspaceId}\u0000${sessionId}`
    if (!ws.listSessions().some((s) => s.sessionId === sessionId)) {
      await this.forget(key)
      return reply.status(404).send({ detail: 'session not found' })
    }
    let served = this.served.get(key)
    if (served === undefined) {
      const operations = new MirageToolOperations(ws, { sessionId })
      served = {
        entry,
        handler: createMcpHandler(() => createMirageMcpServer(ws, { operations })),
      }
      this.served.set(key, served)
    }
    const headers = new Headers()
    for (const [name, value] of Object.entries(req.headers)) {
      if (value === undefined) continue
      headers.set(name, Array.isArray(value) ? value.join(', ') : value)
    }
    const request = new Request(`http://${req.headers.host ?? 'localhost'}${req.url}`, {
      method: req.method,
      headers,
    })
    const response = await served.handler.fetch(
      request,
      req.body === undefined ? {} : { parsedBody: req.body },
    )
    return reply.send(response)
  }

  /** Close every handler; the app's `onClose` awaits it. */
  async close(): Promise<void> {
    const handlers = [...this.served.values()].map((s) => s.handler)
    this.served.clear()
    await Promise.all(handlers.map((h) => h.close()))
  }

  private async dropStale(): Promise<void> {
    for (const [key, served] of [...this.served]) {
      const id = served.entry.id
      if (!this.registry.has(id) || this.registry.get(id) !== served.entry) {
        await this.forget(key)
      }
    }
  }

  private async forget(key: string): Promise<void> {
    const served = this.served.get(key)
    if (served === undefined) return
    this.served.delete(key)
    await served.handler.close()
  }
}

/**
 * Serve MCP at `/v1/workspaces/:workspaceId/mcp`, behind the app's host
 * check and auth as every other route is.
 */
export function registerMcpRoutes(app: FastifyInstance, registry: WorkspaceRegistry): McpDoor {
  const door = new McpDoor(registry)
  app.route<{ Params: { workspaceId: string }; Querystring: { sessionId?: string } }>({
    method: ['GET', 'POST', 'DELETE'],
    url: MCP_PATH,
    handler: (req, reply) => door.handle(req, reply),
  })
  return door
}
