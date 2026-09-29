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

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { start } from './server/kit/typescript/index.ts'
import type { JsonValue } from './server/kit/typescript/index.ts'
import { airtableFake } from './server/airtable/fake.ts'

type Json = Record<string, JsonValue>

interface Call {
  task: string
  tool: string
  args: Json
  reply: string
  skip?: string
}

interface Corpus {
  workspace: Json
  calls: Call[]
}

const CORPUS = fileURLToPath(new URL('./truth/airtable_atlas.json', import.meta.url))

// What the server requests for each tool, and the key of the reply it prints
// (`build/index.js`): axios under `baseURL` https://api.airtable.com/v0, whose
// path is joined unescaped and then parsed as a URL, as `new URL` does here.
function request(call: Call): { path: string; params: Record<string, string>; key?: string } {
  const a = call.args
  const base = String(a.base_id)
  const table = String(a.table_name)
  switch (call.tool) {
    case 'list_bases':
      return { path: '/meta/bases', params: {}, key: 'bases' }
    case 'list_tables':
      return { path: `/meta/bases/${base}/tables`, params: {}, key: 'tables' }
    case 'list_records':
      return {
        path: `/${base}/${table}`,
        params: a.max_records ? { maxRecords: String(a.max_records) } : {},
        key: 'records',
      }
    case 'search_records':
      return {
        path: `/${base}/${table}`,
        params: { filterByFormula: `{${String(a.field_name)}} = "${String(a.value)}"` },
        key: 'records',
      }
    case 'get_record':
      return { path: `/${base}/${table}/${String(a.record_id)}`, params: {} }
    default:
      throw new Error(`Unsupported tool ${call.tool}`)
  }
}

// Every record id a listing pages through, following each offset.
async function listIds(url: URL, token: string): Promise<string[]> {
  const out: string[] = []
  for (;;) {
    const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    const body = (await response.json()) as Json
    if (!response.ok) throw new Error(`${url.pathname}: ${JSON.stringify(body)}`)
    out.push(...(body.records as Json[]).map((r) => String(r.id)))
    if (typeof body.offset !== 'string') return out
    url.searchParams.set('offset', body.offset)
  }
}

/**
 * Replay MCP-Atlas's recorded Airtable calls against the fake, seeded with the
 * base they were recorded against (scripts/gen_airtable_atlas.py).
 *
 * The server, @felores/airtable-mcp-server@0.3.0, sends each tool as one GET
 * and answers with JSON.stringify(<one key of the reply>, null, 2), so a reply
 * is the fake's body through the same two steps, compared byte for byte.
 *
 * Then every table whole, both ways the recordings imply: with no view in
 * record-id order, which each recorded list and search answered in, and
 * through the Grid view in the base's own row order, which the share read.
 */
async function main(): Promise<void> {
  const corpus = JSON.parse(readFileSync(CORPUS, 'utf8')) as Corpus
  const token = String(((corpus.workspace.tokens as Json[])[0] as Json).token)
  const root = mkdtempSync(join(tmpdir(), 'airtable-atlas-'))
  mkdirSync(join(root, 'airtable'))
  writeFileSync(join(root, 'airtable', 'atlas.json'), JSON.stringify(corpus.workspace))
  const fake = await start(airtableFake, 0, 'atlas', root)
  let failed = 0
  let skipped = 0
  try {
    for (const [i, call] of corpus.calls.entries()) {
      const label = `${String(i).padStart(3, '0')} ${call.task} ${call.tool}`
      if (call.skip !== undefined) {
        skipped += 1
        process.stdout.write(`  skip ${label}  [${call.skip}]\n`)
        continue
      }
      const { path, params, key } = request(call)
      const url = new URL(`${fake.endpoint}/v0${path}`)
      for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v)
      const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      const body = (await response.json()) as Json
      const reply = JSON.stringify(key === undefined ? body : (body[key] ?? body), null, 2)
      if (response.ok && reply === call.reply) {
        process.stdout.write(`  ok   ${label}\n`)
      } else {
        failed += 1
        process.stdout.write(
          `  FAIL ${label} ${JSON.stringify(call.args)}\n` +
            `  got (${String(response.status)}): ${JSON.stringify(reply).slice(0, 600)}\n` +
            `  want: ${JSON.stringify(call.reply).slice(0, 600)}\n`,
        )
      }
    }
    const base = ((corpus.workspace.bases as Json[])[0] ?? {}) as Json
    for (const table of base.tables as Json[]) {
      const rows = (table.records as Json[]).map((r) => String(r.id))
      const grid = String(((table.views as Json[])[0] ?? {}).id)
      for (const [label, view, want] of [
        ['no view, record-id order', null, [...rows].sort()],
        ['Grid view, the base row order', grid, rows],
      ] as const) {
        const url = new URL(`${fake.endpoint}/v0/${String(base.id)}/${String(table.id)}`)
        if (view !== null) url.searchParams.set('view', view)
        const got = await listIds(url, token)
        const same = got.length === want.length && got.every((id, i) => id === want[i])
        if (!same) failed += 1
        process.stdout.write(`  ${same ? 'ok  ' : 'FAIL'} ${String(table.name)}: ${label}\n`)
      }
    }
  } finally {
    await fake.close()
    rmSync(root, { recursive: true, force: true })
  }
  const total = corpus.calls.length - skipped
  process.stdout.write(
    `airtable atlas: ${String(failed)} failure(s) over ${String(total)} live replies and each table's two orders, ${String(skipped)} skipped\n`,
  )
  if (failed > 0) process.exitCode = 1
}

await main()
