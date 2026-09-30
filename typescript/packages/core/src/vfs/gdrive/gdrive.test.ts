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

import { beforeEach, describe, expect, it, vi } from 'vitest'
import type * as DriveModule from '../../core/google/drive.ts'

vi.mock('../../core/google/drive.ts', async () => {
  const actual = await vi.importActual<typeof DriveModule>('../../core/google/drive.ts')
  const { driveModuleMock } = await import('../../core/gdrive/_test_util.ts')
  return driveModuleMock(actual)
})

import type { FakeDrive } from '../../core/gdrive/_test_util.ts'
import { resetFakeDrive } from '../../core/gdrive/_test_util.ts'
import { MountMode, ReadPolicy } from '../../types.ts'
import { getTestParser } from '../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../workspace/workspace/workspace.ts'
import { GDriveVFS } from './gdrive.ts'

const ENC = new TextEncoder()
const DEC = new TextDecoder()
let fake: FakeDrive

beforeEach(() => {
  fake = resetFakeDrive()
})

describe('GDriveVFS re-list cleanup', () => {
  // The first read of an expired folder can be a stat of one child; the
  // re-list it warms still has to find the sibling that went away, which it
  // cannot if the old listing is thrown out before warming.
  it('cleans up a sibling a stat-driven re-list drops', async () => {
    const dir = fake.folder('dir')
    fake.add('a.txt', dir, undefined, ENC.encode('alpha\n'))
    const b = fake.add('b.txt', dir, undefined, ENC.encode('bravo\n'))
    const ws = new Workspace(
      { '/gd': new GDriveVFS({ clientId: 'i', clientSecret: 's', refreshToken: 'r' }) },
      { mode: MountMode.READ, shellParser: await getTestParser() },
    )
    try {
      expect(DEC.decode((await ws.shell('ls /gd/dir')).stdout)).toBe('a.txt\nb.txt\n')
      // Seeded directly: the byte read goes through Drive's revision API,
      // which this fake does not serve, and only its leftover matters here.
      await ws.cache.set('/gd/dir/b.txt', ENC.encode('bravo\n'))
      await ws.namespace.setAttrs('/gd/dir/b.txt', { mode: 0o600 })
      expect(await ws.cache.exists('/gd/dir/b.txt')).toBe(true)
      fake.items.delete(b)
      await ws.registry.mountFor('/gd/dir').index.invalidate()
      expect(DEC.decode((await ws.shell('stat -c %n /gd/dir/a.txt')).stdout)).toBe(
        '/gd/dir/a.txt\n',
      )
      expect(ws.namespace.metaFor('/gd/dir/b.txt')).toBeNull()
      expect(await ws.cache.exists('/gd/dir/b.txt')).toBe(false)
    } finally {
      await ws.close()
    }
  })

  // Under fresh the next command re-lists on its own; its first read is a
  // stat of a sibling, and that re-list still has to find b.txt gone.
  it('re-lists under fresh on a stat and cleans up a dropped sibling', async () => {
    const dir = fake.folder('dir')
    fake.add('a.txt', dir, undefined, ENC.encode('alpha\n'))
    const b = fake.add('b.txt', dir, undefined, ENC.encode('bravo\n'))
    const ws = new Workspace(
      { '/gd': new GDriveVFS({ clientId: 'i', clientSecret: 's', refreshToken: 'r' }) },
      {
        mode: MountMode.READ,
        read: { policy: ReadPolicy.FRESH, ttl: 600 },
        shellParser: await getTestParser(),
      },
    )
    try {
      expect(DEC.decode((await ws.shell('ls /gd/dir')).stdout)).toBe('a.txt\nb.txt\n')
      await ws.cache.set('/gd/dir/b.txt', ENC.encode('bravo\n'))
      await ws.namespace.setAttrs('/gd/dir/b.txt', { mode: 0o600 })
      fake.items.delete(b)
      expect(DEC.decode((await ws.shell('stat -c %n /gd/dir/a.txt')).stdout)).toBe(
        '/gd/dir/a.txt\n',
      )
      expect(ws.namespace.metaFor('/gd/dir/b.txt')).toBeNull()
      expect(await ws.cache.exists('/gd/dir/b.txt')).toBe(false)
    } finally {
      await ws.close()
    }
  })
})
