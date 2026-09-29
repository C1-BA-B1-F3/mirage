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
import { type FileGlob, fileAdmitted, parseFileGlobs } from './grep_select.ts'
import { SPECS } from '../spec/index.ts'
import { FlagView } from '../spec/flag_view.ts'

function rules(...pairs: [string, boolean][]): {
  fileGlobs: FileGlob[]
  excludeDir: string[]
  text: boolean
} {
  return {
    fileGlobs: pairs.map(([glob, admit]) => ({ glob, admit })),
    excludeDir: [],
    text: false,
  }
}

describe('fileAdmitted', () => {
  it('resolves rules in line order', () => {
    // Pinned against GNU grep 3.11: the last matching rule decides.
    expect(fileAdmitted('/d/a.txt', rules(['*.txt', true], ['*.txt', false]))).toBe(false)
    expect(fileAdmitted('/d/a.txt', rules(['*.txt', false], ['*.txt', true]))).toBe(true)
  })

  it('defaults a no-match file by the first rule', () => {
    // GNU 3.11: a file matching no rule is admitted only when the
    // first rule is an exclude.
    expect(fileAdmitted('/d/a.txt', rules(['*.log', false], ['*.zzz', true]))).toBe(true)
    expect(fileAdmitted('/d/a.txt', rules(['*.zzz', true], ['*.log', false]))).toBe(false)
  })

  it('admits everything with no rules', () => {
    expect(fileAdmitted('/d/a.bin', rules())).toBe(true)
  })
})

describe('parseFileGlobs', () => {
  it('reads dests in typed order', () => {
    const spec = SPECS.grep
    const excFirst = new FlagView({ exclude: ['notes.*'], include: ['*.tex'] }, spec)
    expect(parseFileGlobs(excFirst)).toEqual([
      { glob: 'notes.*', admit: false },
      { glob: '*.tex', admit: true },
    ])
    const incFirst = new FlagView({ include: ['*.tex'], exclude: ['notes.*'] }, spec)
    expect(parseFileGlobs(incFirst)).toEqual([
      { glob: '*.tex', admit: true },
      { glob: 'notes.*', admit: false },
    ])
  })
})
