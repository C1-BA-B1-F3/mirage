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

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RegisteredOp } from '../../ops/registry.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { IndexView } from '../../cache/index/view.ts'
import { FakeGitHub } from '../../core/github/_test_util.ts'
import { MountMode, ReadPolicy } from '../../types.ts'
import { getTestParser } from '../../workspace/fixtures/workspace_fixture.ts'
import { Mount } from '../../workspace/mount/spec.ts'
import { Workspace } from '../../workspace/workspace/workspace.ts'
import { GitHubVFS } from './github.ts'

const DEC = new TextDecoder()
const OLD_LS = 'a.txt\nb.txt\n'
const NEW_LS = 'a.txt\nb.txt\nc.txt\n'

let gh: FakeGitHub

beforeEach(() => {
  gh = new FakeGitHub({ 'docs/a.txt': 'alpha\n', 'docs/b.txt': 'bravo\n', 'top.txt': 'top\n' })
  vi.stubGlobal('fetch', gh.fetch)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

async function vfsOf(): Promise<GitHubVFS> {
  const vfs = await GitHubVFS.create({
    token: 't',
    owner: 'o',
    repo: 'r',
    ref: 'main',
    baseUrl: gh.url,
  })
  gh.log.length = 0
  return vfs
}

async function wsOf(
  vfs: GitHubVFS,
  read: { policy: ReadPolicy; ttl: number } | null = { policy: ReadPolicy.BOUNDED, ttl: 1 },
  prefix = '/gh',
): Promise<Workspace> {
  const mount =
    read === null
      ? new Mount(vfs, { mode: MountMode.READ })
      : new Mount(vfs, { mode: MountMode.READ, read })
  return new Workspace({ [prefix]: mount }, { shellParser: await getTestParser() })
}

async function out(w: Workspace, line: string, sessionId?: string): Promise<string> {
  const result = await w.shell(line, sessionId === undefined ? {} : { sessionId })
  expect([result.exitCode, DEC.decode(result.stderr)], line).toEqual([0, ''])
  return DEC.decode(result.stdout)
}

function indexOf(w: Workspace, path: string): IndexCacheStore {
  return w.registry.mountFor(path).index
}

function sessions(w: Workspace, n: number): string[] {
  const ids = Array.from({ length: n }, (_, i) => `s${String(i)}`)
  for (const id of ids) w.createSession(id)
  return ids
}

function settleWithin<T>(work: Promise<T>, ms: number): Promise<'done' | 'pending'> {
  return Promise.race([
    work.then(() => 'done' as const),
    new Promise<'pending'>((resolve) => {
      setTimeout(() => {
        resolve('pending')
      }, ms)
    }),
  ])
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function delta(before: [number, number, number]): [number, number, number] {
  const now = gh.counts()
  return [now[0] - before[0], now[1] - before[1], now[2] - before[2]]
}

/** Pause one refill outside the mutation fence so another reader can enter. */
function gateRefill(): { wiped: Promise<void>; release: () => void } {
  // eslint-disable-next-line @typescript-eslint/unbound-method
  const original = IndexView.prototype.invalidatePrefix
  let armed = true
  let signal = (): void => undefined
  let release = (): void => undefined
  const wiped = new Promise<void>((resolve) => {
    signal = resolve
  })
  const released = new Promise<void>((resolve) => {
    release = resolve
  })
  vi.spyOn(IndexView.prototype, 'invalidatePrefix').mockImplementation(async function (
    this: IndexView,
    path: string,
  ): Promise<void> {
    await original.call(this, path)
    if (!armed) return
    armed = false
    signal()
    await released
  })
  return { wiped, release }
}

describe('github listings under a shared view', () => {
  it('refills once for seven sessions after an expiry', async () => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    try {
      const ids = sessions(w, 7)
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await indexOf(w, '/gh').invalidate()
      const before = gh.counts()
      const outputs = await Promise.all(ids.map((id) => out(w, 'ls /gh/docs', id)))
      expect(delta(before)).toEqual([0, 1, 0])
      expect(outputs).toEqual(ids.map(() => OLD_LS))
    } finally {
      await w.close()
    }
  })

  it('waits on a refill in progress instead of duplicating it', async () => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    let first: Promise<string> | undefined
    let second: Promise<string> | undefined
    let gate: { wiped: Promise<void>; release: () => void } | undefined
    try {
      const [s0, s1] = sessions(w, 2)
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await indexOf(w, '/gh').invalidate()
      gate = gateRefill()
      const before = gh.counts()
      first = out(w, 'ls /gh/docs', s0)
      expect(await settleWithin(gate.wiped, 2000)).toBe('done')
      second = out(w, 'ls /gh/docs', s1)
      const early = await settleWithin(second, 20)
      gate.release()
      expect(await Promise.all([first, second])).toEqual([OLD_LS, OLD_LS])
      expect(delta(before)).toEqual([0, 1, 0])
      expect(early).toBe('pending')
    } finally {
      gate?.release()
      await Promise.allSettled([first, second])
      await w.close()
    }
  })

  it('lets a glob in the refill gap answer on its own', async () => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    let first: Promise<string> | undefined
    let glob: Promise<string> | undefined
    let gate: { wiped: Promise<void>; release: () => void } | undefined
    try {
      const [s0, s1] = sessions(w, 2)
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await indexOf(w, '/gh').invalidate()
      gate = gateRefill()
      const before = gh.counts()
      first = out(w, 'ls /gh/docs', s0)
      expect(await settleWithin(gate.wiped, 2000)).toBe('done')
      glob = out(w, 'echo /gh/docs/*', s1)
      expect(await settleWithin(glob, 5000)).toBe('done')
      expect(await glob).toBe('/gh/docs/a.txt /gh/docs/b.txt\n')
      gate.release()
      expect(await first).toBe(OLD_LS)
      expect(delta(before)).toEqual([0, 2, 0])
    } finally {
      gate?.release()
      await Promise.allSettled([first, glob])
      await w.close()
    }
  })

  it('never deadlocks mixed commands after an expiry', async () => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    try {
      const ids = sessions(w, 3)
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await indexOf(w, '/gh').invalidate()
      const lines: [string, (stdout: string) => void][] = [
        [
          'ls /gh/docs',
          (s) => {
            expect(s).toBe(OLD_LS)
          },
        ],
        [
          'find /gh -name a.txt',
          (s) => {
            expect(s).toBe('/gh/docs/a.txt\n')
          },
        ],
        [
          'du -a /gh',
          (s) => {
            expect(s).toContain('/gh/docs/a.txt')
          },
        ],
        [
          'grep -rl alpha /gh',
          (s) => {
            expect(s).toBe('/gh/docs/a.txt\n')
          },
        ],
        [
          'echo /gh/docs/*',
          (s) => {
            expect(s).toBe('/gh/docs/a.txt /gh/docs/b.txt\n')
          },
        ],
        [
          'cat /gh/docs/a.txt',
          (s) => {
            expect(s).toBe('alpha\n')
          },
        ],
      ]
      const running = lines.map(([line], i) => out(w, line, ids[i % ids.length]))
      const all = Promise.all(running)
      expect(await settleWithin(all, 5000)).toBe('done')
      const outputs = await all
      lines.forEach(([, check], i) => {
        check(outputs[i] ?? '')
      })
    } finally {
      await w.close()
    }
  })
})

