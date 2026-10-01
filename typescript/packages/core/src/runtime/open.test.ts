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
import { parseMode } from './handles/mode.ts'
import { applyOpen, type OpenSurface } from './open.ts'
import type { VFSEntry, VFSStat } from './vfs.ts'

const F = '/data/f'

interface Shape {
  files?: string[]
  dirs?: string[]
  implied?: string[]
  links?: string[]
}

// A filesystem for the rule to land on, recording every effect. An
// implied directory lists but has no row, the root above a nested
// mount; a dangling link has a row only for a no-follow stat.
function world(shape: Shape): OpenSurface & { effects: string[] } {
  const effects: string[] = []
  const has = (list: string[] | undefined, path: string): boolean => list?.includes(path) === true
  return {
    effects,
    statOrNull: (path: string, nofollow = false): Promise<VFSStat | null> => {
      if (has(shape.files, path))
        return Promise.resolve({ size: 1, isDir: false, mode: 0o100644, mtimeMs: 0 })
      if (has(shape.dirs, path))
        return Promise.resolve({ size: 0, isDir: true, mode: 0o40755, mtimeMs: 0 })
      if (has(shape.links, path) && nofollow) {
        return Promise.resolve({ size: 8, isDir: false, mode: 0o120777, mtimeMs: 0, isLink: true })
      }
      return Promise.resolve(null)
    },
    listingOrNull: (path: string): Promise<VFSEntry[] | null> =>
      Promise.resolve(has(shape.dirs, path) || has(shape.implied, path) ? [] : null),
    create: (path: string): Promise<void> => {
      effects.push(`create ${path}`)
      return Promise.resolve()
    },
    truncate: (path: string): Promise<void> => {
      effects.push(`truncate ${path}`)
      return Promise.resolve()
    },
  }
}

describe('applyOpen', () => {
  it.each<[string, Shape, string[], boolean, string | null]>([
    ['r', { files: [F] }, [], true, null],
    ['r', {}, [], false, 'ENOENT'],
    ['r', { dirs: [F] }, [], false, 'EISDIR'],
    ['r', { implied: [F] }, [], false, 'EISDIR'],
    ['r', { links: [F] }, [], false, 'ENOENT'],
    ['w', { files: [F] }, [`truncate ${F}`], false, null],
    ['w', {}, [`create ${F}`], false, null],
    ['w', { implied: [F] }, [], false, 'EISDIR'],
    ['a', { files: [F] }, [], true, null],
    ['a', {}, [`create ${F}`], false, null],
    ['a', { implied: [F] }, [], false, 'EISDIR'],
    ['wx', { files: [F] }, [], false, 'EEXIST'],
    ['wx', { links: [F] }, [], false, 'EEXIST'],
    ['wx', { implied: [F] }, [], false, 'EEXIST'],
    ['wx', {}, [`create ${F}`], false, null],
  ])(
    "lands open '%s' over %j before any byte moves",
    async (mode, shape, effect, kept, refusal) => {
      const surface = world(shape)
      if (refusal === null) {
        expect((await applyOpen(surface, F, parseMode(mode))) !== null).toBe(kept)
      } else {
        await expect(applyOpen(surface, F, parseMode(mode))).rejects.toMatchObject({
          code: refusal,
        })
      }
      expect(surface.effects).toEqual(effect)
    },
  )
})
