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

import { afterEach, expect, it, vi } from 'vitest'
import type { GitHubAccessor } from '../../../accessor/github.ts'
import { FileStat, FileType, PathSpec } from '../../../types.ts'
import { eacces } from '../../../utils/errors.ts'
import { materialize } from '../../../io/types.ts'
import { GITHUB_IO } from './io.ts'
import { GITHUB_DU } from './du.ts'

vi.mock('../../../core/github/tree.ts', () => ({
  ensureLiveTree: vi.fn().mockResolvedValue(undefined),
}))

afterEach(() => vi.restoreAllMocks())

it('truncated du preserves directory rows and permission errors', async () => {
  vi.spyOn(GITHUB_IO, 'readdir').mockImplementation((_a, p) => {
    if (p.virtual === '/db/sealed') return Promise.reject(eacces(p.virtual))
    return Promise.resolve(
      p.virtual === '/db' ? ['/db/a', '/db/empty', '/db/sealed', '/db/walled'] : [],
    )
  })
  vi.spyOn(GITHUB_IO, 'stat').mockImplementation((_a, p) => {
    if (p.virtual === '/db/walled') return Promise.reject(eacces(p.virtual))
    return Promise.resolve(
      new FileStat({
        name: p.virtual,
        type: p.virtual === '/db/a' ? FileType.FILE : FileType.DIRECTORY,
        size: p.virtual === '/db/a' ? 3 : null,
      }),
    )
  })
  const cmd = GITHUB_DU[0]
  if (cmd === undefined) throw new Error('du not registered')
  const result = await cmd.fn(
    { truncated: true } as GitHubAccessor,
    [PathSpec.fromStrPath('/db')],
    [],
    { stdin: null, flags: {}, filetypeFns: null, cwd: '/' },
  )
  if (result === null) throw new Error('du returned nothing')
  const [out, io] = result
  const bytes =
    out === null ? new Uint8Array() : out instanceof Uint8Array ? out : await materialize(out)
  expect(new TextDecoder().decode(bytes)).toBe('0\t/db/empty\n0\t/db/sealed\n3\t/db\n')
  expect(io.exitCode).toBe(1)
  expect(await io.stderrStr()).toBe(
    "du: cannot read directory '/db/sealed': Permission denied\n" +
      "du: cannot read directory '/db/walled': Permission denied\n",
  )
})
