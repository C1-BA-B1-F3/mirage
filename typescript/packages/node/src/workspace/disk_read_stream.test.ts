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

import type * as fs from 'node:fs'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { setFlagsFromString } from 'node:v8'
import { runInNewContext } from 'node:vm'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReadStream } from '@struktoai/mirage-core/io/read_stream'
import { OpReport } from '@struktoai/mirage-core/io/types'
import type { RegisteredOp } from '@struktoai/mirage-core/ops/registry'
import { MountMode, PathSpec } from '@struktoai/mirage-core/types'
import type { Dispatcher } from '@struktoai/mirage-core/workspace/dispatcher/dispatcher'
import { DiskVFS } from '../vfs/disk/disk.ts'
import { Workspace } from '../workspace.ts'

const files = vi.hoisted(() => ({ opened: [] as fs.ReadStream[] }))

vi.mock('node:fs', async (importOriginal) => {
  const actual = await importOriginal<typeof fs>()
  return {
    ...actual,
    createReadStream: (...args: Parameters<typeof actual.createReadStream>) => {
      const stream = actual.createReadStream(...args)
      files.opened.push(stream)
      return stream
    },
  }
})

const CHUNK = 64 * 1024
const MIB = 1024 * 1024

interface Pulls {
  opened: number
  pulls: number
  closed: boolean
}

type StreamForm = NonNullable<RegisteredOp['stream']>

function pattern(size: number): Uint8Array {
  return Uint8Array.from({ length: size }, (_, i) => i % 251)
}

function doorOf(ws: Workspace): Dispatcher {
  return (ws as unknown as { dispatcher: Dispatcher }).dispatcher
}

function spyReads(ws: Workspace): Pulls {
  const original = ws.opsRegistry.find('read', 'disk')
  const inner: StreamForm | undefined = original?.stream
  if (original === null || inner === undefined) throw new Error('disk read has no stream form')
  const pulls: Pulls = { opened: 0, pulls: 0, closed: false }
  ws.opsRegistry.register({
    ...original,
    stream: (accessor, p, args, kwargs) => {
      pulls.opened++
      const source = inner(accessor, p, args, kwargs) as AsyncIterable<Uint8Array>
      return (async function* (): AsyncGenerator<Uint8Array> {
        try {
          for await (const chunk of source) {
            pulls.pulls++
            yield chunk
          }
        } finally {
          pulls.closed = true
        }
      })()
    },
  })
  return pulls
}

async function openReported(ws: Workspace, virtual: string, report: OpReport): Promise<ReadStream> {
  const [stream] = (await doorOf(ws).dispatch(
    'read',
    PathSpec.fromStrPath(virtual),
    [],
    { stream: true },
    report,
  )) as [ReadStream, unknown]
  expect(stream).toBeInstanceOf(ReadStream)
  return stream
}

async function settlesWithin(promise: Promise<unknown>, ms: number): Promise<boolean> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const late = new Promise<boolean>((resolve) => {
    timer = setTimeout(() => {
      resolve(false)
    }, ms)
  })
  try {
    return await Promise.race([promise.then(() => true), late])
  } finally {
    clearTimeout(timer)
  }
}

// A read stream closed before its end is destroyed with an AbortError,
// which `events.once` would reject on; only the close matters here.
async function fileClosed(stream: fs.ReadStream | undefined): Promise<boolean> {
  if (stream === undefined) return false
  if (stream.closed) return true
  const closing = new Promise<void>((resolve) => {
    stream.once('close', () => {
      resolve()
    })
  })
  return settlesWithin(closing, 2000)
}

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

const collectGarbage = exposedGc()

async function collectedWithin(settled: () => boolean, rounds = 50): Promise<boolean> {
  for (let i = 0; i < rounds && !settled(); i++) {
    collectGarbage?.()
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  return settled()
}

describe('a streamed disk read through the door', () => {
  let root: string
  let ws: Workspace

  beforeEach(async () => {
    files.opened.length = 0
    root = await mkdtemp(path.join(tmpdir(), 'mirage-read-stream-'))
    await writeFile(path.join(root, 'huge.bin'), pattern(MIB))
    ws = new Workspace({ '/disk': new DiskVFS({ root }) }, { mode: MountMode.WRITE })
  })

  afterEach(async () => {
    await ws.close()
    await rm(root, { recursive: true, force: true })
  })

  it('closing a streamed read early stops the backend', async () => {
    const pulls = spyReads(ws)
    const report = new OpReport()
    const stream = await openReported(ws, '/disk/huge.bin', report)
    const first = await stream.next()
    expect(first.value).toEqual(pattern(CHUNK))
    await stream.return()
    expect(pulls.opened).toBe(1)
    expect(pulls.pulls).toBeLessThanOrEqual(2)
    expect(pulls.closed).toBe(true)
    expect(report.completed).toBe(true)
    expect(report.bytes).toBeLessThan(MIB)
    expect(files.opened.length).toBe(1)
    expect(await fileClosed(files.opened[0])).toBe(true)
    expect(await settlesWithin(ws.unmount('/disk'), 2000)).toBe(true)
  })

  it.skipIf(collectGarbage === undefined)(
    'a streamed read dropped unclosed closes its file once collected, and unmount completes (needs a gc the runtime exposes)',
    async () => {
      const pulls = spyReads(ws)
      const report = new OpReport()
      const openAndDrop = async (): Promise<void> => {
        const stream = await openReported(ws, '/disk/huge.bin', report)
        expect(((await stream.next()).value as Uint8Array).byteLength).toBe(CHUNK)
      }
      await openAndDrop()
      let unmounted = false
      const unmounting = ws.unmount('/disk').then(() => {
        unmounted = true
      })
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(unmounted).toBe(false)
      expect(pulls.closed).toBe(false)
      expect(await collectedWithin(() => unmounted)).toBe(true)
      await unmounting
      expect(pulls.closed).toBe(true)
      expect([report.completed, report.bytes]).toEqual([true, CHUNK])
      expect(files.opened.length).toBe(1)
      expect(await fileClosed(files.opened[0])).toBe(true)
    },
  )
})
