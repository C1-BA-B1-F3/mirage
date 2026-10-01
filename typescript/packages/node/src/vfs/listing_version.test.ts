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

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RAMIndexCacheStore } from '@struktoai/mirage-core/cache/index/ram'
import { runInCommandScope } from '@struktoai/mirage-core/cache/index/scope'
import { FileStat, FileType, MountMode, PathSpec, ReadPolicy } from '@struktoai/mirage-core/types'
import type { MountEntry } from '@struktoai/mirage-core/workspace/mount/mount'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { Mount } from '@struktoai/mirage-core/workspace/mount/spec'
import { Reconciler } from '@struktoai/mirage-core/workspace/reconcile'
import { Workspace } from '@struktoai/mirage-core/workspace/workspace/workspace'
import { Workspace as NodeWorkspace } from '../workspace.ts'
import { FakeHub, serveHub } from '../core/hf_hub/_test_util.ts'
import { InlineGitHub } from './fixtures/github.ts'
import { buildVfs, knownVfsNames } from './registry.ts'

const SPEC_VFS = resolve(
  fileURLToPath(import.meta.url),
  '../../../../../../spec/typescript/node/vfs.json',
)

const KINDS = ['none', 'mount', 'folder']

interface Harness {
  ws: NodeWorkspace
  key: string
  nested: string
  counts: () => [number, number]
  change: () => void
  close?: () => Promise<void>
}

async function githubHarness(): Promise<Harness> {
  const gh = new InlineGitHub({ 'docs/sub/a.txt': 'a\n', 'top.txt': 't\n' })
  vi.stubGlobal('fetch', gh.fetch)
  const vfs = await buildVfs('github', {
    token: 't',
    owner: 'o',
    repo: 'r',
    ref: 'main',
    base_url: gh.url,
  })
  const ws = new NodeWorkspace({
    '/m': new Mount(vfs, { mode: MountMode.READ, read: { policy: ReadPolicy.FRESH, ttl: 600 } }),
  })
  return {
    ws,
    key: '/m',
    nested: '/m/docs/sub',
    counts: () => [gh.count('dir'), gh.count('recursive')],
    change: () => {
      gh.set('docs/new.txt', 'n\n')
    },
  }
}

function hfHarness(name: string, segment: string): () => Promise<Harness> {
  return async () => {
    const hub = new FakeHub()
    const files = hub.files(segment)
    files.set('docs/sub/a.txt', new TextEncoder().encode('a\n'))
    files.set('top.txt', new TextEncoder().encode('t\n'))
    await serveHub(hub)
    const vfs = await buildVfs(name, { repo_id: 'acme/widget', endpoint: hub.url })
    const ws = new NodeWorkspace({
      '/m': new Mount(vfs, { mode: MountMode.READ, read: { policy: ReadPolicy.FRESH, ttl: 600 } }),
    })
    return {
      ws,
      key: '/m',
      nested: '/m/docs/sub',
      counts: () => [hub.count('revision'), hub.count('tree')],
      change: () => {
        files.set('docs/new.txt', new TextEncoder().encode('n\n'))
      },
      close: () => hub.close(),
    }
  }
}

// A declarer gets a harness proving that its check and its fill agree, so
// the gate's stat and the stored version are one kind of token. Each
// declaring backend adds its row with its declaration.
const HARNESSES: Record<string, () => Promise<Harness>> = {
  github: githubHarness,
  hf_models: hfHarness('hf_models', 'models'),
  hf_datasets: hfHarness('hf_datasets', 'datasets'),
  hf_spaces: hfHarness('hf_spaces', 'spaces'),
}

async function shell(ws: NodeWorkspace, line: string): Promise<void> {
  const result = await ws.shell(line)
  expect([result.exitCode, new TextDecoder().decode(result.stderr)], line).toEqual([0, ''])
}

async function throwawayStat(ws: NodeWorkspace, mount: MountEntry, key: string): Promise<FileStat> {
  const spec = new PathSpec({ virtual: key, directory: '/', vfsPath: '' })
  return (await ws.opsRegistry.call('stat', mount.vfs, mount.vfs.accessor, spec, [], {
    index: new RAMIndexCacheStore(),
  })) as FileStat
}

