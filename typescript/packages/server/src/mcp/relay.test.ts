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

import { Client, InMemoryTransport } from '@modelcontextprotocol/client'
import { MountMode } from '@struktoai/mirage-core/types'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { Workspace } from '@struktoai/mirage-node'
import { afterEach, describe, expect, it } from 'vitest'
import { McpRelay } from './relay.ts'
import { createMirageMcpServer } from './server.ts'

const closers: (() => Promise<void>)[] = []

async function linked(server: {
  connect: (t: InMemoryTransport) => Promise<void>
  close: () => Promise<void>
}): Promise<Client> {
  const client = new Client({ name: 'mirage-test', version: '1.0.0' })
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair()
  await server.connect(serverTransport)
  await client.connect(clientTransport)
  closers.push(
    () => client.close(),
    () => server.close(),
  )
  return client
}

async function relayed(): Promise<{ upstream: Client; client: Client }> {
  const ws = new Workspace({ '/': new RAMVFS() }, { mode: MountMode.WRITE })
  const upstream = await linked(createMirageMcpServer(ws))
  const client = await linked(new McpRelay(upstream).server)
  return { upstream, client }
}

function firstText(content: unknown): string {
  return (content as { text?: string }[])[0]?.text ?? ''
}

afterEach(async () => {
  for (const close of closers.splice(0).reverse()) await close()
})

describe('McpRelay', () => {
  it('relays the tool table', async () => {
    const { upstream, client } = await relayed()
    expect(await client.listTools()).toEqual(await upstream.listTools())
  })

  it('relays a tool call', async () => {
    const { client } = await relayed()
    await client.callTool({ name: 'shell', arguments: { command: 'mkdir /d && cd /d' } })
    const result = await client.callTool({ name: 'shell', arguments: { command: 'pwd' } })
    expect(firstText(result.content)).toBe('/d\n')
    expect(result.isError).not.toBe(true)
  })

  it('relays a protocol error', async () => {
    const { client } = await relayed()
    await expect(client.callTool({ name: 'nope', arguments: {} })).rejects.toMatchObject({
      code: -32602,
      message: 'Tool nope not found',
    })
  })
})
