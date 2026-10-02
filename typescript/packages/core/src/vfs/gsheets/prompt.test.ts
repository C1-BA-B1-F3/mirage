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
import { PROMPT, WRITE_PROMPT } from './prompt.ts'

describe('PROMPT', () => {
  it('renders prefix and includes buckets, structure, jq paths, read command', () => {
    const rendered = PROMPT.replace(/\{prefix\}/g, '/gsheets')
    expect(rendered).toContain('owned/')
    expect(rendered).toContain('shared/')
    expect(rendered).toContain('shared with you by others')
    expect(rendered).toContain('still in owned/')
    expect(rendered).toContain('gsheet.json structure')
    expect(rendered).toContain('.sheets[].properties.title')
    expect(rendered).toContain('gws sheets read')
  })
})

describe('WRITE_PROMPT', () => {
  it('matches actual command flag signatures', () => {
    expect(WRITE_PROMPT).toContain('gws sheets write')
    expect(WRITE_PROMPT).toContain('gws sheets append')
    expect(WRITE_PROMPT).toContain('--spreadsheet')
    expect(WRITE_PROMPT).toContain('--range')
    expect(WRITE_PROMPT).toContain('--values')
    expect(WRITE_PROMPT).toContain('--json-values')
    expect(WRITE_PROMPT).toContain('gws sheets --help')
  })

  it('documents rm', () => {
    expect(WRITE_PROMPT).toContain('rm ')
    expect(WRITE_PROMPT).toContain('.gsheet.json')
  })
})
