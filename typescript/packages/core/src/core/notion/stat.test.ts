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

import type { IndexCacheStore } from '../../cache/index/store.ts'
import { mountKey } from '../../utils/key_prefix.ts'
import { describe, expect, it } from 'vitest'
import { IndexEntry } from '../../cache/index/config.ts'
import { RAMIndexCacheStore } from '../../cache/index/ram.ts'
import { ContentType, FileType, PathSpec } from '../../types.ts'
import type { NotionAccessor } from '../../accessor/notion.ts'
import { NotionAPIError, type NotionTransport } from './client.ts'
import { stat as rawOperation } from './stat.ts'

class FakeTransport implements NotionTransport {
  public readonly invocations: { name: string; args: Record<string, unknown> }[] = []
  private readonly responses = new Map<string, Record<string, unknown>[]>()

  enqueue(toolName: string, response: Record<string, unknown>): void {
    const list = this.responses.get(toolName)
    if (list === undefined) {
      this.responses.set(toolName, [response])
    } else {
      list.push(response)
    }
  }

  callTool(name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> {
    this.invocations.push({ name, args })
    const list = this.responses.get(name) ?? []
    const response = list.shift()
    if (response === undefined) return Promise.reject(new Error(`unexpected tool call: ${name}`))
    return Promise.resolve(response)
  }
}

function makeAccessor(transport: NotionTransport): NotionAccessor {
  return { transport }
}

function spec(virtual: string, prefix = ''): PathSpec {
  return new PathSpec({ virtual, directory: virtual, vfsPath: mountKey(virtual, prefix) })
}

const PAGE_ID = 'aaaa1111-2222-3333-4444-555566667777'
const DB_ID = 'bbbb1111-2222-3333-4444-555566667777'

function databaseBody(id: string, title: string, lastEdited: string): Record<string, unknown> {
  return {
    id,
    object: 'database',
    title: [{ plain_text: title }],
    last_edited_time: lastEdited,
  }
}

describe('notion stat', () => {
  it('returns a directory stat for the root', async () => {
    const transport = new FakeTransport()
    const result = await stat(makeAccessor(transport), spec('/'), undefined)
    expect(result.name).toBe('/')
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(transport.invocations).toHaveLength(0)
  })

  it('returns a directory stat for virtual roots', async () => {
    const transport = new FakeTransport()
    for (const root of ['/', '/pages', '/databases']) {
      const result = await stat(makeAccessor(transport), spec(root), undefined)
      expect(result.type).toBe(FileType.DIRECTORY)
    }
    expect(transport.invocations).toHaveLength(0)
  })

  it('returns directory stat for a database dir using cached remoteTime', async () => {
    const transport = new FakeTransport()
    const idx = new RAMIndexCacheStore()
    const segment = `Tasks__${DB_ID}`
    await idx.setDir('/databases', [
      [
        segment,
        new IndexEntry({
          id: DB_ID,
          name: segment,
          resourceType: 'notion/database',
          remoteTime: '2024-02-03T00:00:00Z',
          vfsName: segment,
        }),
      ],
    ])
    const result = await stat(makeAccessor(transport), spec(`/databases/${segment}/`), idx)
    expect(result.name).toBe(segment)
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.extra.database_id).toBe(DB_ID)
    expect(transport.invocations).toHaveLength(0)
  })

  it('resolves an uncached database dir through the databases listing', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-post-search', {
      results: [{ id: 'ds1', object: 'data_source', parent: { database_id: DB_ID } }],
      has_more: false,
      next_cursor: null,
    })
    transport.enqueue(
      'API-retrieve-a-database',
      databaseBody(DB_ID, 'Tasks', '2024-04-05T00:00:00Z'),
    )
    const segment = `Tasks__${DB_ID}`
    const result = await stat(
      makeAccessor(transport),
      spec(`/databases/${segment}/`),
      new RAMIndexCacheStore(),
    )
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.modified).toBe('2024-04-05T00:00:00Z')
    expect(result.extra.database_id).toBe(DB_ID)
  })

  it('resolves an existing database dir with no index supplied', async () => {
    // A caller with no cache gets a call-local one, so the entry
    // resolution can read the parent listing it just warmed instead of
    // reporting every existing node as absent.
    const transport = new FakeTransport()
    transport.enqueue('API-post-search', {
      results: [{ id: 'ds1', object: 'data_source', parent: { database_id: DB_ID } }],
      has_more: false,
      next_cursor: null,
    })
    transport.enqueue(
      'API-retrieve-a-database',
      databaseBody(DB_ID, 'Tasks', '2024-04-05T00:00:00Z'),
    )
    const result = await stat(makeAccessor(transport), spec(`/databases/Tasks__${DB_ID}/`))
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.modified).toBe('2024-04-05T00:00:00Z')
    expect(result.extra.database_id).toBe(DB_ID)
  })

  it('returns a json stat for database.json without any API call', async () => {
    const transport = new FakeTransport()
    const idx = new RAMIndexCacheStore()
    const segment = `Tasks__${DB_ID}`
    await idx.setDir(`/databases/${segment}`, [
      [
        'database.json',
        new IndexEntry({
          id: `${DB_ID}:database`,
          name: 'database.json',
          resourceType: 'file',
          vfsName: 'database.json',
          size: 42,
        }),
      ],
    ])
    const result = await stat(
      makeAccessor(transport),
      spec(`/databases/${segment}/database.json`),
      idx,
    )
    expect(result.name).toBe('database.json')
    expect(result.content).toBe(ContentType.JSON)
    expect(result.size).toBe(42)
    expect(result.extra.database_id).toBe(DB_ID)
    expect(transport.invocations).toHaveLength(0)
  })

  it('returns a directory stat for the pages root', async () => {
    const transport = new FakeTransport()
    const result = await stat(makeAccessor(transport), spec('/pages/'), undefined)
    expect(result.name).toBe('pages')
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(transport.invocations).toHaveLength(0)
  })

  it('throws ENOENT for a page dir the pages listing does not carry', async () => {
    // The old stat accepted any well-shaped page dir unseen; the kit
    // resolves through the parent listing, so an unlisted one is absent.
    const transport = new FakeTransport()
    transport.enqueue('API-post-search', { results: [], has_more: false, next_cursor: null })
    const segment = `Page__${PAGE_ID}`
    await expect(
      stat(makeAccessor(transport), spec(`/pages/${segment}/`), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('uses the cached index entry name for a page dir', async () => {
    const transport = new FakeTransport()
    const idx = new RAMIndexCacheStore()
    const segment = `Page__${PAGE_ID}`
    await idx.setDir('/pages', [
      [
        segment,
        new IndexEntry({
          id: PAGE_ID,
          name: segment,
          resourceType: 'notion/page',
          remoteTime: '2024-01-02T00:00:00Z',
          vfsName: segment,
        }),
      ],
    ])
    const result = await stat(makeAccessor(transport), spec(`/pages/${segment}/`), idx)
    expect(result.name).toBe(segment)
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.modified).toBe('2024-01-02T00:00:00Z')
    expect(result.extra.page_id).toBe(PAGE_ID)
    expect(transport.invocations).toHaveLength(0)
  })

  it('returns a json stat for page.json without any API call', async () => {
    const transport = new FakeTransport()
    const idx = new RAMIndexCacheStore()
    const segment = `Page__${PAGE_ID}`
    await idx.setDir(`/pages/${segment}`, [
      [
        'page.json',
        new IndexEntry({
          id: `${PAGE_ID}:page`,
          name: 'page.json',
          resourceType: 'file',
          vfsName: 'page.json',
        }),
      ],
    ])
    const result = await stat(makeAccessor(transport), spec(`/pages/${segment}/page.json`), idx)
    expect(result.name).toBe('page.json')
    expect(result.content).toBe(ContentType.JSON)
    expect(result.size).toBeNull()
    expect(transport.invocations).toHaveLength(0)
  })

  it('throws ENOENT for a top-level dir that is not pages', async () => {
    const transport = new FakeTransport()
    let captured: unknown = null
    try {
      await stat(makeAccessor(transport), spec('/no-id-here/'), undefined)
    } catch (err) {
      captured = err
    }
    expect(captured).toBeInstanceOf(Error)
    expect((captured as { code?: string }).code).toBe('ENOENT')
    expect(transport.invocations).toHaveLength(0)
  })

  it('throws ENOENT for an unknown leaf inside a page dir', async () => {
    const transport = new FakeTransport()
    const segment = `Page__${PAGE_ID}`
    let captured: unknown = null
    try {
      await stat(makeAccessor(transport), spec(`/pages/${segment}/foo.txt`), undefined)
    } catch (err) {
      captured = err
    }
    expect(captured).toBeInstanceOf(Error)
    expect((captured as { code?: string }).code).toBe('ENOENT')
    expect(transport.invocations).toHaveLength(0)
  })

  it('honors a path prefix', async () => {
    const transport = new FakeTransport()
    const idx = new RAMIndexCacheStore()
    const segment = `Page__${PAGE_ID}`
    await idx.setDir('/notion/pages', [
      [
        segment,
        new IndexEntry({
          id: PAGE_ID,
          name: segment,
          resourceType: 'notion/page',
          remoteTime: '',
          vfsName: segment,
        }),
      ],
    ])
    const virtual = `/notion/pages/${segment}/`
    const result = await stat(
      makeAccessor(transport),
      new PathSpec({ virtual, directory: virtual, vfsPath: mountKey(virtual, '/notion') }),
      idx,
    )
    expect(result.name).toBe(segment)
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.extra.page_id).toBe(PAGE_ID)
  })
})

