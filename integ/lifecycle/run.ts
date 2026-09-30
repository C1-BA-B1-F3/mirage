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

import { isDeepStrictEqual } from 'node:util'
import { readFileSync } from 'node:fs'
import { setFlagsFromString } from 'node:v8'
import { runInNewContext } from 'node:vm'
import {
  Workspace as NodeWorkspace,
  buildVfs as buildNodeVfs,
  registerVfsFactory as registerNodeVfs,
} from '@struktoai/mirage-node'
import {
  Workspace as BrowserWorkspace,
  buildVfs as buildBrowserVfs,
  registerVfsFactory as registerBrowserVfs,
} from '@struktoai/mirage-browser'
import { MountMode } from '@struktoai/mirage-core/types'
import type { BaseVFS } from '@struktoai/mirage-core/vfs/base'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import type {
  Workspace,
  WorkspaceOptions,
} from '@struktoai/mirage-core/workspace/workspace/workspace'
import { parseSessionProfile } from '@struktoai/mirage-core/policy/profile'
import { parseCommandLimits } from '@struktoai/mirage-core/policy/builtin/output_cap'
import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'
import type { ReadStream } from '@struktoai/mirage-core/io/read_stream'
import { classify } from '@struktoai/mirage-core/errors/classify'
import { ScriptSource } from '@struktoai/mirage-core/runtime/routing/types'
import type { Policy } from '@struktoai/mirage-core/policy/base'
import { CLISpec } from '@struktoai/mirage-core/commands/cli/types'
import { runWithSession } from '@struktoai/mirage-core/context/session_context'
import { applyStateDict, toStateDict } from '@struktoai/mirage-core/workspace/snapshot/state'
import type { WorkspaceStateDict } from '@struktoai/mirage-core/workspace/snapshot/types'

interface ResourceConfig {
  vfs: string
  config?: Record<string, unknown>
}

interface Case {
  id: string
  settings: {
    mounts: Record<string, ResourceConfig>
    mode: MountMode
    profiles?: Record<string, unknown>
    runtimes?: string[]
  }
  steps: Step[]
}

type Step = (
  | ({
      op: 'mount'
      path: string
      mode?: MountMode
      command_limits?: Record<string, unknown>
    } & ResourceConfig)
  | { op: 'unmount'; path: string; within?: number }
  | { op: 'read' | 'readdir' | 'stat' | 'cached' | 'records'; path: string }
  | {
      op: 'read_stream'
      path: string
      take?: number
      raw?: boolean
      close?: boolean
      hold?: string
    }
  | { op: 'drop'; id: string }
  | { op: 'write'; path: string; data: string }
  | { op: 'exec'; command: string; session?: string }
  | { op: 'spawn'; argv: string[]; session?: string }
  | { op: 'set_mode'; path: string; mode: MountMode }
  | { op: 'session'; id: string; profile?: Record<string, unknown> }
  | { op: 'close_session'; id: string }
  | { op: 'set_profile'; session?: string; profile: Record<string, unknown> | string | null }
  | {
      op: 'register_cli'
      name: string
      script: ScriptDocument
      runtime?: string
      config?: Record<string, unknown>
    }
  | { op: 'unregister_cli' | 'add_runtime'; name: string }
  | {
      op: 'register_policy'
      id: string
      commands?: string[]
      paths?: string[]
      vars?: string[]
      reason: string
    }
  | { op: 'unregister_policy'; id: string }
  | { op: 'mounts' | 'clis' | 'close' | 'snapshot' | 'checkout' | 'drain_processes' }
  | { op: 'concurrent'; steps: Step[] }
) & { expect?: Record<string, unknown>; session?: string }

interface ScriptDocument {
  source: string
  language: 'python' | 'js'
}

function profileDocument(raw: Record<string, unknown>) {
  const doc = { ...raw }
  if (doc.policy != null) {
    const policy = doc.policy as { script: ScriptDocument; runtime: string }
    doc.policy = {
      ...policy,
      script: new ScriptSource(policy.script.source, policy.script.language),
    }
  }
  return parseSessionProfile(doc)
}

interface Host {
  name: string
  workspace: new (mounts: Record<string, BaseVFS>, options: WorkspaceOptions) => Workspace
  build: (name: string, config: Record<string, unknown>) => Promise<BaseVFS>
}

const HOSTS: Host[] = [
  { name: 'node', workspace: NodeWorkspace, build: buildNodeVfs },
  { name: 'browser', workspace: BrowserWorkspace, build: buildBrowserVfs },
]
const ENC = new TextEncoder()
const DEC = new TextDecoder()
const SESSION_OPS = new Set<string>(['read', 'read_stream', 'write', 'readdir', 'stat'])

