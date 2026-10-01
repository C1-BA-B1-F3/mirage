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
import { shiftPerformanceNow } from '../../cache/_test_util.ts'
import { LISTING_TRUST_WINDOW } from '../../cache/index/constants.ts'
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import type { IndexCacheStore } from '../../cache/index/store.ts'
import { runInCommandScope } from '../../cache/index/scope.ts'
import { FakeGitHub } from '../../core/github/_test_util.ts'
import { stat } from '../../core/github/stat.ts'
import { GitHubWalk } from '../../core/github/watch.ts'
import { ListingVersion, MountMode, PathSpec, ReadPolicy } from '../../types.ts'
import { getTestParser } from '../../workspace/fixtures/workspace_fixture.ts'
import { Mount } from '../../workspace/mount/spec.ts'
import { Reconciler } from '../../workspace/reconcile.ts'
import { Workspace } from '../../workspace/workspace/workspace.ts'
import { RAMVFS } from '../ram/ram.ts'
import { GitHubVFS } from './github.ts'

const DEC = new TextDecoder()
const ROOT = new PathSpec({ vfsPath: '', virtual: '/gh', directory: '/gh' })
const LISTED = 'a.txt\nb.txt\nc.txt\n'
const GROWN = 'a.txt\nb.txt\nc.txt\nnew.txt\n'

let gh: FakeGitHub

function three(): FakeGitHub {
  const hub = new FakeGitHub(
    Object.fromEntries(
      ['d1', 'd2', 'd3'].flatMap((d) => ['a', 'b', 'c'].map((n) => [`${d}/${n}.txt`, 'x\n'])),
    ),
  )
  vi.stubGlobal('fetch', hub.fetch)
  return hub
}