const DS_ID = 'cccc1111-2222-3333-4444-555566667777'
const DS_DIR = `/databases/Tasks__${DB_ID}/Tasks__${DS_ID}`

function rowBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: PAGE_ID,
    object: 'page',
    last_edited_time: '2024-03-04T00:00:00Z',
    in_trash: false,
    parent: { type: 'data_source_id', data_source_id: DS_ID, database_id: DB_ID },
    properties: { Name: { type: 'title', title: [{ plain_text: 'Row A' }] } },
    ...overrides,
  }
}

describe('notion stat rows', () => {
  // A data source lists rows.jsonl rather than its rows, so a row directory
  // proves itself with one retrieve instead of through a listing.
  it('returns a directory stat for a row of this data source', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-retrieve-a-page', rowBody())
    const segment = `Row_A__${PAGE_ID}`
    const result = await stat(
      makeAccessor(transport),
      spec(`${DS_DIR}/${segment}`),
      new RAMIndexCacheStore(),
    )
    expect(result.name).toBe(segment)
    expect(result.type).toBe(FileType.DIRECTORY)
    expect(result.modified).toBe('2024-03-04T00:00:00Z')
    expect(result.extra.page_id).toBe(PAGE_ID)
    expect(transport.invocations).toEqual([
      { name: 'API-retrieve-a-page', args: { page_id: PAGE_ID } },
    ])
  })

  it('throws ENOENT for a row of another data source', async () => {
    const transport = new FakeTransport()
    transport.enqueue(
      'API-retrieve-a-page',
      rowBody({
        parent: { type: 'data_source_id', data_source_id: 'eeee1111-2222-3333-4444-555566667777' },
      }),
    )
    await expect(
      stat(makeAccessor(transport), spec(`${DS_DIR}/Row_A__${PAGE_ID}`), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('throws ENOENT for a row spelled with another title', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-retrieve-a-page', rowBody())
    await expect(
      stat(makeAccessor(transport), spec(`${DS_DIR}/Row_B__${PAGE_ID}`), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('throws ENOENT for a row in the trash', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-retrieve-a-page', rowBody({ in_trash: true }))
    await expect(
      stat(makeAccessor(transport), spec(`${DS_DIR}/Row_A__${PAGE_ID}`), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('throws ENOENT for a row Notion does not know', async () => {
    const transport: NotionTransport = {
      callTool: () =>
        Promise.reject(new NotionAPIError('Could not find page', 404, 'object_not_found')),
    }
    await expect(
      stat(makeAccessor(transport), spec(`${DS_DIR}/Row_A__${PAGE_ID}`), new RAMIndexCacheStore()),
    ).rejects.toMatchObject({ code: 'ENOENT' })
  })

  it('returns a text stat for rows.jsonl through the data source listing', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-retrieve-a-data-source', {
      id: DS_ID,
      object: 'data_source',
      title: [{ plain_text: 'Tasks' }],
      parent: { type: 'database_id', database_id: DB_ID },
      properties: {},
    })
    const result = await stat(
      makeAccessor(transport),
      spec(`${DS_DIR}/rows.jsonl`),
      new RAMIndexCacheStore(),
    )
    expect(result.type).toBe(FileType.FILE)
    expect(result.content).toBe(ContentType.TEXT)
    expect(result.size).toBeNull()
    expect(result.extra.data_source_id).toBe(DS_ID)
  })

  it('returns a json stat for a row page.json without fetching blocks', async () => {
    const transport = new FakeTransport()
    transport.enqueue('API-retrieve-a-page', rowBody())
    const result = await stat(
      makeAccessor(transport),
      spec(`${DS_DIR}/Row_A__${PAGE_ID}/page.json`),
      new RAMIndexCacheStore(),
    )
    expect(result.type).toBe(FileType.FILE)
    expect(result.content).toBe(ContentType.JSON)
    expect(transport.invocations.map((call) => call.name)).toEqual(['API-retrieve-a-page'])
  })
})

async function stat(accessor: NotionAccessor, path: PathSpec, index?: IndexCacheStore) {
  const cache = index ?? new RAMIndexCacheStore()
  const pieces = path.virtual.replace(/\/$/, '').split('/')
  const count = pieces.length - 1
  for (let i = 1; i < count; i++) {
    const key = pieces.slice(0, i + 1).join('/')
    const name = pieces[i] ?? ''
    if (name.includes('__') && (await cache.get(key)).entry == null)
      await cache.setPartialDir(key.slice(0, key.lastIndexOf('/')) || '/', [
        [
          name,
          new IndexEntry({
            id: name.split('__').at(-1) ?? '',
            name,
            vfsName: name,
            resourceType: 'notion/container',
          }),
        ],
      ])
  }
  return rawOperation(accessor, path, cache)
}

it.each(['Wrong__db123', 'Tasks__db123/Wrong__ds789', 'Tasks__db123/Other__foreign'])(
  'rejects an unlisted ancestor %s before reading its leaf',
  async (directory) => {
    for (const index of [new RAMIndexCacheStore(), undefined]) {
      const transport = new FakeTransport()
      transport.enqueue('API-post-search', {
        results: [{ id: 'ds789', object: 'data_source', parent: { database_id: 'db123' } }],
        has_more: false,
        next_cursor: null,
      })
      const database = {
        id: 'db123',
        title: [{ plain_text: 'Tasks' }],
        data_sources: [{ id: 'ds789', name: 'Tasks' }],
      }
      transport.enqueue('API-retrieve-a-database', database)
      transport.enqueue('API-retrieve-a-database', database)
      const leaf = directory.includes('/') ? 'rows.jsonl' : 'database.json'
      await expect(
        rawOperation(makeAccessor(transport), spec(`/databases/${directory}/${leaf}`), index),
      ).rejects.toMatchObject({ code: 'ENOENT' })
      expect(transport.invocations.some((call) => call.name === 'API-retrieve-a-data-source')).toBe(
        false,
      )
    }
  },
)
