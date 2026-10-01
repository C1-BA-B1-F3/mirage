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
import { describe, expect, it, vi } from 'vitest'
import { runInCommandScope } from '@struktoai/mirage-core/cache/index/scope'
import { FileStat, FileType, MountMode, ReadPolicy } from '@struktoai/mirage-core/types'
import { RAMVFS } from '@struktoai/mirage-core/vfs/ram/ram'
import { Reconciler } from '@struktoai/mirage-core/workspace/reconcile'
import { Workspace } from '@struktoai/mirage-core/workspace/workspace/workspace'
import { knownVfsNames } from './registry.ts'

const SPEC_VFS = resolve(
  fileURLToPath(import.meta.url),
  '../../../../../../spec/typescript/node/vfs.json',
)

const KINDS = ['none', 'mount', 'folder']

// A declarer gets a harness proving that its check and its fill agree, so
// the gate's stat and the stored version are one kind of token. None ships
// yet; each declaring backend adds its row with its declaration.
const HARNESSES: Record<string, string> = {}

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
    expect(Object.keys(HARNESSES).sort()).toEqual([])
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