/** Seed a RAM fixture with the text files its JSON config names. */
function loadFiles<T extends RAMVFS>(vfs: T, config: Record<string, unknown>): Promise<T> {
  const files = (config.files ?? {}) as Record<string, string>
  vfs.loadState({
    type: 'ram',
    files: Object.fromEntries(
      Object.entries(files).map(([path, data]) => [path, ENC.encode(data)]),
    ),
  })
  return Promise.resolve(vfs)
}

class CachedRAMVFS extends RAMVFS {
  override readonly cachesReads = true
}

type StreamFn = NonNullable<RegisteredOp['stream']>

/** Split a streamed read into one chunk per line, `pause` seconds apart. */
function byLine(stream: StreamFn, pause: number): StreamFn {
  return async function* (accessor, path, args, kwargs) {
    let sent = 0
    for await (const chunk of stream(accessor, path, args, kwargs) as AsyncIterable<Uint8Array>) {
      let start = 0
      while (start < chunk.byteLength) {
        const newline = chunk.indexOf(0x0a, start)
        const end = newline < 0 ? chunk.byteLength : newline + 1
        if (sent > 0 && pause > 0) {
          await new Promise((resolve) => setTimeout(resolve, pause * 1000))
        }
        sent++
        yield chunk.subarray(start, end)
        start = end
      }
    }
  }
}

// A RAM fixture whose streamed read yields one chunk per line, so chunk
// boundaries are the same on every host, which a disk mount's read size
// is not; `pause` delays every chunk after the first, a backend slow to
// deliver the rest.
class ChunkedRAMVFS extends RAMVFS {
  constructor(private readonly pause: number) {
    super()
  }

  override ops(): readonly RegisteredOp[] {
    return super
      .ops()
      .map((ro) =>
        ro.name === 'read' && ro.stream !== undefined
          ? { ...ro, stream: byLine(ro.stream, this.pause) }
          : ro,
      )
  }
}

// A chunked fixture behind the read cache: a cold stream arrives one line
// per chunk and a warm one in the single chunk the cache answers with, so
// the two are told apart.
class CachedChunkedRAMVFS extends ChunkedRAMVFS {
  override readonly cachesReads = true
}

// Register a fixture through the same factory extension point as an embedder.
for (const register of [registerNodeVfs, registerBrowserVfs]) {
  register('cached-ram', (config) => loadFiles(new CachedRAMVFS(), config))
  register('chunked-ram', (config) =>
    loadFiles(new ChunkedRAMVFS((config.pause ?? 0) as number), config),
  )
  register('cached-chunked-ram', (config) =>
    loadFiles(new CachedChunkedRAMVFS((config.pause ?? 0) as number), config),
  )
}

/** The host's collector when node lets one be exposed, as Python's `gc.collect`. */
function exposedGc(): (() => void) | undefined {
  const own = (globalThis as { gc?: () => void }).gc
  if (own !== undefined) return own
  // The flag is process-wide and stays on: resetting it could race another
  // worker's lookup, and a runtime that refuses it just skips the GC cases.
  try {
    setFlagsFromString('--expose-gc')
    const gc: unknown = runInNewContext('typeof gc === "function" ? gc : undefined')
    return typeof gc === 'function' ? (gc as () => void) : undefined
  } catch {
    return undefined
  }
}

const collect = exposedGc()

// What earlier steps put aside for later ones: `snapshot` stores the
// state dict `checkout` applies, and `read_stream` keeps a stream under
// its `hold` id until `drop` lets it go.
interface Held {
  state?: WorkspaceStateDict
  streams: Map<string, ReadStream>
}

const CLOSE_WITHIN = 60

async function finishWithin(work: Promise<unknown>, seconds: number, what: string): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const deadline = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      reject(new Error(`${what} did not finish within ${String(seconds)}s`))
    }, seconds * 1000)
  })
  try {
    await Promise.race([work, deadline])
  } finally {
    clearTimeout(timer)
  }
}

// Hands back when the held stream settles and forgets it, all without a
// local that would keep it reachable from the caller's frame.
function letGo(held: Held, id: string): Promise<unknown> {
  const stream = held.streams.get(id)
  if (stream === undefined) throw new Error(`no held stream: ${id}`)
  held.streams.delete(id)
  return new Promise((resolve) => {
    void stream.onSettle(resolve)
  })
}

