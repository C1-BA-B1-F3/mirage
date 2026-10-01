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

import { LISTING_TRUST_WINDOW } from '@struktoai/mirage-core/cache/index/constants'
import { RAMIndexCacheStore } from '@struktoai/mirage-core/cache/index/ram'
import { runInCommandScope } from '@struktoai/mirage-core/cache/index/scope'
import type { IndexCacheStore } from '@struktoai/mirage-core/cache/index/store'
import type { FileStat } from '@struktoai/mirage-core/types'
import { ListingVersion, MountMode, PathSpec, ReadPolicy } from '@struktoai/mirage-core/types'
import type { BaseVFS } from '@struktoai/mirage-core/vfs/base'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { Mount } from '@struktoai/mirage-core/workspace/mount/spec'
import { Reconciler } from '@struktoai/mirage-core/workspace/reconcile'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { HfHubAccessor } from '../../accessor/hf_hub.ts'
import { FakeHub, serveHub } from '../../core/hf_hub/_test_util.ts'
import { stat } from '../../core/hf_hub/stat.ts'
import { Workspace } from '../../workspace.ts'
import { HfModelsVFS } from '../hf_models/hf_models.ts'
import { buildVfs } from '../registry.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()
const ROOT = new PathSpec({ vfsPath: '', virtual: '/m', directory: '/m' })
const LISTED = 'b.txt\n'
const GROWN = 'b.txt\nnew.txt\n'

let hubs: FakeHub[] = []

afterEach(async () => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  await Promise.all(hubs.map((hub) => hub.close()))
  hubs = []
})

async function hubOf(): Promise<FakeHub> {
  const fake = new FakeHub()
  fake.files().set('a.txt', ENC.encode('alpha\n'))
  fake.files().set('docs/sub/b.txt', ENC.encode('bravo\n'))
  hubs.push(fake)
  return serveHub(fake)
}

function vfsOf(fake: FakeHub, revision?: string): Promise<BaseVFS> {
  const config: Record<string, unknown> = { repo_id: 'acme/widget', endpoint: fake.url }
  if (revision !== undefined) config.revision = revision
  return buildVfs('hf_models', config)
}

function wsOf(
  vfs: BaseVFS,
  policy: ReadPolicy = ReadPolicy.FRESH,
  index: IndexCacheStore | null = null,
): Workspace {
  const w = new Workspace({
    '/m': new Mount(vfs, { mode: MountMode.READ, read: { policy, ttl: 600 } }),
    '/r': [new RAMVFS(), MountMode.WRITE],
  })
  if (index !== null) {
    ;(w.registry.mountFor('/m') as { indexStore: IndexCacheStore }).indexStore = index
  }
  return w
}

async function out(w: Workspace, line: string): Promise<string> {
  const result = await w.shell(line)
  expect([result.exitCode, DEC.decode(result.stderr)], line).toEqual([0, ''])
  return DEC.decode(result.stdout)
}

function counts(fake: FakeHub): number[] {
  return [
    fake.count('revision'),
    fake.count('tree'),
    fake.count('paths_info'),
    fake.count('resolve'),
  ]
}

function revs(fake: FakeHub, route: string): string[] {
  return [...new Set(fake.log.filter(([name]) => name === route).map(([, , rev]) => rev))]
}

function add(fake: FakeHub): void {
  fake.files().set('docs/sub/new.txt', ENC.encode('new\n'))
}

async function stored(w: Workspace, key = '/m'): Promise<string | null> {
  return (await w.registry.mountFor('/m').indexStore.listDir(key)).version ?? null
}

function accessorOf(vfs: BaseVFS): HfHubAccessor {
  return vfs.accessor as HfHubAccessor
}

const SHA = '0123456789abcdef0123456789abcdef01234567'

