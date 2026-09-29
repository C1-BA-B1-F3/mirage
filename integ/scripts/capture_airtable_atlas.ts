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

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { chromium } from 'playwright-core'

const APP = 'appIF9byLfQwdHqE2'
const SHARE = `https://airtable.com/${APP}/shr1KTZOgPl0qQmA8`

interface Read {
  status: number
  body: string
}

/**
 * Capture MCP-Atlas's Airtable base from the share link its data_exports
 * README names in place of a file ("Copy base"), for gen_airtable_atlas.py.
 *
 *   pnpm exec tsx scripts/capture_airtable_atlas.ts <out-dir> [chrome-path]
 *
 * The share page loads the base through its own read endpoint, authorised by
 * the share's access policy; this replays that request inside the page, once
 * for the schema and once per table, so every row arrives whole, unrendered
 * and in the base's own row order. Nothing here signs in or holds a key.
 */
async function main(): Promise<void> {
  const [out, chrome] = process.argv.slice(2)
  if (out === undefined) throw new Error('usage: capture_airtable_atlas.ts <out-dir> [chrome-path]')
  mkdirSync(out, { recursive: true })
  const browser = await chromium.launch(
    chrome === undefined ? { channel: 'chrome', headless: true } : { executablePath: chrome },
  )
  try {
    const page = await browser.newPage()
    const doc = await page.goto(SHARE, { waitUntil: 'domcontentloaded', timeout: 90_000 })
    if (doc === null) throw new Error(`${SHARE}: no document`)
    const html = await doc.text()
    writeFileSync(join(out, 'share.html'), html)
    const policy = /accessPolicy=([^"&]+)/.exec(html)?.[1]
    const pageLoadId = /"x-airtable-page-load-id":"([^"]+)"/.exec(html)?.[1]
    if (policy === undefined || pageLoadId === undefined)
      throw new Error(`${SHARE}: the page carries no access policy`)

    const read = (tableIds: string[]): Promise<Read> =>
      page.evaluate(
        async ({ app, policy, pageLoadId, tableIds }) => {
          const params = {
            includeDataForTableIds: tableIds,
            includeDataForViewIds: null,
            shouldIncludeSchemaChecksum: true,
            mayExcludeCellDataForLargeViews: false,
            allowMsgpackOfResult: false,
          }
          const query = new URLSearchParams({
            stringifiedObjectParams: JSON.stringify(params),
            requestId: `req${Math.random().toString(36).slice(2, 16)}`,
            accessPolicy: decodeURIComponent(policy),
          })
          const res = await fetch(`/v0.3/application/${app}/read?${query.toString()}`, {
            headers: {
              'x-user-locale': 'en',
              'x-time-zone': 'UTC',
              'x-airtable-application-id': app,
              'x-airtable-page-load-id': pageLoadId,
              'X-Requested-With': 'XMLHttpRequest',
              'x-airtable-inter-service-client': 'webClient',
            },
          })
          return { status: res.status, body: await res.text() }
        },
        { app: APP, policy, pageLoadId, tableIds },
      )

    const schema = await read([])
    if (schema.status !== 200) throw new Error(`schema read: HTTP ${String(schema.status)}`)
    writeFileSync(join(out, 'schema.json'), schema.body)
    const tables = (
      JSON.parse(schema.body) as { data: { tableSchemas: { id: string; name: string }[] } }
    ).data.tableSchemas
    for (const table of tables) {
      const got = await read([table.id])
      if (got.status !== 200) throw new Error(`${table.name}: HTTP ${String(got.status)}`)
      writeFileSync(join(out, `${table.id}.json`), got.body)
      process.stdout.write(`${table.id} ${table.name}\n`)
    }
  } finally {
    await browser.close()
  }
}

await main()
