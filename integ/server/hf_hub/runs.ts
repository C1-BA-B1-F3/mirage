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

import assert from 'node:assert/strict'
import { start } from '../kit/typescript/serve.ts'
import type { C } from './config.ts'
import { hfHubFake } from './fake.ts'
import { listenMcp, mcpServerFor } from './mcp.ts'

function signal(): { promise: Promise<void>; resolve: () => void } {
  let resolve = (): void => {
    throw new Error('signal not initialized')
  }
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

export async function testMcpRuns(): Promise<void> {
  const seedEntered = signal()
  const seedRelease = signal()
  const epoch = '2026-02-03T00:00:00Z'
  const routedRuns: string[] = []
  const rest = await start<C>({
    ...hfHubFake,
    config: { ...hfHubFake.config, runTokenPattern: '^draw:(?<run>[^:]+):(?<tenant>[^:]+)$' },
    routes: () =>
      hfHubFake.routes().map((spec) =>
        spec.path === '/api/whoami-v2'
          ? {
              ...spec,
              write: true,
              handler: (ctx) => {
                routedRuns.push(ctx.run)
                return spec.handler(ctx)
              },
            }
          : spec,
      ),
    afterSeed: async (...args) => {
      if (args[5] === epoch) {
        seedEntered.resolve()
        await seedRelease.promise
      }
      await hfHubFake.afterSeed?.(...args)
    },
  })
  const server = mcpServerFor(rest.runtime)
  const port = await listenMcp(server, 0)
  const headers = {
    Authorization: 'Bearer draw:race:integ',
    'Content-Type': 'application/json',
    Accept: 'application/json, text/event-stream',
  }
  try {
    const resetting = rest.runtime.reset({ run: 'race', tenants: ['integ'], epoch })
    await seedEntered.promise
    const arrived = signal()
    server.once('request', () => arrived.resolve())
    const listing = fetch(`http://127.0.0.1:${port}/mcp`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
    })
    await arrived.promise
    try {
      assert(!rest.runtime.pool.has('race'), 'MCP must not create a client during a seed')
    } finally {
      seedRelease.resolve()
    }
    await resetting
    const tools = await listing
    assert.equal(tools.status, 200)
    await tools.text()
    const models = await fetch(`${rest.endpoint}/api/models?author=integ`, { headers })
    assert.equal(((await models.json()) as unknown[]).length, 3)

    const blocked = signal()
    const writeEntered = signal()
    const writing = rest.runtime.router.enqueue('race', async () => {
      writeEntered.resolve()
      await blocked.promise
    })
    await writeEntered.promise
    const calling = fetch(`http://127.0.0.1:${port}/mcp`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/call',
        params: { name: 'hf_whoami', arguments: {} },
      }),
    })
    // A different run continues while race is waiting.
    await rest.runtime.reset({ run: 'other', tenants: ['integ'] })
    blocked.resolve()
    await writing
    const answer = await calling
    assert.equal(answer.status, 200)
    const text = await answer.text()
    assert(text.includes('@integ'))
    assert.deepEqual(routedRuns, ['race'], 'MCP uses the runtime router and the resolved run')
    assert(!text.includes('draw:race'))
    await rest.runtime.drop('race')
    await rest.runtime.reset({ run: 'race', tenants: ['integ'] })
    assert.equal(
      await rest.runtime.pool
        .client('race')
        .hfRepo.count({ where: { tenant: 'integ', kind: 'models' } }),
      3,
    )
    process.stdout.write('hf-hub run/reset regressions passed\n')
  } finally {
    seedRelease.resolve()
    await new Promise<void>((resolve, reject) => {
      server.close((err) => (err ? reject(err) : resolve()))
      server.closeAllConnections()
    })
    await rest.close()
  }
}