async function settledOnceCollected(settled: Promise<unknown>): Promise<void> {
  let done = false
  void settled.then(() => {
    done = true
  })
  for (let round = 0; round < 100 && !done; round++) {
    if (collect === undefined) throw new Error('dropping a stream needs a gc the runtime exposes')
    collect()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  if (!done) throw new Error('a dropped stream did not settle')
}

async function action(
  host: Host,
  ws: Workspace,
  step: Step,
  policies: Map<string, Policy>,
  held: Held,
): Promise<unknown> {
  if (SESSION_OPS.has(step.op) && step.session !== undefined) {
    const { session, ...unbound } = step
    return runWithSession(ws.getSession(session), () => action(host, ws, unbound, policies, held))
  }
  switch (step.op) {
    case 'cached': {
      const value = await ws.cache.get(step.path)
      return value === null ? null : DEC.decode(value)
    }
    case 'mount': {
      const vfs = await host.build(step.vfs, step.config ?? {})
      let entry
      try {
        entry = ws.addMount(step.path, vfs, step.mode ?? MountMode.READ)
      } catch (err) {
        await vfs.close()
        throw err
      }
      for (const [name, limit] of Object.entries(parseCommandLimits(step.command_limits))) {
        entry.commandLimits.set(name, limit)
      }
      return entry.prefix
    }
    case 'unmount': {
      const within = step.within
      if (within === undefined) await ws.unmount(step.path)
      else await finishWithin(ws.unmount(step.path), within, `unmount ${step.path}`)
      break
    }
    case 'set_mode':
      ws.setMountMode(step.path, step.mode)
      break
    case 'session':
      ws.createSession(step.id, { profile: profileDocument(step.profile ?? {}) })
      break
    case 'close_session':
      await ws.closeSession(step.id)
      break
    case 'set_profile':
      await ws.setSessionProfile(
        step.session ?? ws.defaultSessionId,
        typeof step.profile === 'object' && step.profile !== null
          ? profileDocument(step.profile)
          : step.profile,
      )
      break
    case 'register_cli':
      ws.registerCli(
        step.name,
        new CLISpec({
          name: step.name,
          script: new ScriptSource(step.script.source, step.script.language),
          ...(step.runtime !== undefined ? { runtime: step.runtime } : {}),
        }),
        step.config ?? null,
      )
      break
    case 'unregister_cli':
      ws.unregisterCli(step.name)
      break
    case 'clis':
      return [...ws.clis().keys()].sort()
    case 'add_runtime':
      return ws.addRuntime(step.name).name
    case 'register_policy': {
      if (policies.has(step.id)) throw new Error('policy already registered')
      const policy: Policy = {
        preCommand: (ctx) =>
          step.commands?.includes(ctx.command) ? { kind: 'deny', reason: step.reason } : null,
        preOps: (ctx) =>
          step.paths?.includes(ctx.path.virtual) ? { kind: 'deny', reason: step.reason } : null,
        preSession: (ctx) =>
          step.vars?.includes(ctx.key) ? { kind: 'deny', reason: step.reason } : null,
      }
      ws.policies.add(policy)
      policies.set(step.id, policy)
      break
    }
    case 'unregister_policy': {
      const policy = policies.get(step.id)
      if (policy === undefined) return false
      policies.delete(step.id)
      return ws.policies.remove(policy)
    }
    case 'write':
      await ws.vfs.writeFile(step.path, ENC.encode(step.data))
      break
    case 'read':
      return DEC.decode(await ws.vfs.readFile(step.path))
    case 'read_stream': {
      if (step.take === 0 && step.close === false) {
        throw new Error('take 0 with close false pulls nothing: hold the stream and drop it')
      }
      const stream = await ws.vfs.readStream(step.path, { raw: step.raw ?? false })
      const decoder = new TextDecoder()
      let text = ''
      if (step.close ?? true) {
        try {
          for (let pulled = 0; step.take === undefined || pulled < step.take; pulled++) {
            const next = await stream.next()
            if (next.done === true) break
            text += decoder.decode(next.value, { stream: true })
          }
        } finally {
          await stream.return()
        }
      } else {
        // No explicit close: a `break` out of `for await` is what closes
        // it, as Python's `async for` leaves it to collection.
        let pulled = 0
        for await (const chunk of stream) {
          text += decoder.decode(chunk, { stream: true })
          if (++pulled === step.take) break
        }
      }
      if (step.hold !== undefined) held.streams.set(step.hold, stream)
      return text + decoder.decode()
    }
    case 'drop':
      await settledOnceCollected(letGo(held, step.id))
      break
    case 'records':
      return ws.vfs.records.filter((r) => r.path === step.path).map((r) => [r.op, r.bytes])
    case 'readdir':
      return (await ws.vfs.readdir(step.path)).sort()
    case 'stat': {
      const row = await ws.vfs.stat(step.path)
      return { type: row.type, size: row.size }
    }
    case 'drain_processes':
      await ws.processes.drain()
      break
    case 'spawn': {
      const child = ws.spawn({ argv: step.argv }, step.session)
      child.stdin.close()
      return child.pid
    }
    case 'exec': {
      const result = await ws.shell(
        step.command,
        step.session === undefined ? {} : { sessionId: step.session },
      )
      return {
        exit_code: result.exitCode,
        stdout: result.stdoutText,
        stderr: result.stderrText,
        refusal: result.refusal?.reason ?? null,
      }
    }
    case 'concurrent':
      return Promise.all(step.steps.map((sub) => action(host, ws, sub, policies, held)))
    case 'snapshot':
      held.state = await toStateDict(ws)
      break
    case 'checkout': {
      // A checkout onto the running workspace: the restored state wins,
      // and every restored variable clears the session gate first.
      if (held.state === undefined) throw new Error('checkout before snapshot')
      await applyStateDict(ws, held.state)
      break
    }
    case 'mounts':
      return ws
        .mounts()
        .map((m) => m.prefix)
        .sort()
    case 'close':
      await ws.close()
      break
    default:
      throw new Error(`unknown lifecycle action: ${String((step as { op: string }).op)}`)
  }
  return null
}

async function run(host: Host, testCase: Case): Promise<number> {
  const mounts: Record<string, BaseVFS> = {}
  for (const [prefix, config] of Object.entries(testCase.settings.mounts)) {
    mounts[prefix] = await host.build(config.vfs, config.config ?? {})
  }
  const profiles = Object.fromEntries(
    Object.entries(testCase.settings.profiles ?? {}).map(([name, profile]) => [
      name,
      parseSessionProfile(profile),
    ]),
  )
  const ws = new host.workspace(mounts, {
    mode: testCase.settings.mode,
    profiles,
    ...(testCase.settings.runtimes !== undefined ? { runtimes: testCase.settings.runtimes } : {}),
  })
  const policies = new Map<string, Policy>()
  const held: Held = { streams: new Map() }
  try {
    for (const [index, step] of testCase.steps.entries()) {
      let actual: Record<string, unknown>
      try {
        actual = { value: await action(host, ws, step, policies, held) }
      } catch (err) {
        actual = { error: err instanceof Error ? err.message : String(err) }
        const condition = classify(err)
        if (condition !== null) actual.errno = condition
      }
      const expected = step.expect ?? { value: null }
      if (!matches(actual, expected)) {
        throw new Error(
          `step ${index + 1} (${step.op}): expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
        )
      }
    }
    return testCase.steps.length
  } finally {
    // A mount that never goes idle would hold close forever; the case
    // fails instead of hanging the battery.
    await finishWithin(ws.close(), CLOSE_WITHIN, 'close')
  }
}

function matches(actual: unknown, expected: unknown): boolean {
  if (Array.isArray(expected)) {
    return (
      Array.isArray(actual) &&
      actual.length === expected.length &&
      expected.every((want, at) => matches(actual[at], want))
    )
  }
  if (expected === null || typeof expected !== 'object') {
    return isDeepStrictEqual(actual, expected)
  }
  if (actual === null || typeof actual !== 'object') return false
  const fields = actual as Record<string, unknown>
  return Object.entries(expected).every(([key, want]) => {
    const field = key.replace(/_contains$/, '')
    if (!(field in fields)) return false
    const got = fields[field]
    return key === 'error' || key.endsWith('_contains')
      ? typeof got === 'string' && typeof want === 'string' && got.includes(want)
      : matches(got, want)
  })
}

const suite = JSON.parse(readFileSync(new URL('./cases.json', import.meta.url), 'utf8')) as {
  cases: Case[]
}
let passed = 0
let steps = 0
let failures = 0
for (const host of HOSTS) {
  for (const testCase of suite.cases) {
    try {
      steps += await run(host, testCase)
      passed++
      console.log(`ok ${host.name}/${testCase.id}`)
    } catch (err) {
      failures++
      console.error(`FAIL ${host.name}/${testCase.id}: ${String(err)}`)
    }
  }
}
console.log(`${passed} cases / ${steps} steps passed, ${failures} failed`)
process.exitCode = failures > 0 ? 1 : 0
