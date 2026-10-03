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
import { FileHandle, writeRuns } from './file_handle.ts'
import { NO_WRITE } from './flush.ts'

const enc = new TextEncoder()

describe('FileHandle', () => {
  it('positions by append and seeds the flush facts', () => {
    const h = FileHandle.opened('/f', enc.encode('abc'), { writable: true, append: true })
    expect([h.pos, h.baseLen, h.lowWrite, h.dirty]).toEqual([3, 3, NO_WRITE, false])
    const fresh = FileHandle.opened('/f', enc.encode('abc'), { writable: false, append: false })
    expect(fresh.pos).toBe(0)
    expect(fresh.writable).toBe(false)
  })

  it('reads forward and never moves the position backward', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: false, append: false })
    expect(h.read(2)).toEqual(enc.encode('he'))
    expect(h.read(null)).toEqual(enc.encode('llo'))
    h.pos = 99
    expect(h.read(4)).toEqual(new Uint8Array())
    expect(h.pos).toBe(99)
  })

  it('preads without moving the position', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: false, append: false })
    expect(h.pread(1, 3)).toEqual(enc.encode('ell'))
    expect(h.pos).toBe(0)
  })

  it('writes extend, zero-fill, and track the flush facts', () => {
    const h = FileHandle.opened('/f', enc.encode('abc'), { writable: true, append: true })
    h.write(enc.encode('XY'))
    expect(h.buf).toEqual(enc.encode('abcXY'))
    expect(h.dirty).toBe(true)
    h.pwrite(7, enc.encode('Z'))
    expect(h.buf).toEqual(new Uint8Array([...enc.encode('abcXY'), 0, 0, ...enc.encode('Z')]))
    expect(h.lowWrite).toBe(3)
    expect(h.flushPlan()).toEqual([
      'append',
      new Uint8Array([...enc.encode('XY'), 0, 0, ...enc.encode('Z')]),
    ])
    h.pwrite(0, enc.encode('q'))
    expect(h.flushPlan()[0]).toBe('write')
  })

  it('seek answers null for a bad whence or a negative target', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: false, append: false })
    expect(h.seek(-2, 2)).toBe(3)
    expect(h.seek(-9, 0)).toBeNull()
    expect(h.seek(0, 7)).toBeNull()
    expect(h.pos).toBe(3)
  })

  it('truncate rewrites history in both directions', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: true, append: true })
    h.truncate(2)
    expect(h.buf).toEqual(enc.encode('he'))
    expect(h.lowWrite).toBe(0)
    h.truncate(4)
    expect(h.buf).toEqual(new Uint8Array([...enc.encode('he'), 0, 0]))
    expect(h.flushPlan()[0]).toBe('write')
  })

  it('eof tracks the position', () => {
    const h = FileHandle.opened('/f', enc.encode('ab'), { writable: false, append: false })
    expect(h.eof).toBe(false)
    h.read(null)
    expect(h.eof).toBe(true)
  })

  it('appending many small writes stays linear and preserves content', () => {
    const h = FileHandle.opened('/f', new Uint8Array(), { writable: true, append: true })
    const parts: Uint8Array[] = []
    for (let i = 0; i < 5000; i++) {
      const chunk = enc.encode(`chunk${String(i)};`)
      parts.push(chunk)
      h.write(chunk)
    }
    const expected = new Uint8Array(parts.reduce((n, p) => n + p.length, 0))
    let at = 0
    for (const p of parts) {
      expected.set(p, at)
      at += p.length
    }
    expect(h.buf).toEqual(expected)
    expect(h.size).toBe(expected.length)
    expect(h.eof).toBe(true)
    expect(h._growCount).toBeLessThanOrEqual(Math.ceil(Math.log2(h.size)) + 1)
    const [kind, tail] = h.flushPlan()
    expect(kind).toBe('write')
    expect(tail).toEqual(expected)
  })

  it('pwrite after truncate zero-fills the gap', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: true, append: false })
    h.truncate(2)
    h.pwrite(3, enc.encode('X'))
    expect(h.buf).toEqual(new Uint8Array([...enc.encode('he'), 0, ...enc.encode('X')]))
    expect(h.size).toBe(4)
  })

  it('pread never reads past the logical end', () => {
    const h = FileHandle.opened('/f', enc.encode('abc'), { writable: true, append: false })
    h.pwrite(5, enc.encode('X'))
    expect(h.size).toBe(6)
    expect(h.pread(4, 10)).toEqual(new Uint8Array([0, ...enc.encode('X')]))
  })

  it('a gap write keeps a payload that views the dropped tail', () => {
    const h = FileHandle.opened('/f', enc.encode('hello'), { writable: true, append: false })
    const saved = h.buf
    h.truncate(1)
    h.pwrite(3, saved.subarray(1, 3))
    expect(h.buf).toEqual(new Uint8Array([...enc.encode('h'), 0, 0, ...enc.encode('el')]))
  })

  it('never writes into the array it opened over', () => {
    const stored = enc.encode('hello world')
    const h = FileHandle.opened('/f', stored, { writable: true, append: false })
    h.write(enc.encode('XY'))
    h.truncate(0)
    h.pwrite(0, enc.encode('Z'))
    expect(new TextDecoder().decode(stored)).toBe('hello world')
    expect(new TextDecoder().decode(h.buf)).toBe('Z')
  })
})

describe('writeRuns', () => {
  it('folds a sequential stream into one run', () => {
    expect(
      writeRuns([
        [0, enc.encode('ab')],
        [2, enc.encode('cd')],
        [4, enc.encode('e')],
      ]),
    ).toEqual([[0, enc.encode('abcde')]])
    expect(
      writeRuns([
        [0, enc.encode('new')],
        [1, enc.encode('O')],
      ]),
    ).toEqual([[0, enc.encode('nOw')]])
    expect(writeRuns([])).toEqual([])
  })

  it('keeps scattered writes apart and in order', () => {
    expect(
      writeRuns([
        [0, enc.encode('a')],
        [10, enc.encode('b')],
      ]),
    ).toEqual([
      [0, enc.encode('a')],
      [10, enc.encode('b')],
    ])
    expect(
      writeRuns([
        [4, enc.encode('xy')],
        [0, enc.encode('abcdef')],
      ]),
    ).toEqual([
      [4, enc.encode('xy')],
      [0, enc.encode('abcdef')],
    ])
  })
})
