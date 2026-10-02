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
import { getExtension } from './resolve.ts'

describe('getExtension', () => {
  it.each([
    ['file.txt', '.txt'],
    ['data/file.parquet', '.parquet'],
    ['folder/My Doc.gdoc.json', '.gdoc.json'],
    ['folder/My Sheet.gsheet.json', '.gsheet.json'],
    ['slides/My Slides.gslide.json', '.gslide.json'],
    ['INBOX/2026-05-03/Hi__18f.gmail.json', '.gmail.json'],
    ['Makefile', null],
    ['dir.d/file', null],
    [null, null],
  ])('reads %s as %s', (path, extension) => {
    expect(getExtension(path)).toBe(extension)
  })
})
