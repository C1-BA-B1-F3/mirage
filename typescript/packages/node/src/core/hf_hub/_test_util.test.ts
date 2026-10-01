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

import { afterEach, describe, expect, it } from 'vitest'
import { FakeHub, serveHub } from './_test_util.ts'

const HEX40 = /^[0-9a-f]{40}$/
const API = '/api/models/acme/widget'
const ENC = new TextEncoder()

let hubs: FakeHub[] = []

afterEach(async () => {
  await Promise.all(hubs.map((h) => h.close()))
  hubs = []
})

async function hub(): Promise<FakeHub> {
  const fake = new FakeHub()
  fake.files().set('README.md', ENC.encode('readme'))
  fake.files().set('data/a.csv', ENC.encode('a'))
  hubs.push(fake)
  return serveHub(fake)
}

interface Answer {
  status: number
  body: unknown
  code: string
}

async function call(fake: FakeHub, path: string, body?: unknown): Promise<Answer> {
  const response = await fetch(
    fake.url + path,
    body === undefined
      ? {}
      : {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(body),
        },
  )
  const text = await response.text()
  const kind = response.headers.get('content-type') ?? ''
  return {
    status: response.status,
    body: kind.includes('json') ? (JSON.parse(text) as unknown) : text,
    code: response.headers.get('x-error-code') ?? '',
  }
}

async function head(fake: FakeHub, rev = 'main'): Promise<string> {
  const answer = await call(fake, `${API}/revision/${rev}?expand%5B%5D=sha`)
  expect(answer.status, rev).toBe(200)
  return (answer.body as { sha: string }).sha
}

async function paths(fake: FakeHub, rev: string, prefix = ''): Promise<string[]> {
  const answer = await call(fake, `${API}/tree/${rev}${prefix === '' ? '' : `/${prefix}`}`)
  expect(answer.status, `${rev} ${prefix}`).toBe(200)
  return (answer.body as { path: string }[]).map((row) => row.path).sort()
}

describe('FakeHub revision route', () => {
  it('answers the full object by default', async () => {
    const fake = await hub()
    const answer = await call(fake, `${API}/revision/main`)
    expect(answer.status).toBe(200)
    const body = answer.body as { sha: string; id: string; siblings: { rfilename: string }[] }
    expect(body.sha).toMatch(HEX40)
    expect(body.id).toBe('acme/widget')
    expect(body.siblings.map((s) => s.rfilename).sort()).toEqual(['README.md', 'data/a.csv'])
  })

  it('answers only the sha and the ids for expand[]=sha', async () => {
    const fake = await hub()
    const answer = await call(fake, `${API}/revision/main?expand%5B%5D=sha`)
    expect(answer.status).toBe(200)
    expect(Object.keys(answer.body as object).sort()).toEqual(['_id', 'id', 'sha'])
  })

  it('logs its rev and query', async () => {
    const fake = await hub()
    await head(fake)
    expect(fake.count('revision')).toBe(1)
    const [route, , rev, query] = fake.log[fake.log.length - 1] ?? []
    expect([route, rev]).toEqual(['revision', 'main'])
    expect(query).toContain('expand[]=sha')
  })

  it('derives the head from the files now', async () => {
    const fake = await hub()
    const first = await head(fake)
    expect(await head(fake)).toBe(first)
    fake.files().set('data/a.csv', ENC.encode('a, edited'))
    const edited = await head(fake)
    expect(edited).not.toBe(first)
    fake.files().set('data/a.csv', ENC.encode('a'))
    expect(await head(fake)).toBe(first)
  })

  it('keeps one head per repo', async () => {
    const fake = await hub()
    fake.files('models', 'acme/other').set('README.md', ENC.encode('other'))
    const answer = await call(fake, '/api/models/acme/other/revision/main')
    expect(answer.status).toBe(200)
    expect((answer.body as { sha: string }).sha).not.toBe(await head(fake))
  })

  it('answers RepoNotFound for a missing repo', async () => {
    const fake = await hub()
    const answer = await call(fake, '/api/models/acme/nope/revision/main')
    expect([answer.status, answer.code]).toEqual([404, 'RepoNotFound'])
  })
})

describe('FakeHub revisions on the other routes', () => {
  it('logs the rev of tree, paths-info and resolve', async () => {
    const fake = await hub()
    await paths(fake, 'main')
    await call(fake, `${API}/paths-info/dev`, { paths: ['README.md'] })
    await call(fake, '/acme/widget/resolve/v1/README.md')
    expect(fake.log.map((entry) => [entry[0], entry[2]])).toEqual([
      ['tree', 'main'],
      ['paths_info', 'dev'],
      ['resolve', 'v1'],
    ])
    expect([fake.count('tree'), fake.count('paths_info'), fake.count('resolve')]).toEqual([1, 1, 1])
  })

  it('serves a commit sha as the files it named', async () => {
    const fake = await hub()
    const old = await head(fake)
    fake.files().set('data/b.csv', ENC.encode('b'))
    fake.files().delete('README.md')
    expect(await paths(fake, old)).toEqual(['README.md', 'data', 'data/a.csv'])
    expect(await paths(fake, 'main')).toEqual(['data', 'data/a.csv', 'data/b.csv'])
    expect(await paths(fake, old, 'data')).toEqual(['data/a.csv'])
    const info = await call(fake, `${API}/paths-info/${old}`, {
      paths: ['README.md', 'data/b.csv'],
    })
    expect(info.status).toBe(200)
    expect((info.body as { path: string }[]).map((row) => row.path)).toEqual(['README.md'])
    expect(await head(fake, old)).toBe(old)
  })

  it('does not find a commit sha it never answered', async () => {
    const fake = await hub()
    await head(fake)
    const unknown = '0'.repeat(40)
    const tree = await call(fake, `${API}/tree/${unknown}`)
    expect([tree.status, tree.code]).toEqual([404, 'RevisionNotFound'])
    const info = await call(fake, `${API}/paths-info/${unknown}`, { paths: ['README.md'] })
    expect([info.status, info.code]).toEqual([404, 'RevisionNotFound'])
    const revision = await call(fake, `${API}/revision/${unknown}`)
    expect([revision.status, revision.code]).toEqual([404, 'RevisionNotFound'])
  })
})
