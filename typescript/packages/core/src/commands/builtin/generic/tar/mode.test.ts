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
import { isCreateMode } from './mode.ts'

describe('isCreateMode', () => {
  it('turns on for -c and --create', () => {
    expect(isCreateMode(['-czf', 'out.tgz', 'dir'])).toBe(true)
    expect(isCreateMode(['--create', '-f', 'out.tar', 'dir'])).toBe(true)
  })

  it('stays off for extract and list', () => {
    expect(isCreateMode(['-xzf', 'a.tgz', './m/x.json'])).toBe(false)
    expect(isCreateMode(['-tzf', 'a.tgz'])).toBe(false)
  })

  it('reads only the first word as a dashless cluster', () => {
    expect(isCreateMode(['cf', 'a.tar', 'd'])).toBe(true)
    expect(isCreateMode(['-xf', 'a.tar', 'crate'])).toBe(false)
  })

  it('never reads a long option as a cluster', () => {
    expect(isCreateMode(['--exclude', 'c', '-xf', 'a.tar'])).toBe(false)
  })

  it('stops at the option terminator', () => {
    // GNU reads everything after -- as an operand: `-c` and even `-C
    // out` name members there (`tar: -C: Not found in archive`).
    expect(isCreateMode(['-xf', 'a.tar', '--', '-c'])).toBe(false)
    expect(isCreateMode(['-xf', 'a.tar', '--', '--create'])).toBe(false)
    expect(isCreateMode(['-cf', 'a.tar', '--', '-c'])).toBe(true)
  })
})

describe('isCreateMode on long words', () => {
  // Mirrors python's test_a_long_word_reads_as_tars_getopt_long_reads_it.
  it.each([
    [['--crea', '-f', 'a.tar', 'd'], true],
    [['--cr=x'], true],
    // Ambiguous in tar's own table, so no mode at all.
    [['--c', '-f', 'a.tar'], false],
    [['--get', '-f', 'a.tar'], false],
  ])('%j reads as tar reads it', (argv, create) => {
    expect(isCreateMode(argv)).toBe(create)
  })
})
