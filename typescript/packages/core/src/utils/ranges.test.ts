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

import {
  isUnsatisfiableRange,
  rangeHeader,
  sliceWindow,
  spliceWindow,
  windowFor,
  windowIfUnranged,
  windowOf,
} from './ranges.js'

const ENC = new TextEncoder()
const DEC = new TextDecoder()
const DATA = ENC.encode('0123456789')

describe('rangeHeader', () => {
  it('needs no header for the whole file', () => {
    expect(rangeHeader(0, null)).toBeNull()
  })

  it('is inclusive at both ends of a bounded window', () => {
    // HTTP ranges name the last byte, not the one after it, so a 4-byte window
    // from 2 ends at 5.
    expect(rangeHeader(2, 4)).toBe('bytes=2-5')
  })

  it('leaves the end blank on an open-ended window', () => {
    expect(rangeHeader(7, null)).toBe('bytes=7-')
  })

  it('names the same offset twice for a single byte', () => {
    expect(rangeHeader(3, 1)).toBe('bytes=3-3')
  })

  it('refuses a negative offset', () => {
    expect(() => rangeHeader(-1, 4)).toThrow(RangeError)
  })

  it('refuses a negative size', () => {
    expect(() => rangeHeader(0, -4)).toThrow(RangeError)
  })

  it('refuses a zero-length window', () => {
    // bytes=2--1 is malformed and no header means the opposite of what was
    // asked, so the caller has to short-circuit instead.
    expect(() => rangeHeader(2, 0)).toThrow(RangeError)
  })
})

describe('spliceWindow', () => {
  it('keeps both sides of the window', () => {
    expect(DEC.decode(spliceWindow(DATA, 2, ENC.encode('ab')))).toBe('01ab456789')
    expect(DEC.decode(spliceWindow(DATA, 8, ENC.encode('xyz')))).toBe('01234567xyz')
  })

  it('fills a gap past the end with zeros', () => {
    expect([...spliceWindow(ENC.encode('ab'), 4, ENC.encode('z'))]).toEqual([97, 98, 0, 0, 122])
    expect(DEC.decode(spliceWindow(new Uint8Array(), 0, ENC.encode('new')))).toBe('new')
  })
})

describe('sliceWindow', () => {
  it('slices a bounded window', () => {
    expect(DEC.decode(sliceWindow(DATA, 2, 4))).toBe('2345')
  })

  it('slices to the end', () => {
    expect(DEC.decode(sliceWindow(DATA, 7, null))).toBe('789')
  })

  it('slices the whole thing', () => {
    expect(sliceWindow(DATA, 0, null)).toEqual(DATA)
  })

  it('stops at the end when the window runs past it', () => {
    expect(DEC.decode(sliceWindow(DATA, 8, 99))).toBe('89')
  })

  it('is empty from past the end', () => {
    expect(sliceWindow(DATA, 99, 4)).toEqual(new Uint8Array(0))
  })
})

describe('isUnsatisfiableRange', () => {
  // The point of the predicate: a POSIX read at or past EOF is empty, an HTTP
  // store answers 416, and no two clients spell the refusal the same way.
  it('recognizes the aws sdk shape', () => {
    const err = Object.assign(new Error('InvalidRange'), {
      name: 'InvalidRange',
      $metadata: { httpStatusCode: 416 },
    })
    expect(isUnsatisfiableRange(err)).toBe(true)
  })

  it('recognizes a bare status, with no code at all', () => {
    expect(isUnsatisfiableRange({ status: 416 })).toBe(true)
    expect(isUnsatisfiableRange({ statusCode: 416 })).toBe(true)
  })

  it('recognizes the code without a status', () => {
    expect(isUnsatisfiableRange(Object.assign(new Error('nope'), { Code: 'InvalidRange' }))).toBe(
      true,
    )
  })

  it('falls back to the status line a plain http store leaves', () => {
    expect(isUnsatisfiableRange(new Error('416 Range Not Satisfiable'))).toBe(true)
  })

  it('recognizes the seek a reader without a header raises', () => {
    // hf and nextcloud open an OpenDAL file object and seek, so a window
    // past EOF surfaces as the seek failing rather than as a status.
    expect(
      isUnsatisfiableRange(new Error('invalid seek to a position beyond the end of the range')),
    ).toBe(true)
  })

  it('does not swallow an ordinary seek failure', () => {
    expect(isUnsatisfiableRange(new Error('invalid seek: bad whence'))).toBe(false)
  })

  it('does not swallow a real failure', () => {
    // Anything broader here would turn a missing object or a denied request
    // into a silent empty read, which is the bug this guards against.
    const notFound = Object.assign(new Error('NoSuchKey'), {
      name: 'NoSuchKey',
      $metadata: { httpStatusCode: 404 },
    })
    expect(isUnsatisfiableRange(notFound)).toBe(false)
    expect(isUnsatisfiableRange(new Error('AccessDenied'))).toBe(false)
    expect(isUnsatisfiableRange({ status: 500 })).toBe(false)
    expect(isUnsatisfiableRange(null)).toBe(false)
    expect(isUnsatisfiableRange(undefined)).toBe(false)
  })
})