beforeEach(() => {
  gh = three()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function vfsOf(ref = 'main'): Promise<GitHubVFS> {
  const vfs = await GitHubVFS.create({ token: 't', owner: 'o', repo: 'r', ref, baseUrl: gh.url })
  gh.log.length = 0
  return vfs
}

async function wsOf(
  vfs: GitHubVFS,
  policy: ReadPolicy = ReadPolicy.FRESH,
  index: IndexCacheStore | null = null,
): Promise<Workspace> {
  const w = new Workspace(
    {
      '/gh': new Mount(vfs, { mode: MountMode.READ, read: { policy, ttl: 600 } }),
      '/r': [new RAMVFS(), MountMode.WRITE],
    },
    { shellParser: await getTestParser() },
  )
  if (index !== null) {
    ;(w.registry.mountFor('/gh') as { indexStore: IndexCacheStore }).indexStore = index
  }
  return w
}

async function out(w: Workspace, line: string): Promise<string> {
  const result = await w.shell(line)
  expect([result.exitCode, DEC.decode(result.stderr)], line).toEqual([0, ''])
  return DEC.decode(result.stdout)
}

async function stored(w: Workspace, key = '/gh'): Promise<string | null> {
  return (await w.registry.mountFor('/gh').indexStore.listDir(key)).version ?? null
}

describe('github versions a listing by its head commit', () => {
  it('declares one version for the whole mount', async () => {
    expect((await vfsOf()).listingVersion).toBe(ListingVersion.MOUNT)
  })

  // The mount's own index answers the root from its listing, read past the
  // gate, so a getattr of the root costs nothing however stale the trust is.
  it.each([true, false])(
    'reads the root ungated through the mount index (scoped=%s)',
    async (scoped) => {
      const clock = shiftPerformanceNow()
      const vfs = await vfsOf()
      expect(vfs.listingVersion).toBe(ListingVersion.MOUNT)
      const w = await wsOf(vfs)
      try {
        await out(w, 'ls /gh')
        const version = await stored(w)
        clock.advance(LISTING_TRUST_WINDOW * 2000)
        gh.log.length = 0
        const index = w.registry.mountFor('/gh').index
        const found = scoped
          ? await runInCommandScope(() => stat(vfs.accessor, ROOT, index))
          : await stat(vfs.accessor, ROOT, index)
        expect(version).not.toBeNull()
        expect(found.fingerprint).toBe(version)
        expect(gh.counts()).toEqual([0, 0, 0])
      } finally {
        await w.close()
      }
    },
  )

  // An expired root listing names no version and asks nothing.
  it('names no version for an expired root listing', async () => {
    const vfs = await vfsOf()
    const w = await wsOf(vfs, ReadPolicy.BOUNDED)
    try {
      await out(w, 'ls /gh')
      await w.registry.mountFor('/gh').indexStore.invalidate()
      gh.log.length = 0
      const found = await stat(vfs.accessor, ROOT, w.registry.mountFor('/gh').index)
      expect(found.fingerprint).toBeNull()
      expect(gh.counts()).toEqual([0, 0, 0])
    } finally {
      await w.close()
    }
  })

  // An add outside mirage moves the head, so the next command's one check
  // misses and the tree is fetched once; ls and a glob both see the file.
  it.each([
    ['ls /gh/d1', GROWN],
    ['echo /gh/d1/*', '/gh/d1/a.txt /gh/d1/b.txt /gh/d1/c.txt /gh/d1/new.txt\n'],
  ])('sees an outside add after one check and one walk: %s', async (line, expected) => {
    const w = await wsOf(await vfsOf())
    try {
      await out(w, 'ls /gh')
      gh.set('d1/new.txt', 'new\n')
      gh.log.length = 0
      expect(await out(w, line)).toBe(expected)
      expect(gh.counts()).toEqual([1, 1, 0])
    } finally {
      await w.close()
    }
  })

  // The version is the head the tree response itself named, so a commit
  // landing right after that response is a mismatch for the next command.
  it('catches a commit made after the tree response on the next command', async () => {
    const w = await wsOf(await vfsOf())
    try {
      gh.afterRecursive = () => {
        if (!gh.files.has('d1/new.txt')) gh.set('d1/new.txt', 'new\n')
      }
      expect(await out(w, 'ls /gh/d1')).toBe(LISTED)
      gh.afterRecursive = null
      gh.log.length = 0
      expect(await out(w, 'ls /gh/d1')).toBe(GROWN)
      expect(gh.counts()).toEqual([1, 1, 0])
    } finally {
      await w.close()
    }
  })

  // A second workspace refills the index both share, so the first one's
  // in-memory tree is older than its index. ls answers from the index and
  // pays nothing for that; find and grep walk the tree, so they refill it.
  it('refills a tree older than a shared index before walking it', async () => {
    const shared = new RAMIndexCacheStore()
    const one = await wsOf(await vfsOf(), ReadPolicy.FRESH, shared)
    const two = await wsOf(await vfsOf(), ReadPolicy.FRESH, shared)
    try {
      await out(one, 'ls /gh')
      gh.set('d1/new.txt', 'new x\n')
      await out(two, 'ls /gh/d1')
      gh.log.length = 0
      expect(await out(one, 'ls /gh/d1')).toBe(GROWN)
      expect(gh.counts()).toEqual([1, 0, 0])
      gh.log.length = 0
      expect(await out(one, 'find /gh -name new.txt')).toBe('/gh/d1/new.txt\n')
      expect(gh.counts()).toEqual([1, 1, 0])
      expect(await out(one, 'grep -rl x /gh')).toContain('/gh/d1/new.txt')
    } finally {
      await one.close()
      await two.close()
    }
  })

  // A full-hex ref pins every listing: the stored version is the pin, so the
  // next command serves it with no request. Compared lowercased.
  it('serves a listing pinned to a commit with no request', async () => {
    const head = await gh.head()
    const vfs = await vfsOf(head.toUpperCase())
    expect(vfs.listingsPin).toBe(head)
    const w = await wsOf(vfs)
    try {
      expect(await out(w, 'ls /gh/d1')).toBe(LISTED)
      expect(await stored(w)).toBe(head)
      gh.log.length = 0
      expect(await out(w, 'ls /gh/d1')).toBe(LISTED)
      expect(gh.counts()).toEqual([0, 0, 0])
    } finally {
      await w.close()
    }
  })

  it('pins nothing for a branch', async () => {
    expect((await vfsOf()).listingsPin).toBeNull()
  })

  // A mount pinned to an older commit, over a store a `main` mount filled,
  // must not serve main's listing just because it is pinned.
  it("never serves another ref's listing to a pinned mount", async () => {
    const old = await gh.head()
    const shared = new RAMIndexCacheStore()
    const main = await wsOf(await vfsOf(), ReadPolicy.FRESH, shared)
    try {
      await out(main, 'ls /gh/d1')
      gh.set('d1/new.txt', 'new\n')
      expect(await out(main, 'ls /gh/d1')).toBe(GROWN)
    } finally {
      await main.close()
    }
    const pinned = await wsOf(await vfsOf(old), ReadPolicy.FRESH, shared)
    try {
      gh.log.length = 0
      expect(await out(pinned, 'ls /gh/d1')).toBe(LISTED)
      expect(gh.count('dir')).toBe(1)
    } finally {
      await pinned.close()
    }
  })

  // A ref shaped like a commit is not one: a branch named with 40 or 64 hex
  // characters is stored at the head its tree answered, so it never matches
  // the ref and an outside change is always seen.
  for (const ref of ['a'.repeat(40), 'b'.repeat(64)]) {
    for (const truncated of [false, true]) {
      it(`never serves a hex branch name as a pin (${String(ref.length)}, truncated=${String(truncated)})`, async () => {
        gh.ref = ref
        gh.truncatedRecursive = truncated
        const vfs = await vfsOf(ref)
        expect(vfs.listingsPin).toBe(ref)
        const w = await wsOf(vfs)
        try {
          expect(await out(w, 'ls /gh/d1')).toBe(LISTED)
          gh.set('d1/new.txt', 'new\n')
          gh.log.length = 0
          expect(await out(w, 'ls /gh/d1')).toBe(GROWN)
          expect(gh.counts()).not.toEqual([0, 0, 0])
        } finally {
          await w.close()
        }
      })
    }
  }

  // A truncated tree stores no version, pinned or not, so it re-lists folder
  // by folder as it did before versions existed.
  it('re-lists a truncated pinned mount like an unpinned one', async () => {
    const costs: [number[], number][] = []
    for (const pinned of [false, true]) {
      gh = three()
      gh.truncatedRecursive = true
      const w = await wsOf(await vfsOf(pinned ? await gh.head() : 'main'))
      try {
        await out(w, 'ls /gh/d1')
        expect(await stored(w, '/gh/d1')).toBeNull()
        gh.log.length = 0
        expect(await out(w, 'ls /gh/d1')).toBe(LISTED)
        costs.push([gh.counts(), gh.count('sha_dir')])
      } finally {
        await w.close()
      }
    }
    expect(costs[0]).toEqual(costs[1])
  })

  // A tree response that names no head stores no version, so the next
  // command re-lists exactly as before versions existed.
  it('stores no version for a response without a head', async () => {
    gh.dropSha = true
    const w = await wsOf(await vfsOf())
    try {
      await out(w, 'ls /gh')
      expect(await stored(w)).toBeNull()
      expect(await stored(w, '/gh/d1')).toBeNull()
      gh.log.length = 0
      await out(w, 'ls /gh/d1')
      expect(gh.counts()).toEqual([0, 1, 0])
    } finally {
      await w.close()
    }
  })

  // Tree walks check the version like a listing does, and refill on a miss.
  it.each(['find /gh', 'du -a /gh'])(
    '%s after an outside add checks then walks once',
    async (line) => {
      const w = await wsOf(await vfsOf())
      try {
        await out(w, 'ls /gh')
        gh.set('d1/new.txt', 'new\n')
        gh.log.length = 0
        expect(await out(w, line)).toContain('/gh/d1/new.txt')
        expect(gh.counts()).toEqual([1, 1, 0])
      } finally {
        await w.close()
      }
    },
  )

  // The watcher's walk reseats the tree, and stamps the head it answered, so
  // a revert back to the index's head still refills the walked tree.
  it.each([
    [ReadPolicy.BOUNDED, [0, 1, 0]],
    [ReadPolicy.FRESH, [1, 1, 0]],
  ])('carries the head a watched tree was walked at (%s)', async (policy, cost) => {
    const vfs = await vfsOf()
    const w = await wsOf(vfs, policy)
    try {
      await out(w, 'ls /gh')
      gh.set('d1/new.txt', 'new\n')
      for await (const entry of new GitHubWalk(vfs.accessor).walk(ROOT)) void entry
      expect(vfs.accessor.treeVersion).toBe(await gh.head())
      gh.files.delete('d1/new.txt')
      gh.log.length = 0
      expect(await out(w, 'find /gh -name new.txt')).toBe('')
      expect(gh.counts()).toEqual(cost)
    } finally {
      await w.close()
    }
  })

  // A backend that cannot be reached answers EXPIRED at the gate, warned,
  // and the listing stays stored for the re-list to diff.
  it('keeps the listing when the backend cannot be reached', async () => {
    const w = await wsOf(await vfsOf())
    try {
      await out(w, 'ls /gh')
      const mount = w.registry.mountFor('/gh')
      const before = await mount.indexStore.listDir('/gh/d1')
      vi.stubGlobal('fetch', () => Promise.reject(new TypeError('fetch failed')))
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
      const rec = new Reconciler(w.cache, w.namespace, w.opsRegistry)
      expect(
        await runInCommandScope(() => rec.mayServeListing(mount, '/gh/d1', before.version ?? null)),
      ).toBe(false)
      expect((await mount.indexStore.listDir('/gh/d1')).entries).toEqual(before.entries)
      expect(warn).toHaveBeenCalled()
    } finally {
      await w.close()
    }
  })
})