async function checkContract(name: string): Promise<void> {
  const make = HARNESSES[name]
  if (make === undefined) throw new Error(`no harness for ${name}`)
  const harness = await make()
  const { ws } = harness
  try {
    const mount = ws.registry.mountFor(harness.key)
    await shell(ws, `ls ${harness.key} ${harness.nested}`)
    const store = mount.indexStore
    const stored = (await store.listDir(harness.key)).version ?? null
    expect(stored).not.toBeNull()
    expect((await store.listDir(harness.nested)).version ?? null).not.toBeNull()
    const remote = await throwawayStat(ws, mount, harness.key)
    expect(remote.fingerprint).toBe(stored)
    const before = harness.counts()
    await shell(ws, `ls ${harness.key} ${harness.nested}`)
    const after = harness.counts()
    expect([after[0] - before[0], after[1] - before[1]]).toEqual([1, 0])
    expect(mount.vfs.listingVersion).toBe(manifest()[name]?.listing_version)
    harness.change()
    const moved = await throwawayStat(ws, mount, harness.key)
    expect(moved.fingerprint ?? null).not.toBeNull()
    expect(moved.fingerprint).not.toBe(stored)
  } finally {
    await ws.close()
    await harness.close?.()
  }
}

function manifest(): Record<string, { listing_version?: unknown }> {
  return (
    JSON.parse(readFileSync(SPEC_VFS, 'utf8')) as {
      capabilities: Record<string, { listing_version?: unknown }>
    }
  ).capabilities
}

function declared(): string[] {
  const known = new Set(knownVfsNames())
  return Object.entries(manifest())
    .filter(([name, caps]) => known.has(name) && caps.listing_version !== 'none')
    .map(([name]) => name)
}

class StubVFS extends RAMVFS {
  override readonly indexTtl: number = 600
}

describe('listing version declarations', () => {
  it('every backend declares one of the three kinds', () => {
    for (const [name, caps] of Object.entries(manifest())) {
      expect([name, KINDS.includes(String(caps.listing_version))]).toEqual([name, true])
    }
    expect(manifest().s3?.listing_version).toBe('none')
  })

  it('every declaring backend has a harness', () => {
    expect(declared().sort()).toEqual(Object.keys(HARNESSES).sort())
  })

  it('the harness roster is pinned', () => {
    // A literal, not the derived set: the expectation must not move with the
    // spec it checks.
    expect(Object.keys(HARNESSES).sort()).toEqual([
      'github',
      'hf_datasets',
      'hf_models',
      'hf_spaces',
    ])
  })

  const undeclared = (): string[] => {
    const known = new Set(knownVfsNames())
    const caps = manifest()
    return [...known].filter((name) => caps[name]?.listing_version === 'none').sort()
  }

  it.each(undeclared())('%s never pays a version check', async (name) => {
    const vfs = new StubVFS()
    Object.defineProperty(vfs, 'listingVersion', {
      value: manifest()[name]?.listing_version,
      configurable: true,
    })
    const ws = new Workspace(
      { '/m': vfs },
      { mode: MountMode.WRITE, read: { policy: ReadPolicy.FRESH, ttl: 600 } },
    )
    const stat = vi
      .spyOn(ws.opsRegistry, 'call')
      .mockResolvedValue(new FileStat({ name: 'm', type: FileType.DIRECTORY, fingerprint: 'v1' }))
    try {
      const mount = ws.namespace.mountFor('/m/a')
      await mount.indexStore.setDir('/m/a', [], null, { version: 'v1' })
      const rec = new Reconciler(ws.cache, ws.namespace, ws.opsRegistry)
      expect(await runInCommandScope(() => rec.mayServeListing(mount, '/m/a', 'v1'))).toBe(false)
      expect(stat).not.toHaveBeenCalled()
    } finally {
      vi.restoreAllMocks()
      await ws.close()
    }
  })
})

describe('a declarer checks what its fill stored', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it.each(Object.keys(HARNESSES).sort())('%s', async (name) => {
    await checkContract(name)
  })

  it('goes red on github seeding a tree sha', async () => {
    // github made to store each listing at a tree's sha while its check
    // answers the head commit: one kind of token on each side.
    const seed = Object.getOwnPropertyDescriptor(RAMIndexCacheStore.prototype, 'seed')
      ?.value as RAMIndexCacheStore['seed']
    vi.spyOn(RAMIndexCacheStore.prototype, 'seed').mockImplementation(function (
      this: RAMIndexCacheStore,
      entries,
      children,
      expiresAt,
      version,
    ) {
      seed.call(this, entries, children, expiresAt, version == null ? version : 'f'.repeat(40))
    })
    await expect(checkContract('github')).rejects.toThrow()
  })
})
