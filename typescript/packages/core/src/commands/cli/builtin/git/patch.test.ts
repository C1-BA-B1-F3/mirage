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

import git from 'isomorphic-git'
import { beforeAll, expect, it } from 'vitest'

import { IOResult } from '../../../../io/types.ts'
import { OpsRegistry } from '../../../../ops/registry.ts'
import { MountMode } from '../../../../types.ts'
import { RAMVFS } from '../../../../vfs/ram/ram.ts'
import { Workspace } from '../../../../workspace/workspace/workspace.ts'
import { filePatch, shortOid } from './patch.ts'
import { openRepo, repoArgs, type Repo } from './repo.ts'
import type { TreeEntry } from './tree.ts'
import type { Dispatch } from './types.ts'

const MODE = '100644'
const SYMLINK = '120000'
const WIDTH = 7
const ENC = new TextEncoder()

let repo: Repo

beforeAll(async () => {
  const ram = new RAMVFS()
  const registry = new OpsRegistry()
  registry.registerVfs(ram)
  const ws = new Workspace({ '/repo': ram }, { mode: MountMode.WRITE, ops: registry })
  const dispatch: Dispatch = async (op, path, args = [], kwargs = {}) => [
    await ws.dispatch(op, path.virtual, args, kwargs),
    new IOResult(),
  ]
  repo = await openRepo(dispatch, {
    gitdir: '/repo/.git',
    commondir: '/repo/.git',
    worktree: '/repo',
    mountRoot: '/repo',
  })
})

async function blob(mode: string, text: string): Promise<TreeEntry> {
  return { mode, oid: await git.writeBlob({ ...repoArgs(repo), blob: ENC.encode(text) }) }
}

it('pads a missing side with zeros', () => {
  expect(shortOid(null, WIDTH)).toBe('0000000')
  expect(shortOid({ mode: MODE, oid: `4cb29ea${'0'.repeat(33)}` }, WIDTH)).toBe('4cb29ea')
})

// Every expected patch below is pinned against git 2.54.

it('writes a changed line as one hunk with its context', async () => {
  const before = await blob(MODE, 'one\ntwo\nthree\n')
  const after = await blob(MODE, 'one\nTWO\nthree\n')
  expect(await filePatch(repo, 'f.txt', 'f.txt', before, after, null, WIDTH)).toBe(
    'diff --git a/f.txt b/f.txt\n' +
      'index 4cb29ea..ddc897f 100644\n' +
      '--- a/f.txt\n' +
      '+++ b/f.txt\n' +
      '@@ -1,3 +1,3 @@\n' +
      ' one\n' +
      '-two\n' +
      '+TWO\n' +
      ' three\n',
  )
})

it('marks a missing final newline on each side', async () => {
  const before = await blob(MODE, 'keep\nlast')
  const after = await blob(MODE, 'keep\nend')
  const patch = await filePatch(repo, 'g.txt', 'g.txt', before, after, null, WIDTH)
  expect(patch.slice(patch.indexOf('@@'))).toBe(
    '@@ -1,2 +1,2 @@\n' +
      ' keep\n' +
      '-last\n' +
      '\\ No newline at end of file\n' +
      '+end\n' +
      '\\ No newline at end of file\n',
  )
})

it('gives a pure rename no index line', async () => {
  const entry = await blob(MODE, 'keep\nend')
  expect(await filePatch(repo, 'h.txt', 'g.txt', entry, entry, 100, WIDTH)).toBe(
    'diff --git a/g.txt b/h.txt\n' +
      'similarity index 100%\n' +
      'rename from g.txt\n' +
      'rename to h.txt\n',
  )
})

it('splits a file turned symlink into a deletion and a creation', async () => {
  const before = await blob(MODE, 'one\nTWO\nthree\n')
  const after = await blob(SYMLINK, 'target')
  expect(await filePatch(repo, 'f.txt', 'f.txt', before, after, null, WIDTH)).toBe(
    'diff --git a/f.txt b/f.txt\n' +
      'deleted file mode 100644\n' +
      'index ddc897f..0000000\n' +
      '--- a/f.txt\n' +
      '+++ /dev/null\n' +
      '@@ -1,3 +0,0 @@\n' +
      '-one\n' +
      '-TWO\n' +
      '-three\n' +
      'diff --git a/f.txt b/f.txt\n' +
      'new file mode 120000\n' +
      'index 0000000..1de5659\n' +
      '--- /dev/null\n' +
      '+++ b/f.txt\n' +
      '@@ -0,0 +1 @@\n' +
      '+target\n' +
      '\\ No newline at end of file\n',
  )
})
