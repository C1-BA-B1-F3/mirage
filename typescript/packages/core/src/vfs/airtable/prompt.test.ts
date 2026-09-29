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
import { AirtableVFS } from './airtable.ts'
import { AIRTABLE_PROMPT, AIRTABLE_WRITE_PROMPT } from './prompt.ts'

describe('AIRTABLE_PROMPT', () => {
  it('maps every file and the record shape', () => {
    const rendered = AIRTABLE_PROMPT.replace(/\{prefix\}/g, '/airtable')
    for (const name of ['base.json', 'table.json', 'records.jsonl', 'views/']) {
      expect(rendered).toContain(name)
    }
    expect(rendered).toContain('record_id, created_time, and fields')
    expect(rendered).toContain('max_read_records')
    expect(rendered).toContain('head -n 20 /airtable/bases/')
    expect(rendered).not.toMatch(/[{}]/)
  })
})

describe('AIRTABLE_PROMPT and the CLI', () => {
  it('points at the CLI for what a file cannot do', () => {
    const rendered = AIRTABLE_PROMPT.replace(/\{prefix\}/g, '/airtable')
    expect(rendered).toContain('airtable record list --formula or --view')
    expect(rendered).toContain('airtable record get')
    expect(rendered).toContain('airtable comment list')
  })

  it('names the write verbs and the help', () => {
    const rendered = AIRTABLE_WRITE_PROMPT.replace(/\{prefix\}/g, '/airtable')
    for (const verb of ['record create', 'record update', 'comment add']) {
      expect(rendered).toContain(`airtable ${verb} --base <base-id> --table <table-id>`)
    }
    expect(rendered).toContain('/airtable/bases/<base>/<table>/records.jsonl')
    expect(rendered.trimEnd().endsWith('See airtable --help for every verb.')).toBe(true)
    expect(new AirtableVFS({ token: 't' }).writePrompt).toBe(AIRTABLE_WRITE_PROMPT)
  })
})