const bytes = (s: string): Uint8Array => new TextEncoder().encode(s)
const text = (b: Uint8Array): string => new TextDecoder().decode(b)

describe('windowIfUnranged', () => {
  it('trusts a 206 as already the window', () => {
    expect(text(windowIfUnranged(bytes('234'), 206, 2, 3))).toBe('234')
  })

  // RFC 9110 lets a server answer the whole representation to a Range
  // request, and a CDN in front of one may. Without this the caller gets the
  // entire file for what it asked to be a window.
  it('slices a 200 because the server ignored the range', () => {
    expect(text(windowIfUnranged(bytes('0123456789'), 200, 2, 3))).toBe('234')
  })

  it('slices a 200 to EOF from the offset', () => {
    expect(text(windowIfUnranged(bytes('0123456789'), 200, 7, null))).toBe('789')
  })

  it('answers empty for a 200 whose offset is past EOF', () => {
    expect(text(windowIfUnranged(bytes('abc'), 200, 500, 10))).toBe('')
  })
})

describe('isUnsatisfiableRange on a WebDAV 416', () => {
  // OpenDAL puts the whole response in the message, so the status is only
  // readable inside the string and the exception name has no spaces for the
  // spaced spelling to match.
  it('recognises the SabreDAV shape nextcloud answers with', () => {
    expect(
      isUnsatisfiableRange(
        new Error(
          `Unexpected (permanent) at read, context: { uri: http://h/x, response: Parts { status: 416 } } <d:error><s:exception>Sabre\\DAV\\Exception\\RequestedRangeNotSatisfiable</s:exception><s:message>The start offset (99) exceeded the size of the entity (3)</s:message></d:error>`,
        ),
      ),
    ).toBe(true)
  })

  it('still refuses an unrelated permanent error', () => {
    expect(isUnsatisfiableRange(new Error('Unexpected (permanent) at read, status: 500'))).toBe(
      false,
    )
  })
})

describe('windowFor', () => {
  it('is undefined for a whole-file read', () => {
    expect(windowFor(0, null)).toBeUndefined()
  })

  it('carries both numbers otherwise', () => {
    expect(windowFor(2, 3)).toEqual({ offset: 2, size: 3 })
    expect(windowFor(7, null)).toEqual({ offset: 7, size: null })
  })
})

describe('windowOf', () => {
  it('trusts a 206 body', () => {
    expect(DEC.decode(windowOf(ENC.encode('234'), 206, { offset: 2, size: 3 }))).toBe('234')
  })

  it('slices a 200 body', () => {
    expect(DEC.decode(windowOf(DATA, 200, { offset: 2, size: 3 }))).toBe('234')
  })

  // A reader with no window passes undefined, and the offset a slice would
  // otherwise apply is not zero by accident but absent.
  it('leaves a whole-file read alone', () => {
    expect(DEC.decode(windowOf(DATA, 200, undefined))).toBe('0123456789')
  })
})

const HF_INVALID_CONTENT_RANGE =
  'Unexpected (permanent) at read, context: { value: bytes 99-2/3, ' +
  'called: BytesContentRange::from_str, service: hf, path: range_past.txt, ' +
  'range: 99-103 } => header content range is invalid: end is less than start'

describe('isUnsatisfiableRange on huggingface', () => {
  // Past the end huggingface echoes a range whose end precedes its start and
  // OpenDAL refuses to parse it, so no status ever surfaces.
  it('reads a backwards content range as past the end', () => {
    expect(isUnsatisfiableRange(new Error(HF_INVALID_CONTENT_RANGE))).toBe(true)
  })

  it('still raises on a malformed header with no such wording', () => {
    expect(isUnsatisfiableRange(new Error('header content range is invalid: junk'))).toBe(false)
  })
})