describe('github tree walks after the listing expires', () => {
  // [first command, prefix, expected stdout fragment]
  const ROOT: [string, string, string][] = [
    ['find /gh -name c.txt', '/gh', '/gh/docs/c.txt\n'],
    ['cd /gh && find . -name c.txt', '/gh', './docs/c.txt\n'],
    ['du -a /gh', '/gh', '/gh/docs/c.txt'],
    ['cd /gh && du -a', '/gh', './docs/c.txt'],
    ['find /r/gh -name c.txt', '/r/gh', '/r/gh/docs/c.txt\n'],
  ]
  const SUBDIR: [string, string, string][] = [
    ['find /gh/docs -name c.txt', '/gh', '/gh/docs/c.txt\n'],
    ['cd /gh/docs && du -a', '/gh', './c.txt'],
    ['du -a /gh/docs', '/gh', '/gh/docs/c.txt'],
  ]

  for (const [kind, rows] of [
    ['root operand', ROOT],
    ['subdirectory operand', SUBDIR],
  ] as const) {
    it.each(rows)(`${kind}: %s sees a remote add with one refill`, async (line, prefix, want) => {
      const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 }, prefix)
      try {
        expect(await out(w, `ls ${prefix}/docs`)).toBe(OLD_LS)
        gh.set('docs/c.txt', 'charlie\n')
        await indexOf(w, prefix).invalidate()
        const before = gh.counts()
        expect(await out(w, line)).toContain(want)
        expect(await out(w, `ls ${prefix}`)).toBe('docs\ntop.txt\n')
        expect(delta(before)).toEqual([0, 1, 0])
      } finally {
        await w.close()
      }
    })
  }

  it('never refills a truncated tree in a loop', async () => {
    gh.truncatedRecursive = true
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    try {
      await w.shell('find /gh -name a.txt')
      const walks = gh.count('recursive')
      await w.shell('find /gh -name a.txt')
      expect(gh.count('recursive')).toBe(walks)
    } finally {
      await w.close()
    }
  })
})