describe('hf_hub versions a listing by its head commit', () => {
  it.each(['hf_models', 'hf_datasets', 'hf_spaces'])(
    '%s declares one version for the whole mount',
    async (name) => {
      const vfs = await buildVfs(name, { repo_id: 'acme/widget' })
      expect(vfs.listingVersion).toBe(ListingVersion.MOUNT)
    },
  )

  // The check asks the revision object trimmed to its sha, about 110 bytes
  // against the whole sibling list.
  it('asks the head with expand[]=sha', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      await out(w, 'ls /m')
      const asked = fake.log.filter(([name]) => name === 'revision').map(([, , , q]) => q)
      expect(asked).toEqual(['expand[]=sha', 'expand[]=sha'])
    } finally {
      await w.close()
    }
  })

  // The refill walks the tree at the commit the head named; every other route
  // stays on the branch the mount reads.
  it('walks the tree at the head it resolved', async () => {
    const fake = await hubOf()
    const vfs = await vfsOf(fake)
    const w = wsOf(vfs)
    try {
      const head = fake.head()
      await out(w, 'ls /m')
      await out(w, 'cat /m/a.txt')
      await out(w, 'cat /m/a.txt')
      expect(revs(fake, 'tree')).toEqual([head])
      expect(revs(fake, 'paths_info')).toEqual(['main'])
      expect(revs(fake, 'resolve')).toEqual(['main'])
      expect(accessorOf(vfs).revision).toBe('main')
      expect(await stored(w)).toBe(head)
    } finally {
      await w.close()
    }
  })

  // Every folder of the refill is seeded with the head, one setDir each.
  it('stamps every folder it seeds with the head', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      const head = fake.head()
      for (const key of ['/m', '/m/docs', '/m/docs/sub']) expect(await stored(w, key)).toBe(head)
    } finally {
      await w.close()
    }
  })

  // The listing an implied folder sits in names it, with a row of its own.
  it('lists a folder implied by a deeper file', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      expect(await out(w, 'ls /m')).toBe('a.txt\ndocs\n')
      expect(await out(w, 'ls /m/docs')).toBe('sub\n')
    } finally {
      await w.close()
    }
  })

  it('costs one revision for an unchanged second command', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      fake.log.length = 0
      expect(await out(w, 'ls /m/docs/sub')).toBe(LISTED)
      expect(counts(fake)).toEqual([1, 0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // The gate's check misses, and the refill asks the head once more for the
  // commit it walks the tree at.
  it('checks then walks once for a changed second command', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      add(fake)
      fake.log.length = 0
      expect(await out(w, 'ls /m/docs/sub')).toBe(GROWN)
      expect(counts(fake)).toEqual([2, 1, 0, 0])
    } finally {
      await w.close()
    }
  })

  it.each(['find /m -type f', 'ls -R /m'])('sees an outside add on a walk: %s', async (line) => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      fake.log.length = 0
      expect(await out(w, line)).not.toContain('new.txt')
      expect(counts(fake)).toEqual([1, 0, 0, 0])
      add(fake)
      fake.log.length = 0
      expect(await out(w, line)).toContain('new.txt')
      expect(counts(fake)).toEqual([2, 1, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A bounded mount's cold fill resolves the head too, so the version it
  // stores always comes from a response.
  it('asks the head once for a bounded cold fill', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake), ReadPolicy.BOUNDED)
    try {
      await out(w, 'ls /m')
      expect(counts(fake)).toEqual([1, 1, 0, 0])
      expect(await stored(w)).toBe(fake.head())
      fake.log.length = 0
      await out(w, 'ls /m/docs/sub')
      expect(counts(fake)).toEqual([0, 0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A second mount over a warm shared store has not loaded its tree; the
  // gate's root stat asks the head once and never walks or loads the tree.
  it('never walks for a root stat through a throwaway index', async () => {
    const fake = await hubOf()
    const shared = new RAMIndexCacheStore({ ttl: 600 })
    const one = wsOf(await vfsOf(fake), ReadPolicy.FRESH, shared)
    const twoVfs = await vfsOf(fake)
    const two = wsOf(twoVfs, ReadPolicy.FRESH, shared)
    try {
      await out(one, 'ls /m')
      fake.log.length = 0
      const found = (await two.opsRegistry.call('stat', twoVfs, twoVfs.accessor, ROOT, [], {
        index: new RAMIndexCacheStore(),
      })) as FileStat
      expect(found.fingerprint).toBe(fake.head())
      expect(counts(fake)).toEqual([1, 0, 0, 0])
      expect(accessorOf(twoVfs).treeLoaded).toBe(false)
    } finally {
      await one.close()
      await two.close()
    }
  })

  // The mount's own index answers the root from its listing, read past the
  // gate, so a getattr of the root costs nothing however stale the trust is.
  it.each([true, false])(
    'reads the root ungated through the mount index (scoped=%s)',
    async (scoped) => {
      const real = performance.now.bind(performance)
      let offset = 0
      vi.spyOn(performance, 'now').mockImplementation(() => real() + offset)
      const fake = await hubOf()
      const vfs = await vfsOf(fake)
      const w = wsOf(vfs)
      try {
        await out(w, 'ls /m')
        const version = await stored(w)
        offset += LISTING_TRUST_WINDOW * 2000
        fake.log.length = 0
        const index = w.registry.mountFor('/m').index
        const found = scoped
          ? await runInCommandScope(() => stat(accessorOf(vfs), ROOT, index))
          : await stat(accessorOf(vfs), ROOT, index)
        expect(version).not.toBeNull()
        expect(found.fingerprint).toBe(version)
        expect(counts(fake)).toEqual([0, 0, 0, 0])
      } finally {
        await w.close()
      }
    },
  )

  it('names no version for an expired root listing', async () => {
    const fake = await hubOf()
    const vfs = await vfsOf(fake)
    const w = wsOf(vfs, ReadPolicy.BOUNDED)
    try {
      await out(w, 'ls /m')
      await w.registry.mountFor('/m').indexStore.invalidate()
      fake.log.length = 0
      const found = await stat(accessorOf(vfs), ROOT, w.registry.mountFor('/m').index)
      expect(found.fingerprint).toBeNull()
      expect(counts(fake)).toEqual([0, 0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A refused head names no version, and the root stat never falls into a
  // refill of the throwaway index.
  it.each([
    [404, 'RevisionNotFound'],
    [401, ''],
  ] as [number, string][])(
    'names no version and walks nothing for a refused head (%s)',
    async (status, code) => {
      const fake = await hubOf()
      const vfs = await vfsOf(fake)
      const w = wsOf(vfs)
      try {
        await out(w, 'ls /m')
        fake.fail.set('revision', [status, code])
        fake.log.length = 0
        const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
        const found = await stat(accessorOf(vfs), ROOT, new RAMIndexCacheStore())
        expect(found.fingerprint).toBeNull()
        expect([fake.count('revision'), fake.count('tree')]).toEqual([1, 0])
        // Said on stderr, the way Python logs it.
        expect(warn).toHaveBeenCalledTimes(1)
        expect(String(warn.mock.calls[0]?.[0])).toMatch(/^head of \S+ not answered: /)
        warn.mockRestore()
      } finally {
        await w.close()
      }
    },
  )

  // With no index at all (the null index), the root asks the head once.
  it('asks the head once for a root stat with no index', async () => {
    const fake = await hubOf()
    const vfs = await vfsOf(fake)
    const found = await stat(accessorOf(vfs), ROOT, undefined)
    expect(found.fingerprint).toBe(fake.head())
    expect(counts(fake)).toEqual([1, 0, 0, 0])
  })

  it('pins the effective revision lowercased', () => {
    const pin = (revision?: string): string | null =>
      new HfModelsVFS(
        revision === undefined ? { repoId: 'acme/widget' } : { repoId: 'acme/widget', revision },
      ).listingsPin
    expect(pin(SHA.toUpperCase())).toBe(SHA)
    expect(pin('b'.repeat(64))).toBe('b'.repeat(64))
    expect(pin('main')).toBeNull()
    expect(pin()).toBeNull()
    expect(pin(SHA.slice(0, -1))).toBeNull()
  })

  // Pinned to a commit given in uppercase: the refill still resolves the
  // head, stores the lowercase sha the Hub answers, and the next command
  // serves it with no request.
  it('serves a listing pinned to a commit with no request', async () => {
    const fake = await hubOf()
    const head = fake.head()
    const w = wsOf(await vfsOf(fake, head.toUpperCase()))
    try {
      expect(await out(w, 'ls /m/docs/sub')).toBe(LISTED)
      expect(counts(fake)).toEqual([1, 1, 0, 0])
      expect(await stored(w)).toBe(head)
      fake.log.length = 0
      expect(await out(w, 'ls /m/docs/sub')).toBe(LISTED)
      expect(counts(fake)).toEqual([0, 0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A mount pinned to an older commit, over a store a `main` mount filled,
  // must not serve main's listing just because it is pinned.
  it("never serves another revision's listing to a pinned mount", async () => {
    const fake = await hubOf()
    const old = fake.head()
    const shared = new RAMIndexCacheStore({ ttl: 600 })
    const main = wsOf(await vfsOf(fake), ReadPolicy.FRESH, shared)
    try {
      await out(main, 'ls /m/docs/sub')
      add(fake)
      expect(await out(main, 'ls /m/docs/sub')).toBe(GROWN)
    } finally {
      await main.close()
    }
    const pinned = wsOf(await vfsOf(fake, old), ReadPolicy.FRESH, shared)
    try {
      fake.log.length = 0
      expect(await out(pinned, 'ls /m/docs/sub')).toBe(LISTED)
      // The check answers the pin, not main's head: a refill at it.
      expect(counts(fake)).toEqual([2, 1, 0, 0])
      fake.log.length = 0
      expect(await out(pinned, 'ls /m/docs/sub')).toBe(LISTED)
      expect(counts(fake)).toEqual([0, 0, 0, 0])
    } finally {
      await pinned.close()
    }
  })

  // A branch named with 40 hex characters is not a commit: it is stored at
  // the head its revision answered, so an outside change is always seen.
  it('never serves a hex branch name as a pin', async () => {
    const fake = await hubOf()
    const branch = 'a'.repeat(40)
    fake.branches.add(branch)
    const w = wsOf(await vfsOf(fake, branch))
    try {
      expect(w.registry.mountFor('/m').vfs.listingsPin).toBe(branch)
      expect(await out(w, 'ls /m/docs/sub')).toBe(LISTED)
      add(fake)
      fake.log.length = 0
      expect(await out(w, 'ls /m/docs/sub')).toBe(GROWN)
      expect(counts(fake)).not.toEqual([0, 0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A commit landing between the head and the tree walk: the tree is walked
  // at the head that was named, so the rows match their version, and the
  // next command's check sees the change.
  it('catches a commit between the head and the walk on the next command', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      const old = fake.head()
      fake.afterRevision = () => {
        add(fake)
      }
      expect(await out(w, 'ls /m/docs/sub')).toBe(LISTED)
      fake.afterRevision = null
      expect(revs(fake, 'tree')).toEqual([old])
      expect(await stored(w)).toBe(old)
      fake.log.length = 0
      expect(await out(w, 'ls /m/docs/sub')).toBe(GROWN)
      expect(counts(fake)).toEqual([2, 1, 0, 0])
    } finally {
      await w.close()
    }
  })

  // A revision the Hub does not know: the refusal wording is the one the
  // tree walk gave before the head was asked first.
  it('reads a bad revision as permission denied', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake, 'f'.repeat(40)))
    try {
      const ls = await w.shell('ls /m')
      expect([ls.exitCode, DEC.decode(ls.stderr)]).toEqual([
        2,
        "ls: cannot open directory '/m': Permission denied\n",
      ])
      const cat = await w.shell('cat /m/a.txt')
      expect([cat.exitCode, DEC.decode(cat.stderr)]).toEqual([
        1,
        'cat: /m/a.txt: Permission denied\n',
      ])
      expect(await out(w, 'stat -c %n /m')).toBe('/m\n')
    } finally {
      await w.close()
    }
  })

  // An hf outage is a transport failure, not a programming error: the gate
  // answers EXPIRED, warned, and the listing stays stored for the re-list.
  it('keeps the listing when the Hub cannot be reached', async () => {
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      const mount = w.registry.mountFor('/m')
      const before = await mount.indexStore.listDir('/m/docs/sub')
      vi.stubGlobal('fetch', () => Promise.reject(new TypeError('fetch failed')))
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      vi.useFakeTimers({ toFake: ['setTimeout'] })
      const rec = new Reconciler(w.cache, w.namespace, w.opsRegistry)
      const verdict = runInCommandScope(() =>
        rec.mayServeListing(mount, '/m/docs/sub', before.version ?? null),
      )
      await vi.runAllTimersAsync()
      expect(await verdict).toBe(false)
      vi.useRealTimers()
      expect((await mount.indexStore.listDir('/m/docs/sub')).entries).toEqual(before.entries)
      expect(warn).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
      vi.unstubAllGlobals()
      await w.close()
    }
  })

  // A FUSE or programmatic read belongs to no command: it trusts a listing
  // for the window, then pays one version check, never a tree walk.
  it('checks once past the window on an unscoped read', async () => {
    const real = performance.now.bind(performance)
    let offset = 0
    vi.spyOn(performance, 'now').mockImplementation(() => real() + offset)
    const fake = await hubOf()
    const w = wsOf(await vfsOf(fake))
    try {
      await out(w, 'ls /m')
      fake.log.length = 0
      expect(await w.vfs.readdir('/m/docs/sub')).toEqual(['/m/docs/sub/b.txt'])
      await w.vfs.stat('/m/docs/sub/b.txt')
      expect(counts(fake)).toEqual([0, 0, 0, 0])
      offset += LISTING_TRUST_WINDOW * 1000
      await w.vfs.readdir('/m/docs/sub')
      await w.vfs.stat('/m/docs/sub/b.txt')
      expect(counts(fake)).toEqual([1, 0, 0, 0])
    } finally {
      await w.close()
    }
  })
})
