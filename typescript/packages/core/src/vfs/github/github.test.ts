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

import { afterEach, describe, expect, it, vi } from 'vitest'
import { MountMode } from '../../types.ts'
import { getTestParser } from '../../workspace/fixtures/workspace_fixture.ts'
import { Workspace } from '../../workspace/workspace/workspace.ts'
import { GitHubVFS } from './github.ts'

const DEC = new TextDecoder()
const TREE = [
  { path: 'top.txt', type: 'blob', sha: 'a', size: 2 },
  { path: 'empty', type: 'tree', sha: 'b' },
]

function offline(): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: string | URL | Request) => {
      const url = input instanceof Request ? input.url : String(input)
      const body = url.includes('/git/trees/')
        ? { tree: TREE, truncated: false }
        : { default_branch: 'main' }
      return Promise.resolve(
        new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } }),
      )
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('GitHubVFS', () => {
  for (const [mode, refusal] of [
    [MountMode.READ, 'Read-only file system'],
    [MountMode.WRITE, 'Operation not supported'],
  ] as const) {
    it(`refuses removing a tree entry on a ${mode} mount rather than missing it`, async () => {
      // rm, rmdir and unlink stat their operand first; a file `ls` lists
      // must meet the mount's refusal, -f or not, as GNU's does on a
      // filesystem that refuses the removal. Mirrors the Python test.
      offline()
      const vfs = await GitHubVFS.create({
        token: 't',
        owner: 'o',
        repo: 'r',
        ref: 'main',
        baseUrl: 'http://127.0.0.1:1',
      })
      const ws = new Workspace({ '/gh': vfs }, { mode, shellParser: await getTestParser() })
      try {
        const lines: Record<string, string> = {
          'rm /gh/top.txt': `rm: cannot remove '/gh/top.txt': ${refusal}\n`,
          'rm -f /gh/top.txt': `rm: cannot remove '/gh/top.txt': ${refusal}\n`,
          'rmdir /gh/empty': `rmdir: failed to remove '/gh/empty': ${refusal}\n`,
          'unlink /gh/top.txt': `unlink: cannot unlink '/gh/top.txt': ${refusal}\n`,
          'rm /gh/nope': "rm: cannot remove '/gh/nope': No such file or directory\n",
        }
        for (const [line, stderr] of Object.entries(lines)) {
          const result = await ws.shell(line)
          expect([result.exitCode, DEC.decode(result.stderr)]).toEqual([1, stderr])
        }
        const forced = await ws.shell('rm -f /gh/nope')
        expect([forced.exitCode, DEC.decode(forced.stderr)]).toEqual([0, ''])
        const listed = await ws.shell('ls /gh')
        expect(DEC.decode(listed.stdout)).toBe('empty\ntop.txt\n')
      } finally {
        await ws.close()
      }
    })
  }
})