describe('github listings respect the mount ttl', () => {
  const FIRST = ['ls /gh/docs', 'echo /gh/docs/*', 'for f in /gh/docs/*; do echo $f; done']
  for (const policy of [ReadPolicy.BOUNDED, ReadPolicy.FRESH]) {
    it.each(FIRST)(
      `${policy}: a listing first filled by %s expires with the mount`,
      async (first) => {
        const w = await wsOf(await vfsOf(), { policy, ttl: 1 })
        try {
          await out(w, first)
          gh.set('docs/c.txt', 'charlie\n')
          expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
          await sleep(1100)
          expect(await out(w, 'ls /gh/docs')).toBe(NEW_LS)
        } finally {
          await w.close()
        }
      },
    )
  }

  const PROBE: [string, string][] = [
    ['ls /gh/docs', NEW_LS],
    ['cat /gh/docs/a.txt', 'alpha, edited\n'],
    ['find /gh -name c.txt', '/gh/docs/c.txt\n'],
  ]
  it.each(PROBE)('the first command after the expiry, %s, sees the change', async (line, want) => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 1 })
    try {
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      gh.set('docs/c.txt', 'charlie\n')
      gh.set('docs/a.txt', 'alpha, edited\n')
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await sleep(1100)
      expect(await out(w, line)).toBe(want)
    } finally {
      await w.close()
    }
  })

  it('bounds each prefix of one VFS by its own mount ttl', async () => {
    const vfs = await vfsOf()
    const w = new Workspace(
      {
        '/a': new Mount(vfs, {
          mode: MountMode.READ,
          read: { policy: ReadPolicy.BOUNDED, ttl: 1 },
        }),
        '/b': new Mount(vfs, {
          mode: MountMode.READ,
          read: { policy: ReadPolicy.BOUNDED, ttl: 600 },
        }),
      },
      { shellParser: await getTestParser() },
    )
    try {
      expect(await out(w, 'ls /a/docs')).toBe(OLD_LS)
      expect(await out(w, 'ls /b/docs')).toBe(OLD_LS)
      gh.set('docs/c.txt', 'charlie\n')
      await sleep(1100)
      expect(await out(w, 'ls /a/docs')).toBe(NEW_LS)
      expect(await out(w, 'ls /b/docs')).toBe(OLD_LS)
    } finally {
      await w.close()
    }
  })

  it('writes the listing a */ directory stat refills through the mount view', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
    const vfs = await vfsOf()
    const w = await wsOf(vfs, { policy: ReadPolicy.BOUNDED, ttl: 2 })
    try {
      const glob = vfs.ops().find((op) => op.name === 'glob')
      if (glob === undefined) throw new Error('GitHub serves no glob op')
      w.mount('/gh').registerFns([
        {
          ...glob,
          fn: async (...args) => {
            const found = await glob.fn(...args)
            vi.setSystemTime(Date.now() + 3000)
            return found
          },
        } satisfies RegisteredOp,
      ])
      expect(await out(w, 'echo /gh/*/')).toBe('/gh/docs/\n')
      vi.restoreAllMocks()
      gh.set('docs/c.txt', 'charlie\n')
      vi.setSystemTime(Date.now() + 3000)
      expect(await out(w, 'ls /gh/docs')).toBe(NEW_LS)
    } finally {
      await w.close()
    }
  })

  it('caps a mount with no ttl key at the default 600 s', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'))
    const w = await wsOf(await vfsOf(), null)
    try {
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      const t0 = Date.now()
      gh.set('docs/c.txt', 'charlie\n')
      vi.setSystemTime(t0 + 599_000)
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      vi.setSystemTime(t0 + 601_000)
      expect(await out(w, 'ls /gh/docs')).toBe(NEW_LS)
    } finally {
      await w.close()
    }
  })
})

// du refills an expired tree only after it has validated its flags, and
// find's expression is refused before its handler runs: a usage error
// answers locally, with no request at all.
describe('an invalid walk after an expiry', () => {
  it.each(['du -s -a /gh', 'find /gh -maxdepth nope'])('%s fetches nothing', async (line) => {
    const w = await wsOf(await vfsOf(), { policy: ReadPolicy.BOUNDED, ttl: 600 })
    try {
      expect(await out(w, 'ls /gh/docs')).toBe(OLD_LS)
      await indexOf(w, '/gh').invalidate()
      const before = gh.counts()
      const result = await w.shell(line)
      expect(result.exitCode).toBe(1)
      expect(DEC.decode(result.stderr)).not.toBe('')
      expect(delta(before)).toEqual([0, 0, 0])
    } finally {
      await w.close()
    }
  })
})
