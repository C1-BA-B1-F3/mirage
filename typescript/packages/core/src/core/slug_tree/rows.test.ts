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

import { normalizeSlug, scalarString, virtualPath } from './rows.ts'

describe('normalizeSlug', () => {
  it('normalizes slashes', () => {
    expect(normalizeSlug('/guides//auth.md/', 'Chroma path')).toBe('/guides/auth.md')
  })

  it('names the backend in its refusals', () => {
    expect(() => normalizeSlug('//', 'Chroma path')).toThrow('Invalid empty Chroma path')
    expect(() => normalizeSlug('a/../b', 'Dify document slug')).toThrow(
      "Invalid Dify document slug segment: '..'",
    )
    expect(() => normalizeSlug('./a.md', 'Chroma path')).toThrow("Invalid Chroma path segment: '.'")
  })
})

describe('scalarString', () => {
  it('coerces primitives and rejects objects', () => {
    expect(scalarString('x')).toBe('x')
    expect(scalarString(5)).toBe('5')
    expect(scalarString(true)).toBe('true')
    expect(scalarString(null)).toBeNull()
    expect(scalarString({})).toBeNull()
  })
})

describe('virtualPath', () => {
  it('maps tree paths under the mount root', () => {
    expect(virtualPath('/', '/knowledge/')).toBe('/knowledge')
    expect(virtualPath('/guides', '/knowledge/')).toBe('/knowledge/guides')
    expect(virtualPath('/guides', '')).toBe('/guides')
  })
})
