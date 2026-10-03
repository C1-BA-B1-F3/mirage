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

import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { createServer, type AddressInfo } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { Client } from '@modelcontextprotocol/client'
import { StdioClientTransport } from '@modelcontextprotocol/client/stdio'
import { afterEach, describe, expect, it } from 'vitest'
import { ENV_AUTH_MODE, ENV_AUTH_TOKEN, ENV_DAEMON_PORT, ENV_DAEMON_URL, ENV_TOKEN } from './env.ts'
import { resolveMcpConfig } from './mcp.ts'

const BIN = join(dirname(fileURLToPath(import.meta.url)), '..', 'dist', 'bin', 'mirage.js')
const tempDirs: string[] = []
const DAEMON = createRequire(import.meta.url).resolve('@struktoai/mirage-server/bin/daemon')
const daemons: ChildProcess[] = []

function mkTempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'mirage-mcp-'))
  tempDirs.push(dir)
  return dir
}

afterEach(async () => {
  for (const child of daemons.splice(0)) {
    const exited = new Promise((resolve) => child.once('exit', resolve))
    child.kill()
    await exited
  }
  for (const dir of tempDirs.splice(0)) rmSync(dir, { recursive: true, force: true })
})

describe('resolveMcpConfig', () => {
  it('uses an explicit config path', () => {
    const dir = mkTempDir()
    const path = join(dir, 'custom.yaml')
    writeFileSync(path, 'mounts: {}\n')
    expect(resolveMcpConfig('custom.yaml', { cwd: dir, env: {} })).toBe(path)
  })

  it('uses MIRAGE_MCP_CONFIG', () => {
    const dir = mkTempDir()
    const path = join(dir, 'env.yaml')
    writeFileSync(path, 'mounts: {}\n')
    expect(resolveMcpConfig(undefined, { cwd: dir, env: { MIRAGE_MCP_CONFIG: path } })).toBe(path)
  })

  it('finds .mirage/workspace.yaml from a child directory', () => {
    const dir = mkTempDir()
    const configDir = join(dir, '.mirage')
    const child = join(dir, 'src', 'nested')
    mkdirSync(configDir)
    mkdirSync(child, { recursive: true })
    const path = join(configDir, 'workspace.yaml')
    writeFileSync(path, 'mounts: {}\n')
    expect(resolveMcpConfig(undefined, { cwd: child, env: {} })).toBe(path)
  })
})

const TOKEN = 'mcp-test-token'
const AUTH = { authorization: `Bearer ${TOKEN}` }
const JSON_AUTH = { ...AUTH, 'content-type': 'application/json' }

interface Daemon {
  url: string
  env: Record<string, string>
}

async function freePort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo
  await new Promise((resolve) => server.close(resolve))
  return port
}

async function daemon(): Promise<Daemon> {
  const port = await freePort()
  const url = `http://127.0.0.1:${String(port)}`
  const env: Record<string, string> = {}
  for (const [k, v] of Object.entries(process.env)) {
    if (typeof v === 'string' && k !== ENV_AUTH_TOKEN && k !== ENV_TOKEN) env[k] = v
  }
  env.MIRAGE_HOME = mkTempDir()
  env[ENV_DAEMON_URL] = url
  env[ENV_DAEMON_PORT] = String(port)
  env[ENV_AUTH_MODE] = 'local'
  env[ENV_AUTH_TOKEN] = TOKEN
  env[ENV_TOKEN] = TOKEN
  const child = spawn(process.execPath, [DAEMON], { env, stdio: 'ignore' })
  daemons.push(child)
  await until(async () => {
    try {
      return (await fetch(`${url}/v1/health`, { headers: AUTH })).status === 200
    } catch {
      return false
    }
  })
  return { url, env }
}

async function relay(d: Daemon, ...args: string[]): Promise<Client> {
  const client = new Client({ name: 'mirage-test', version: '1.0.0' })
  await client.connect(
    new StdioClientTransport({
      command: process.execPath,
      args: [BIN, 'mcp', ...args],
      env: d.env,
    }),
  )
  return client
}

function writeConfig(): string {
  const path = join(mkTempDir(), 'workspace.yaml')
  writeFileSync(path, 'mounts:\n  /:\n    vfs: ram\n    mode: WRITE\n')
  return path
}

function text(content: unknown): string {
  return (content as { text?: string }[])[0]?.text ?? ''
}

async function listWorkspaces(d: Daemon): Promise<unknown[]> {
  return (await (await fetch(`${d.url}/v1/workspaces`, { headers: AUTH })).json()) as unknown[]
}

async function until(check: () => Promise<boolean>): Promise<void> {
  const deadline = Date.now() + 10_000
  while (!(await check())) {
    if (Date.now() > deadline) throw new Error('timed out')
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
}

describe('mirage mcp over stdio', () => {
  it("relays the daemon's tools", async () => {
    const d = await daemon()
    const client = await relay(d, writeConfig())
    try {
      const tools = (await client.listTools()).tools.map((t) => t.name).sort()
      await client.callTool({ name: 'write', arguments: { path: '/a.txt', content: 'hi\n' } })
      const read = await client.callTool({ name: 'read', arguments: { path: '/a.txt' } })
      const ran = await client.callTool({
        name: 'shell',
        arguments: { command: 'wc -l /a.txt' },
      })
      expect(tools).toEqual(['edit', 'glob', 'grep', 'ls', 'read', 'shell', 'write'])
      expect(text(read.content)).toBe('     1\thi\n')
      expect(text(ran.content)).toBe('1 /a.txt\n')
      expect(await listWorkspaces(d)).toHaveLength(1)
    } finally {
      await client.close()
    }
  }, 60_000)

  it('takes a loaded workspace with the process', async () => {
    const d = await daemon()
    const client = await relay(d, writeConfig())
    await client.callTool({ name: 'shell', arguments: { command: 'true' } })
    await client.close()
    await until(async () => (await listWorkspaces(d)).length === 0)
  }, 60_000)

  it('leaves a named workspace', async () => {
    const d = await daemon()
    const created = (await (
      await fetch(`${d.url}/v1/workspaces`, {
        method: 'POST',
        headers: JSON_AUTH,
        body: JSON.stringify({ config: { mounts: { '/': { vfs: 'ram', mode: 'write' } } } }),
      })
    ).json()) as { id: string }
    const client = await relay(d, '-w', created.id)
    await client.callTool({ name: 'write', arguments: { path: '/kept.txt', content: 'x' } })
    await client.close()
    const ran = (await (
      await fetch(`${d.url}/v1/workspaces/${created.id}/execute`, {
        method: 'POST',
        headers: JSON_AUTH,
        body: JSON.stringify({ command: 'cat /kept.txt' }),
      })
    ).json()) as { stdout: string }
    expect(ran.stdout).toBe('x')
  }, 60_000)

  it('takes a config or a workspace, not both', async () => {
    const child = spawn(process.execPath, [BIN, 'mcp', writeConfig(), '-w', 'ws_1'])
    const code = await new Promise<number | null>((resolve) => child.on('close', resolve))
    expect(code).toBe(2)
  })
})
