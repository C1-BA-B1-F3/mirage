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

import { describe, expect, it } from 'vitest'
import { PathSpec } from '../../types.ts'
import { stripSlash } from '../../utils/slash.ts'
import type { RedisStoreLike } from '../../vfs/redis/store.ts'
import { lookupError } from './dest.ts'

function mkPath(virtual: string): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath: stripSlash(virtual), resolved: true })
}

// lookupError only asks which keys are files and which are directories, so
// two sets stand in for the store; the ops that route through it run
// against a live server in node/src/core/redis/core.test.ts.
function mkStore(): RedisStoreLike {
  const files = new Set(['/a.txt'])
  const dirs = new Set(['/', '/d'])
  return {
    hasFile: (path: string) => Promise.resolve(files.has(path)),
    hasDir: (path: string) => Promise.resolve(dirs.has(path)),
  } as unknown as RedisStoreLike
}

// GNU resolves a path one component at a time and stops at the first that
// is not a directory; measured against coreutils 9.7 (`cat a.txt/x` is "Not
// a directory", `cat nope/x` is "No such file or directory"). Mirrors
// test_dest.py.
describe('lookupError', () => {
  it.each([
    ['/a.txt/x', 'ENOTDIR'],
    ['/a.txt/x/y', 'ENOTDIR'],
    ['/d/x', 'ENOENT'],
    ['/nope/x', 'ENOENT'],
    ['/nope', 'ENOENT'],
  ])('stops at the first non-directory: %s is %s', async (key, code) => {
    const error = await lookupError(mkStore(), mkPath(key), key)
    expect(error.code).toBe(code)
    expect(error.virtualPath).toBe(key)
  })
})
