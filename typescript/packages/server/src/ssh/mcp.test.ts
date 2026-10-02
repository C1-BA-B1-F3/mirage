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

import { appendFileSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { MountMode } from '@struktoai/mirage-core/types'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { Workspace } from '@struktoai/mirage-node'
import ssh2, { type Client, type ClientChannel } from 'ssh2'
import { afterEach, describe, expect, it } from 'vitest'
import { WorkspaceRegistry, type WorkspaceEntry } from '../registry.ts'
import { MCP_SUBSYSTEM } from './constants.ts'
import { mintKeyPair } from './keys.ts'
import { startSSHServer } from './server.ts'
import type { SSHListener } from './types.ts'

type Message = Record<string, unknown>

interface Harness {
  registry: WorkspaceRegistry
  entry: WorkspaceEntry
  listener: SSHListener
  privateKey: string
  keysFile: string
}

const TIMEOUT = 10_000
const open: Harness[] = []
const clients: Client[] = []

async function startHarness(ws?: Workspace): Promise<Harness> {
  const dir = mkdtempSync(join(tmpdir(), 'mirage-ssh-mcp-'))
  const pair = mintKeyPair(ssh2.utils)
  writeFileSync(join(dir, 'authorized_keys'), `${pair.public}\n`)
  const registry = new WorkspaceRegistry({ idleGraceSeconds: 0 })
  const entry = registry.add(
    ws ?? new Workspace({ '/': new RAMVFS() }, { mode: MountMode.WRITE }),
    'demo',
  )
  const listener = await startSSHServer(registry, {
    port: 0,
    host: '127.0.0.1',
    hostKeyFile: join(dir, 'host_key'),
    authorizedKeysFile: join(dir, 'authorized_keys'),
  })
  const harness = {
    registry,
    entry,
    listener,
    privateKey: pair.private,
    keysFile: join(dir, 'authorized_keys'),
  }
  open.push(harness)
  return harness
}

function connect(h: Harness, username = 'demo', privateKey = h.privateKey): Promise<Client> {
  return new Promise((resolve, reject) => {
    const client = new ssh2.Client()
    clients.push(client)
    client.on('ready', () => {
      resolve(client)
    })
    client.on('error', reject)
    client.connect({ host: '127.0.0.1', port: h.listener.port, username, privateKey })
  })
}

/** Authorize a fresh client key whose line carries `options`. */
function bindKey(h: Harness, options: string): string {
  const pair = mintKeyPair(ssh2.utils)
  appendFileSync(h.keysFile, `${options} ${pair.public}\n`)
  return pair.private
}

/** A workspace whose `guarded` profile seals `/vault`. */
async function vaultWorkspace(): Promise<Workspace> {
  const ws = new Workspace(
    { '/': new RAMVFS() },
    {
      mode: MountMode.WRITE,
      profiles: {
        guarded: { commands: { deny: [{ reason: 'the vault is sealed', paths: ['/vault/*'] }] } },
      },
    },
  )
  await ws.shell('mkdir -p /vault && echo token > /vault/secret')
  return ws
}

function subsystem(client: Client, name: string): Promise<ClientChannel> {
  return new Promise((resolve, reject) => {
    client.subsys(name, (err, stream) => {
      if (err !== undefined) reject(err)
      else resolve(stream)
    })
  })
}

/** Speaks MCP's stdio framing over an `mcp` subsystem channel. */
class McpChannel {
  private buffer = ''
  private readonly lines: string[] = []
  private waiter: (() => void) | null = null
  private nextId = 0

  constructor(readonly channel: ClientChannel) {
    channel.on('data', (chunk: Buffer) => {
      this.buffer += chunk.toString('utf8')
      let cut = this.buffer.indexOf('\n')
      while (cut >= 0) {
        this.lines.push(this.buffer.slice(0, cut))
        this.buffer = this.buffer.slice(cut + 1)
        cut = this.buffer.indexOf('\n')
      }
      this.waiter?.()
    })
  }

  private async line(): Promise<string> {
    const deadline = Date.now() + TIMEOUT
    while (this.lines.length === 0) {
      if (Date.now() > deadline) throw new Error('no reply')
      await new Promise<void>((resolve) => {
        this.waiter = resolve
        setTimeout(resolve, 50)
      })
    }
    return this.lines.shift() ?? ''
  }

  async request(method: string, params: Message): Promise<Message> {
    this.nextId += 1
    const id = this.nextId
    this.channel.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
    for (;;) {
      const reply = JSON.parse(await this.line()) as Message
      if (reply.id === id) return reply
    }
  }

  async call(name: string, args: Message): Promise<{ text: string; isError: boolean }> {
    const reply = await this.request('tools/call', { name, arguments: args })
    const result = reply.result as { content: { text: string }[]; isError?: boolean }
    return { text: result.content[0]?.text ?? '', isError: result.isError === true }
  }
}

async function mcp(h: Harness, privateKey?: string): Promise<McpChannel> {
  const channel = new McpChannel(
    await subsystem(await connect(h, 'demo', privateKey), MCP_SUBSYSTEM),
  )
  await channel.request('initialize', {
    protocolVersion: '2025-06-18',
    capabilities: {},
    clientInfo: { name: 'test', version: '1' },
  })
  channel.channel.write(
    JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n',
  )
  return channel
}

function closed(channel: ClientChannel): Promise<void> {
  return new Promise((resolve) =>
    channel.once('close', () => {
      resolve()
    }),
  )
}

afterEach(async () => {
  for (const client of clients.splice(0)) client.end()
  for (const h of open.splice(0)) {
    await h.listener.close()
    await h.registry.closeAll()
  }
})

describe('the mcp subsystem', () => {
  it('serves the six tools', async () => {
    const channel = await mcp(await startHarness())
    const listed = await channel.request('tools/list', {})
    const written = await channel.call('write', { path: '/a.txt', content: 'hi\n' })
    const read = await channel.call('read', { path: '/a.txt' })
    const tools = (listed.result as { tools: { name: string }[] }).tools.map((t) => t.name)
    expect(tools.sort()).toEqual(['edit', 'execute_command', 'grep', 'ls', 'read', 'write'])
    expect(written.isError).toBe(false)
    expect(read.text).toBe('     1\thi\n')
  })

  it('runs the channel as one session', async () => {
    const channel = await mcp(await startHarness())
    await channel.call('execute_command', { command: 'mkdir /d && cd /d' })
    expect((await channel.call('execute_command', { command: 'pwd' })).text).toBe('/d\n')
  })

  it('runs the tools under the key profile', async () => {
    const h = await startHarness(await vaultWorkspace())
    const guarded = bindKey(h, 'mirage-profile="guarded"')
    const opened = await (await mcp(h)).call('read', { path: '/vault/secret' })
    const channel = await mcp(h, guarded)
    const refused = await channel.call('read', { path: '/vault/secret' })
    const shell = await channel.call('execute_command', { command: 'cat /vault/secret' })
    expect(opened.text).toBe('     1\ttoken\n')
    expect(refused.isError).toBe(true)
    expect(shell.isError).toBe(true)
  })

  it('closes the session with the channel', async () => {
    const h = await startHarness()
    const channel = await mcp(h)
    await channel.call('execute_command', { command: 'true' })
    const done = closed(channel.channel)
    channel.channel.end()
    await done
    await new Promise((resolve) => setTimeout(resolve, 200))
    const ids = h.entry.runner.ws.listSessions().map((s) => s.sessionId)
    expect(ids.filter((id) => id.startsWith('ssh_'))).toEqual([])
  })

  it('rejects an unknown tool as a protocol error', async () => {
    const channel = await mcp(await startHarness())
    const reply = await channel.request('tools/call', { name: 'nope', arguments: {} })
    expect(reply.error).toMatchObject({ code: -32602, message: 'Tool nope not found' })
  })

  it('refuses an unknown workspace', async () => {
    const client = await connect(await startHarness(), 'nope')
    const run = await new Promise<{ stderr: string; code: number | null }>((resolve, reject) => {
      client.subsys(MCP_SUBSYSTEM, (err, stream) => {
        if (err !== undefined) {
          reject(err)
          return
        }
        const got = { stderr: '', code: null as number | null }
        stream.resume()
        stream.stderr.on('data', (d: Buffer) => {
          got.stderr += d.toString()
        })
        stream.on('exit', (code: number | null) => {
          got.code = code
        })
        stream.on('close', () => {
          resolve(got)
        })
      })
    })
    expect(run).toEqual({ stderr: 'mirage: no such workspace: nope\n', code: 1 })
  })
})
