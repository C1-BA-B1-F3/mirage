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

import { searchConformance } from './search_conformance.ts'
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import type { ChildProcessByStdio } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import type { Readable } from 'node:stream'
import { fileURLToPath } from 'node:url'
import { ANNOUNCE_RE } from '../kit/typescript/announce.ts'
import type { JsonValue } from '../kit/typescript/types.ts'
import { start } from '../kit/typescript/serve.ts'
import { githubFake } from './fake.ts'

// The routes the corpus does not reach, or cannot exercise fully, because the
// gh battery drives the porcelain against a one-repository fixture. A client
// that BUILDS history calls `POST /git/trees` then `POST /git/commits`, which is
// the path a fixture uses to pin a commit's own author and date; a grader reads
// an issue's comments back; repository search must preserve owner scope;
// and code search's scope rules need files under several owners and a
// mixed-case name, which the `cli` fixture does not hold.

const HERE = dirname(fileURLToPath(import.meta.url))
const INTEG = resolve(HERE, '..', '..')
const TENANT = 'selftest-github'
const REPO = 'integ/repo-v1'

let checks = 0

function check(name: string, ok: boolean, detail = ''): void {
  checks += 1
  const line = `  ${ok ? 'ok  ' : 'FAIL'} ${String(checks).padStart(2, '0')} ${name}`
  process.stdout.write(detail === '' ? `${line}\n` : `${line}  [${detail}]\n`)
  if (!ok) throw new Error(`github selftest failed: ${name} ${detail}`)
}

function eq(name: string, got: JsonValue, want: JsonValue): void {
  const a = JSON.stringify(got)
  const b = JSON.stringify(want)
  check(name, a === b, a === b ? a : `got ${a} want ${b}`)
}

interface Fake {
  child: ChildProcessByStdio<null, Readable, Readable>
  endpoint: string
}

async function launch(): Promise<Fake> {
  const child = spawn(
    join(INTEG, 'node_modules', '.bin', 'tsx'),
    [join(HERE, 'main.ts'), '--port', '0'],
    { cwd: INTEG, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env } },
  )
  let err = ''
  child.stderr.setEncoding('utf8')
  child.stderr.on('data', (d: string) => {
    err += d
  })
  const first = await new Promise<string>((ok, bad) => {
    let out = ''
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (d: string) => {
      out += d
      const nl = out.indexOf('\n')
      if (nl !== -1) ok(out.slice(0, nl))
    })
    child.on('exit', (code) => {
      bad(new Error(`fake exited ${String(code)} before announcing\n${err}`))
    })
  })
  check('announce line matches ANNOUNCE_RE', ANNOUNCE_RE.test(first), first)
  return { child, endpoint: first.split('=').slice(1).join('=') }
}

const HEADERS = {
  'x-mirage-tenant': TENANT,
  authorization: 'token integ',
  'content-type': 'application/json',
}

async function post(url: string, body: JsonValue): Promise<{ status: number; body: JsonValue }> {
  const r = await fetch(url, { method: 'POST', headers: HEADERS, body: JSON.stringify(body) })
  return { status: r.status, body: (await r.json()) as JsonValue }
}

async function get(url: string): Promise<JsonValue> {
  const r = await fetch(url, { headers: HEADERS })
  return (await r.json()) as JsonValue
}

function field(body: JsonValue, key: string): JsonValue {
  return typeof body === 'object' && body !== null && !Array.isArray(body)
    ? ((body as Record<string, JsonValue>)[key] ?? null)
    : null
}

// A refusal is pinned by its status and its message together, because the
// vendor tells an empty repository from a missing ref by both.
async function refusal(url: string): Promise<JsonValue> {
  const r = await fetch(url, { headers: HEADERS })
  return [r.status, field((await r.json()) as JsonValue, 'message')]
}

// Every ref spelling a client might ask an empty repository about: shown or
// listed, branch or tag, one that would exist and one that never could, and
// the bare listing with and without its slash.
const REF_PATHS = [
  'git/ref/heads/main',
  'git/ref/heads/nope',
  'git/ref/tags/v1',
  'git/refs',
  'git/refs/',
  'git/refs/heads',
  'git/refs/heads/main',
  'git/refs/tags',
]

// Object reads an empty repository refuses the same way, measured against
// GitHub (2026-09-27): the recursive and shallow tree of a ref, one directory
// of it, and a blob, here the empty blob every git repository could name.
const OBJECT_PATHS = [
  'git/trees/main?recursive=1',
  'git/trees/main',
  'git/trees/main%3Adocs',
  'git/blobs/e69de29bb2d1d6434b8b29ae775ad8c2e48c5391',
]

// One staged tree holding one file, which is what a commit needs to exist.
async function stage(at: string, path: string, content: string): Promise<string> {
  const tree = await post(`${at}/repos/${REPO}/git/trees`, {
    tree: [{ path, mode: '100644', type: 'blob', content }],
  })
  return String(field(tree.body, 'sha') ?? '')
}

const AUTHOR = { name: 'Dana Wu', email: 'dana@example.com', date: '2025-09-02T09:00:00+08:00' }

async function metadataRepository(): Promise<void> {
  const root = await mkdtemp(join(tmpdir(), 'mirage-empty-repo-'))
  try {
    await mkdir(join(root, 'github'))
    await writeFile(
      join(root, 'github', 'metadata.json'),
      JSON.stringify({
        repos: [
          {
            fullName: 'integ/metadata',
            owner: 'integ',
            name: 'metadata',
            defaultBranch: 'main',
          },
        ],
      }),
    )
    const home = await start(githubFake, 0, 'metadata', root)
    try {
      await home.runtime.reset({ tenants: [TENANT], fixture: 'metadata' })
      for (const prefix of ['', '/api/v3']) {
        const repo = `${home.endpoint}${prefix}/repos/integ/metadata`
        const contents = await fetch(`${repo}/contents/`, { headers: HEADERS })
        eq('metadata-only contents returns 404', contents.status, 404)
        eq(
          'metadata-only contents identifies an empty repository',
          field((await contents.json()) as JsonValue, 'message'),
          'This repository is empty.',
        )
        const commits = await fetch(`${repo}/commits`, { headers: HEADERS })
        eq('metadata-only history returns 409', commits.status, 409)
        eq(
          'metadata-only history identifies an empty repository',
          field((await commits.json()) as JsonValue, 'message'),
          'Git Repository is empty.',
        )
        eq('metadata-only tags list is empty', await get(`${repo}/tags`), [])
        for (const path of [...REF_PATHS, ...OBJECT_PATHS]) {
          eq(`metadata-only ${path} is refused as empty`, await refusal(`${repo}/${path}`), [
            409,
            'Git Repository is empty.',
          ])
        }
        eq(
          'metadata-only contents at an unknown ref is still empty',
          await refusal(`${repo}/contents/?ref=nope`),
          [404, 'This repository is empty.'],
        )
      }
    } finally {
      await home.close()
    }
  } finally {
    await rm(root, { recursive: true, force: true })
  }
}

async function emptyRepository(at: string): Promise<void> {
  const base = `${at}/_run/empty-repository`
  await post(`${base}/reset`, { run: 'empty-repository', tenants: [TENANT], fixture: 'empty' })
  for (const prefix of ['', '/api/v3']) {
    const name = prefix === '' ? 'empty-public' : 'empty-enterprise'
    const created = await post(`${base}${prefix}/user/repos`, { name })
    eq('empty repository creation succeeds', created.status, 201)
    const repo = `${base}${prefix}/repos/integ-user/${name}`
    for (const path of ['contents', 'contents/']) {
      const response = await fetch(`${repo}/${path}`, { headers: HEADERS })
      eq('empty contents returns 404', response.status, 404)
      eq(
        'empty contents explains why',
        field((await response.json()) as JsonValue, 'message'),
        'This repository is empty.',
      )
    }
    // Emptiness is answered before the ref is resolved, so a ref that names
    // nothing is told the repository is empty, not that the ref is missing.
    for (const path of ['contents/?ref=nope', 'contents?ref=nope', 'contents/first.txt?ref=nope']) {
      eq(`empty ${path} is refused as empty`, await refusal(`${repo}/${path}`), [
        404,
        'This repository is empty.',
      ])
    }
    const commits = await fetch(`${repo}/commits`, { headers: HEADERS })
    eq('empty history returns 409', commits.status, 409)
    eq(
      'empty history explains why',
      field((await commits.json()) as JsonValue, 'message'),
      'Git Repository is empty.',
    )
    // GitHub answers an empty repository before it resolves the ref, so a name
    // or sha that matches nothing gets the same 409 as the default branch.
    for (const ref of ['main', 'HEAD', 'nope', 'deadbeef'.repeat(5)]) {
      const one = await fetch(`${repo}/commits/${ref}`, { headers: HEADERS })
      eq(`empty commit ${ref} returns 409`, one.status, 409)
      eq(
        `empty commit ${ref} explains why`,
        field((await one.json()) as JsonValue, 'message'),
        'Git Repository is empty.',
      )
    }
    const tags = await fetch(`${repo}/tags`, { headers: HEADERS })
    eq('empty tags succeeds', tags.status, 200)
    eq('empty tags lists nothing', (await tags.json()) as JsonValue, [])
    // The fake lets a branch be cut from nothing here. It holds no commit, so
    // the repository stays empty, and once another branch has history it is
    // still no ref: every read of it below is refused.
    const cut = await post(`${repo}/git/refs`, { ref: 'refs/heads/side', sha: '' })
    eq('a branch cut from nothing is created', cut.status, 201)
    eq('and leaves the repository empty', await refusal(`${repo}/contents/?ref=side`), [
      404,
      'This repository is empty.',
    ])
    for (const path of [...REF_PATHS, ...OBJECT_PATHS]) {
      eq(`empty ${path} is refused as empty`, await refusal(`${repo}/${path}`), [
        409,
        'Git Repository is empty.',
      ])
    }
    const written = await fetch(`${repo}/contents/first.txt`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'First real commit',
        content: Buffer.from('hello').toString('base64'),
      }),
    })
    eq('first write succeeds', written.status, 201)
    const body = (await written.json()) as JsonValue
    const history = (await get(`${repo}/commits`)) as JsonValue[]
    eq('first write has no invented ancestor', history.length, 1)
    eq(
      'history contains the written commit',
      field(history[0] ?? null, 'sha'),
      field(field(body, 'commit'), 'sha'),
    )
    // One write and the repository has a ref, so refs resolve again: the
    // branch points at the commit the write made, and a ref, a commit or a
    // contents ref that names nothing is refused as missing, not as empty.
    const sha = field(field(body, 'commit'), 'sha')
    eq('the written branch shows its ref', await get(`${repo}/git/ref/heads/main`), {
      ref: 'refs/heads/main',
      object: { sha, type: 'commit' },
    })
    for (const path of ['git/refs', 'git/refs/heads']) {
      eq(`${path} lists the written branch`, await get(`${repo}/${path}`), [
        { ref: 'refs/heads/main', object: { sha, type: 'commit' } },
      ])
    }
    eq('an unknown ref is missing, not empty', await refusal(`${repo}/git/ref/heads/nope`), [
      404,
      'Not Found',
    ])
    for (const ref of ['nope', 'refs/heads/nope', 'deadbeef'.repeat(5)]) {
      eq(`an unknown commit ${ref} is refused by name`, await refusal(`${repo}/commits/${ref}`), [
        422,
        `No commit found for SHA: ${ref}`,
      ])
    }
    eq('contents at an unknown ref names it', await refusal(`${repo}/contents/?ref=nope`), [
      404,
      'No commit found for the ref nope',
    ])
    // The listings above already leave `side` out.
    eq('an uncommitted branch has no contents', await refusal(`${repo}/contents/?ref=side`), [
      404,
      'No commit found for the ref side',
    ])
    eq('nor a ref', await refusal(`${repo}/git/ref/heads/side`), [404, 'Not Found'])
    eq('nor a commit', await refusal(`${repo}/commits/side`), [
      422,
      'No commit found for SHA: side',
    ])
    const deleted = await fetch(`${repo}/contents/first.txt`, {
      method: 'DELETE',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Remove last file',
        sha: field(field(body, 'content'), 'sha'),
      }),
    })
    eq('last file deletion succeeds', deleted.status, 200)
    eq(
      'a committed empty tree still has history',
      ((await get(`${repo}/commits`)) as JsonValue[]).length,
      2,
    )
    eq('a committed empty tree lists successfully', await get(`${repo}/contents/`), [])
    eq(
      'a committed empty tree still shows its ref',
      field(field(await get(`${repo}/git/ref/heads/main`), 'object'), 'sha'),
      field(field((await deleted.json()) as JsonValue, 'commit'), 'sha'),
    )
  }
  for (const path of ['/graphql', '/api/graphql']) {
    const response = await post(`${base}${path}`, { query: '{ viewer { login } }' })
    eq('GraphQL endpoint succeeds', response.status, 200)
    eq('GraphQL endpoint resolves viewer', field(response.body, 'data'), {
      viewer: { login: 'integ-user' },
    })
    const anonymous = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '{ viewer { login } }' }),
    })
    eq('GraphQL requires authentication', anonymous.status, 401)
  }
}

// A seeded branch has files and no commit, so its ref answers with a root
// derived from those files. The first change on it, a write or a delete, names
// that root as its parent, and history has to keep listing it under that
// commit however the files change afterwards.
async function seededHistory(at: string): Promise<void> {
  for (const first of ['PUT', 'DELETE']) {
    const run = `seeded-${first.toLowerCase()}`
    const base = `${at}/_run/${run}`
    await post(`${base}/reset`, { run, tenants: [TENANT], fixture: 'v1' })
    const repo = `${base}/repos/${REPO}`
    const root = String(field(field(await get(`${repo}/git/ref/heads/main`), 'object'), 'sha'))
    eq('a seeded branch is not an empty repository', await refusal(`${repo}/commits/nope`), [
      422,
      'No commit found for SHA: nope',
    ])
    const path = first === 'PUT' ? 'first.txt' : 'README.md'
    const change =
      first === 'PUT'
        ? { message: 'First change', content: Buffer.from('one').toString('base64') }
        : { message: 'First change', sha: field(await get(`${repo}/contents/${path}`), 'sha') }
    const changed = await fetch(`${repo}/contents/${path}`, {
      method: first,
      headers: HEADERS,
      body: JSON.stringify(change),
    })
    eq(`a first ${first} on a seeded branch succeeds`, changed.status, first === 'PUT' ? 201 : 200)
    const second = await fetch(`${repo}/contents/second.txt`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Second change',
        content: Buffer.from('two').toString('base64'),
      }),
    })
    eq('a second write on it succeeds', second.status, 201)
    const history = (await get(`${repo}/commits`)) as JsonValue[]
    eq(
      'history lists both changes above one root',
      history.map((c) => field(field(c, 'commit'), 'message')),
      ['Second change', 'First change', 'Initial commit'],
    )
    eq(
      'that root is where the ref pointed before the first change',
      field(history[2] ?? null, 'sha'),
      root,
    )
    const found = field(
      await get(`${base}/search/commits?q=${encodeURIComponent(`repo:${REPO} first change`)}`),
      'items',
    ) as JsonValue[]
    eq('the first change names that root as its parent', field(found[0] ?? null, 'parents'), [
      { sha: root },
    ])
    const resolved = await fetch(`${repo}/git/commits/${root}`, { headers: HEADERS })
    eq('that root still resolves as a commit', resolved.status, 200)
    const compared = await fetch(`${repo}/compare/${root}...main`, { headers: HEADERS })
    eq('a comparison from that root succeeds', compared.status, 200)
    eq(
      'and reports both changes',
      ((field((await compared.json()) as JsonValue, 'files') ?? []) as JsonValue[]).map((f) =>
        field(f, 'filename'),
      ),
      ['second.txt', path],
    )
  }
}

// Git keeps an object once it is written, so a blob sha an old listing named
// still reads its own bytes after its path changes: overwritten or deleted,
// whether the bytes came from the seed or from a commit. Measured against
// GitHub (2026-09-27): a superseded blob answers 200 with its old bytes.
async function supersededBlobs(at: string): Promise<void> {
  const run = 'superseded-blobs'
  const base = `${at}/_run/${run}`
  await post(`${base}/reset`, { run, tenants: [TENANT], fixture: 'v1' })
  const repo = `${base}/repos/${REPO}`
  const send = async (method: string, body: JsonValue): Promise<JsonValue> => {
    const r = await fetch(`${repo}/contents/README.md`, {
      method,
      headers: HEADERS,
      body: JSON.stringify(body),
    })
    eq(`the ${method} of README.md succeeds`, r.status, 200)
    return (await r.json()) as JsonValue
  }
  const blob = async (sha: JsonValue): Promise<JsonValue> => {
    const r = await fetch(`${repo}/git/blobs/${String(sha)}`, { headers: HEADERS })
    if (r.status !== 200) return r.status
    return Buffer.from(String(field((await r.json()) as JsonValue, 'content')), 'base64').toString()
  }
  const seeded = await get(`${repo}/contents/README.md`)
  const seededText = Buffer.from(String(field(seeded, 'content')), 'base64').toString()
  const one = await send('PUT', {
    message: 'Replace the seed',
    content: Buffer.from('one').toString('base64'),
    sha: field(seeded, 'sha'),
  })
  eq('a seeded blob a write replaced still reads', await blob(field(seeded, 'sha')), seededText)
  const oneSha = field(field(one, 'content'), 'sha')
  const two = await send('PUT', {
    message: 'Replace the commit',
    content: Buffer.from('two').toString('base64'),
    sha: oneSha,
  })
  eq('a committed blob a write replaced still reads', await blob(oneSha), 'one')
  const twoSha = field(field(two, 'content'), 'sha')
  await send('DELETE', { message: 'Remove it', sha: twoSha })
  eq('a deleted blob still reads', await blob(twoSha), 'two')
  eq('a sha no tree ever held is not found', await blob('0'.repeat(40)), 404)
}

// A ref names a branch, or one commit by its full or abbreviated sha, and
// every read that takes one answers from what it names: a commit's own
// files, its own history, its own place in a comparison.
async function refsNameCommits(at: string): Promise<void> {
  const run = 'refs-name-commits'
  const base = `${at}/_run/${run}`
  await post(`${base}/reset`, { run, tenants: [TENANT], fixture: 'v1' })
  const repo = `${base}/repos/${REPO}`
  const status = async (url: string, init: RequestInit = {}): Promise<number> =>
    (await fetch(url, { headers: HEADERS, ...init })).status
  const put = await fetch(`${repo}/contents/later.txt`, {
    method: 'PUT',
    headers: HEADERS,
    body: JSON.stringify({ message: 'Later', content: Buffer.from('later').toString('base64') }),
  })
  eq('a file lands on the seeded branch', put.status, 201)
  const history = (await get(`${repo}/commits`)) as JsonValue[]
  const head = String(field(history[0] ?? null, 'sha'))
  const root = String(field(history.at(-1) ?? null, 'sha'))
  eq(
    'four hex digits name the root',
    field(await get(`${repo}/commits/${root.slice(0, 4)}`), 'sha'),
    root,
  )
  eq('three name nothing', await status(`${repo}/commits/${root.slice(0, 3)}`), 422)
  eq(
    'commits?sha= lists from the commit it names',
    ((await get(`${repo}/commits?sha=${root.slice(0, 7).toUpperCase()}`)) as JsonValue[]).map((c) =>
      field(c, 'sha'),
    ),
    [root],
  )
  eq('commits?sha= naming nothing is 404', await status(`${repo}/commits?sha=0000000`), 404)
  eq(
    'the root reads its own files',
    await status(`${repo}/contents/later.txt?ref=${root.slice(0, 7)}`),
    404,
  )
  eq(
    'the head reads its own',
    await status(`${repo}/contents/later.txt?ref=${head.slice(0, 7)}`),
    200,
  )
  const paths = async (ref: string): Promise<boolean> =>
    ((field(await get(`${repo}/git/trees/${ref}?recursive=1`), 'tree') as JsonValue[]) ?? []).some(
      (row) => field(row, 'path') === 'later.txt',
    )
  eq("a tree by the root's short sha is the root's", await paths(root.slice(0, 7)), false)
  eq("a tree by the head's short sha is the head's", await paths(head.slice(0, 7)), true)
  const compare = async (spec: string): Promise<JsonValue> => {
    const body = await get(`${repo}/compare/${spec}`)
    return [field(body, 'status'), field(body, 'ahead_by'), field(body, 'behind_by')]
  }
  eq('the head is ahead of the root', await compare(`${root.slice(0, 7)}...main`), ['ahead', 1, 0])
  eq('the root is behind the head', await compare(`main...${root.slice(0, 7)}`), ['behind', 0, 1])
  eq('a branch is identical to itself', await compare('main...main'), ['identical', 0, 0])
  const made = await post(`${repo}/git/refs`, { ref: 'refs/heads/old', sha: root.slice(0, 7) })
  eq('a branch starts at a short sha', made.status, 201)
  eq("and holds that commit's files", await status(`${repo}/contents/later.txt?ref=old`), 404)
}

// A seeded branch force-moved onto an unrelated root leaves its own root on
// no branch, and that sha still names its commit and its files, as git keeps
// an object once it exists.
async function abandonedRoot(at: string): Promise<void> {
  const run = 'abandoned-root'
  const base = `${at}/_run/${run}`
  await post(`${base}/reset`, { run, tenants: [TENANT], fixture: 'v1' })
  const repo = `${base}/repos/${REPO}`
  const root = String(field(((await get(`${repo}/commits`)) as JsonValue[])[0] ?? null, 'sha'))
  const tree = await post(`${repo}/git/trees`, {
    tree: [{ path: 'only.txt', mode: '100644', type: 'blob', content: 'only' }],
  })
  const other = await post(`${repo}/git/commits`, {
    message: 'Unrelated',
    tree: field(tree.body, 'sha'),
    parents: [],
  })
  const moved = await fetch(`${repo}/git/refs/heads/main`, {
    method: 'PATCH',
    headers: HEADERS,
    body: JSON.stringify({ sha: field(other.body, 'sha'), force: true }),
  })
  eq('the branch is forced onto an unrelated root', moved.status, 200)
  eq(
    'the old root still names its commit',
    field(await get(`${repo}/commits/${root.slice(0, 7)}`), 'sha'),
    root,
  )
  const readme = await fetch(`${repo}/contents/README.md?ref=${root.slice(0, 7)}`, {
    headers: HEADERS,
  })
  eq('and its files', readme.status, 200)
  const dispatch = await fetch(
    `${base}/repos/integ/repo-cli/actions/workflows/archive.yml/dispatches`,
    {
      method: 'POST',
      headers: HEADERS,
      body: JSON.stringify({ ref: 'main' }),
    },
  )
  eq('a disabled workflow is not dispatched', await refusalOf(dispatch), [
    422,
    "Cannot trigger a 'workflow_dispatch' on a disabled workflow",
  ])
}

async function refusalOf(r: Response): Promise<JsonValue> {
  return [r.status, field((await r.json()) as JsonValue, 'message')]
}

// Workflows are the repository's files, and the settings routes store what
// they take and refuse what they do not, before anything is written.
async function workflowsAndSettings(at: string): Promise<void> {
  const run = 'workflows-and-settings'
  const base = `${at}/_run/${run}`
  await post(`${base}/reset`, { run, tenants: [TENANT], fixture: 'v1' })
  const repo = `${base}/repos/${REPO}`
  const send = async (method: string, path: string, body?: JsonValue): Promise<number> =>
    (
      await fetch(`${repo}${path}`, {
        method,
        headers: HEADERS,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
    ).status
  const write = (path: string, text: string): Promise<number> =>
    send('PUT', `/contents/${path}`, {
      message: `Add ${path}`,
      content: Buffer.from(text).toString('base64'),
    })
  await write('.github/workflows/nameless.yaml', 'on: push\n')
  await write('.github/workflows/nested/deep.yml', 'name: Deep\n')
  await write('.github/workflows/notes.txt', 'name: Notes\n')
  const listed = async (): Promise<JsonValue> =>
    ((field(await get(`${repo}/actions/workflows`), 'workflows') as JsonValue[]) ?? []).map((w) => [
      field(w, 'name'),
      field(w, 'path'),
    ])
  eq('the list is the workflow files, by id', await listed(), [
    ['Archive', '.github/workflows/archive.yml'],
    ['CI', '.github/workflows/ci.yml'],
    ['.github/workflows/nameless.yaml', '.github/workflows/nameless.yaml'],
  ])
  eq('a workflow is found by its file', await send('GET', '/actions/workflows/ci.yml'), 200)
  eq('never by its display name', await send('GET', '/actions/workflows/CI'), 404)
  eq(
    'one with no dispatch trigger cannot be dispatched',
    await send('POST', '/actions/workflows/nameless.yaml/dispatches', { ref: 'main' }),
    422,
  )
  eq(
    'a dispatch to a ref that is no branch is refused',
    await send('POST', '/actions/workflows/ci.yml/dispatches', { ref: 'nope' }),
    422,
  )
  const ci = await get(`${repo}/contents/.github/workflows/ci.yml`)
  await send('DELETE', '/contents/.github/workflows/ci.yml', {
    message: 'rm',
    sha: field(ci, 'sha'),
  })
  eq('a workflow whose file is gone is not listed', ((await listed()) as JsonValue[]).length, 2)
  eq(
    'and cannot be dispatched',
    await send('POST', '/actions/workflows/ci.yml/dispatches', { ref: 'main' }),
    404,
  )
  eq(
    'a wrongly typed setting refuses the whole edit',
    await send('PATCH', '', { description: 'x', has_issues: 'yes' }),
    422,
  )
  eq('and writes none of it', field(await get(repo), 'description'), null)
  for (const key of ['name', 'default_branch']) {
    for (const value of [123, null, [], {}]) {
      eq(
        `a wrongly typed ${key} refuses the whole edit`,
        await send('PATCH', '', { description: 'must not land', [key]: value }),
        422,
      )
      eq('the refused edit preserves the repository', field(await get(repo), 'description'), null)
    }
  }
  eq(
    'an invalid branch type cannot partially rename a repository',
    await send('PATCH', '', { name: 'must-not-rename', default_branch: false }),
    422,
  )
  eq('the original name still resolves', await send('GET', ''), 200)
  eq('an unknown visibility is refused', await send('PATCH', '', { visibility: 'secret' }), 422)
  eq('a legacy site needs a source', await send('POST', '/pages', {}), 422)
  eq(
    'a source path is the root or /docs',
    await send('POST', '/pages', { source: { branch: 'main', path: '/site' } }),
    422,
  )
  eq('no site is updated', await send('PUT', '/pages', { cname: null }), 404)
  eq('no site is deleted', await send('DELETE', '/pages'), 404)
  eq(
    'a workflow site needs no source',
    await send('POST', '/pages', { build_type: 'workflow' }),
    201,
  )
  eq("and publishes the default branch's root", field(await get(`${repo}/pages`), 'source'), {
    branch: 'main',
    path: '/',
  })
  eq(
    'a wrongly typed site edit is refused',
    await send('PUT', '/pages', { https_enforced: 'yes' }),
    422,
  )
  const logs = await fetch(`${base}/repos/integ/repo-cli/actions/runs/201/logs`, {
    headers: HEADERS,
  })
  eq("a completed run's logs are a zip", logs.headers.get('content-type'), 'application/zip')
  eq(
    "one job's log is its steps' text",
    (
      await (
        await fetch(`${base}/repos/integ/repo-cli/actions/jobs/401/logs`, { headers: HEADERS })
      ).text()
    ).split('\n')[0] ?? '',
    "2026-01-01T00:00:05.0000000Z Current runner version: '2.330.0'",
  )
}

async function main(): Promise<void> {
  const fake = await launch()
  const at = fake.endpoint
  try {
    await emptyRepository(at)
    await seededHistory(at)
    await supersededBlobs(at)
    await refsNameCommits(at)
    await abandonedRoot(at)
    await workflowsAndSettings(at)
    const reset = await fetch(`${at}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenants: [TENANT], fixture: 'v1' }),
    })
    check('/reset seeds the fixture', reset.status === 200, String(reset.status))

    // ---- `{ref}:{dir}` lists one directory, as GitHub's rev syntax does; the
    // point lookup sends it percent-encoded as one segment, and python's
    // client sends the colon raw
    const shallow = async (segment: string): Promise<{ status: number; body: JsonValue }> => {
      const r = await fetch(`${at}/repos/${REPO}/git/trees/${segment}`, { headers: HEADERS })
      return { status: r.status, body: (await r.json()) as JsonValue }
    }
    // docs/vendored is a submodule: GitHub lists a gitlink in a tree, and the
    // client is what drops it.
    const names = (body: JsonValue): JsonValue[] =>
      (field(body, 'tree') as JsonValue[]).map((row) => field(row, 'path'))
    const docs = await shallow('main%3Adocs')
    eq('an encoded ref:dir lists that directory', names(docs.body), [
      'architecture.md',
      'contributing.md',
      'release.md',
      'vendored',
    ])
    eq('a raw colon lists the same rows', names((await shallow('main:docs')).body), [
      'architecture.md',
      'contributing.md',
      'release.md',
      'vendored',
    ])
    eq(
      'an encoded slash reaches a nested directory',
      names((await shallow('main%3Asrc%2Fcache')).body).length,
      9,
    )
    eq('a path through a file is 422', (await shallow('main%3AREADME.md')).status, 422)
    eq('a missing directory is 404', (await shallow('main%3Anope')).status, 404)
    eq('an unknown ref is 404', (await shallow('gone%3Adocs')).status, 404)
    // A bare ref without recursive names only the root's own rows, uncut: the
    // truncated repository's per-directory walk asks for its root this way.
    const bareRoot = await get(`${at}/repos/integ/repo-trunc/git/trees/main`)
    eq('a bare ref lists the root shallow and whole', field(bareRoot, 'truncated'), false)
    check(
      'a bare ref lists no nested path',
      (field(bareRoot, 'tree') as JsonValue[]).every(
        (row) => !String(field(row, 'path')).includes('/'),
      ),
    )
    const whole = await get(`${at}/repos/${REPO}/git/trees/main?recursive=1`)
    const wholeRow = (field(whole, 'tree') as JsonValue[]).find(
      (row) => field(row, 'path') === 'docs/release.md',
    )
    const pointRow = (field(docs.body, 'tree') as JsonValue[]).find(
      (row) => field(row, 'path') === 'release.md',
    )
    eq(
      "a listed row carries the recursive tree row's sha",
      field(pointRow ?? null, 'sha'),
      field(wholeRow ?? null, 'sha'),
    )
    check('vanilla gh search matches Mirage', (await searchConformance(at)) > 0)

    // ---- an author the caller states is the author the fake keeps
    const t1 = await stage(at, 'tasks/one.md', '# one\n')
    const made = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task one',
      tree: t1,
      author: AUTHOR,
    })
    check('a commit is created', made.status === 201, String(made.status))
    eq('the response echoes the author verbatim', field(made.body, 'author'), AUTHOR)

    // The offset is the point. Normalizing it to UTC would answer the same
    // instant spelled differently, and a fixture that pinned +08:00 would read
    // back as something it did not write.
    const author = field(made.body, 'author')
    check(
      'the pinned offset survives',
      String(field(author, 'date')) === '2025-09-02T09:00:00+08:00',
      String(field(author, 'date')),
    )
    eq('a missing committer defaults to the author', field(made.body, 'committer'), AUTHOR)

    // ---- and it survives the round trip, which is what a reader sees
    const sha = String(field(made.body, 'sha') ?? '')
    const read = await get(`${at}/repos/${REPO}/git/commits/${sha}`)
    eq('GET /git/commits/:sha reports the author', field(read, 'author'), AUTHOR)
    eq('and the committer', field(read, 'committer'), AUTHOR)

    // ---- a commit exists before any ref names it, and until one does it is
    // on no branch's history, which is what "dangling" means: readable by sha,
    // absent from every list.
    const beforeAttach = await get(`${at}/repos/${REPO}/commits`)
    check(
      'a commit no ref names is not on a branch',
      Array.isArray(beforeAttach) && !beforeAttach.some((c) => String(field(c, 'sha')) === sha),
      sha,
    )

    // ---- the list endpoint, which is what "most recent commits" reads, once
    // the ref has been pointed at the commit
    const trunk = String(field(await get(`${at}/repos/${REPO}`), 'default_branch'))
    const attach = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha }),
    })
    check('the default ref takes the commit', attach.status === 200, String(attach.status))
    const listed = await get(`${at}/repos/${REPO}/commits`)
    const top = Array.isArray(listed) ? (listed[0] ?? null) : null
    eq('the commit list carries the author', field(field(top, 'commit'), 'author'), AUTHOR)

    // ---- a committer distinct from the author is kept distinct
    const t2 = await stage(at, 'tasks/two.md', '# two\n')
    const two = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task two',
      tree: t2,
      author: AUTHOR,
      committer: { name: 'Sam Iyer', email: 'sam@example.com', date: '2025-09-03T11:30:00+08:00' },
    })
    eq('a distinct committer is kept', field(two.body, 'committer'), {
      name: 'Sam Iyer',
      email: 'sam@example.com',
      date: '2025-09-03T11:30:00+08:00',
    })
    eq('and does not overwrite the author', field(two.body, 'author'), AUTHOR)

    // ---- an author naming only a date still gets a whole person
    const t3 = await stage(at, 'tasks/three.md', '# three\n')
    const dated = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task three',
      tree: t3,
      author: { date: '2025-09-04T08:00:00Z' },
    })
    eq('a date-only author is filled out', field(dated.body, 'author'), {
      name: 'integ-user',
      email: 'integ-user@users.noreply.github.com',
      date: '2025-09-04T08:00:00Z',
    })

    // ---- a commit that names nobody is unchanged, which is what the goldens
    // record: the author blocks are absent, not empty.
    const t4 = await stage(at, 'tasks/four.md', '# four\n')
    const bare = await post(`${at}/repos/${REPO}/git/commits`, { message: 'Add four', tree: t4 })
    check('a commit naming nobody has no author', field(bare.body, 'author') === null, 'absent')
    check(
      'and no committer',
      field(bare.body, 'committer') === null,
      String(field(bare.body, 'committer')),
    )

    // ---- a malformed author is refused rather than read as absent
    const t5 = await stage(at, 'tasks/five.md', '# five\n')
    const bad = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add five',
      tree: t5,
      author: 'Dana Wu <dana@example.com>',
    })
    check('a non-object author is 422', bad.status === 422, String(bad.status))
    const badc = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add five',
      tree: t5,
      committer: ['Dana Wu'],
    })
    check('a non-object committer is 422', badc.status === 422, String(badc.status))

    // ---- a committer without an author keeps the committer, and the author
    // fills with the endpoint's default identity rather than vanishing
    const tSolo = await stage(at, 'tasks/solo.md', '# solo\n')
    const solo = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add solo',
      tree: tSolo,
      committer: { name: 'Sam Iyer', email: 'sam@example.com', date: '2025-09-05T09:15:00+08:00' },
    })
    eq('a committer alone is kept', field(solo.body, 'committer'), {
      name: 'Sam Iyer',
      email: 'sam@example.com',
      date: '2025-09-05T09:15:00+08:00',
    })
    eq('and the author fills with the default identity', field(solo.body, 'author'), {
      name: 'integ-user',
      email: 'integ-user@users.noreply.github.com',
      date: '2026-01-01T00:00:00Z',
    })

    // ---- pointing a ref at a commit is what puts it on that branch's
    // history: a client that builds history stages a tree, creates the
    // commit, and PATCHes the ref, and the branch's commit list has to grow
    // by exactly that commit. The move is a move, not a copy: a commit a ref
    // took to a branch does not stay on the default branch's history.
    const mainBefore = await get(`${at}/repos/${REPO}/commits`)
    const mainCount = Array.isArray(mainBefore) ? mainBefore.length : 0
    const made6 = await post(`${at}/repos/${REPO}/git/refs`, {
      ref: 'refs/heads/task-1',
      sha: '',
    })
    check('a branch is created', made6.status === 201, String(made6.status))
    const branchBefore = await get(`${at}/repos/${REPO}/commits?sha=task-1`)
    const branchCount = Array.isArray(branchBefore) ? branchBefore.length : 0
    const t6 = await stage(at, 'tasks/six.md', '# six\n')
    const six = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task six',
      tree: t6,
      author: AUTHOR,
    })
    const sha6 = String(field(six.body, 'sha') ?? '')
    const moved = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-1`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6 }),
    })
    check('the ref moves', moved.status === 200, String(moved.status))
    const branchAfter = await get(`${at}/repos/${REPO}/commits?sha=task-1`)
    const rows = Array.isArray(branchAfter) ? branchAfter : []
    check(
      'the branch history grows by one',
      rows.length === branchCount + 1,
      `got ${String(rows.length)} want ${String(branchCount + 1)}`,
    )
    check('and its head is the commit the ref took', String(field(rows[0] ?? null, 'sha')) === sha6)
    eq(
      'with the message the commit stated',
      field(field(rows[0] ?? null, 'commit'), 'message'),
      'Add task six',
    )
    eq(
      'and the author it stated',
      field(field(field(rows[0] ?? null, 'commit'), 'author'), 'date'),
      AUTHOR.date,
    )
    const mainAfter = await get(`${at}/repos/${REPO}/commits`)
    check(
      'the default branch does not keep it',
      Array.isArray(mainAfter) && mainAfter.length === mainCount,
      `got ${String(Array.isArray(mainAfter) ? mainAfter.length : -1)} want ${String(mainCount)}`,
    )
    const read6 = await get(`${at}/repos/${REPO}/git/commits/${sha6}`)
    eq('GET /git/commits/:sha still answers after the move', field(read6, 'sha'), sha6)

    // ---- the moved commit freed its sequence on the default branch, so a
    // later commit reusing that sequence AND the message must still get its
    // own sha, or a ref update resolving the sha publishes the wrong tree.
    const t7 = await stage(at, 'tasks/seven.md', '# seven\n')
    const seven = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task six',
      tree: t7,
    })
    check(
      'a same-message commit after the move gets its own sha',
      String(field(seven.body, 'sha')) !== sha6,
      sha6,
    )

    // ---- a second ref pointing at the same commit shares it: git commits
    // are reachable from many refs, so attaching one to another branch copies
    // it onto that history rather than stealing it from the first.
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-2', sha: '' })
    const shared = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-2`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6 }),
    })
    check('a second ref takes the same commit', shared.status === 200, String(shared.status))
    const firstList = await get(`${at}/repos/${REPO}/commits?sha=task-1`)
    check(
      'the first branch keeps it',
      Array.isArray(firstList) && String(field(firstList[0] ?? null, 'sha')) === sha6,
      String(field((Array.isArray(firstList) ? firstList[0] : null) ?? null, 'sha')),
    )
    const secondList = await get(`${at}/repos/${REPO}/commits?sha=task-2`)
    check(
      'and the second branch gains it',
      Array.isArray(secondList) && String(field(secondList[0] ?? null, 'sha')) === sha6,
      String(field((Array.isArray(secondList) ? secondList[0] : null) ?? null, 'sha')),
    )

    // ---- resetting a branch to an older commit is a forced update: refused
    // without `force`, and with it the requested commit becomes the head and
    // the discarded one leaves the branch's history.
    const t8 = await stage(at, 'tasks/eight.md', '# eight\n')
    const eight = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task eight',
      tree: t8,
      parents: [sha6],
    })
    const sha8 = String(field(eight.body, 'sha') ?? '')
    const advance = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-1`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha8 }),
    })
    check(
      'a commit stating its parent advances the ref unforced',
      advance.status === 200,
      String(advance.status),
    )
    const soft = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-1`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6 }),
    })
    check('a backward update without force is refused', soft.status === 422, String(soft.status))
    const heldRef = await get(`${at}/repos/${REPO}/git/ref/heads/task-1`)
    eq('and the head is unchanged', field(field(heldRef, 'object'), 'sha'), sha8)
    const forced = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-1`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6, force: true }),
    })
    check('a forced backward update lands', forced.status === 200, String(forced.status))
    const resetRef = await get(`${at}/repos/${REPO}/git/ref/heads/task-1`)
    eq('the head is the requested commit', field(field(resetRef, 'object'), 'sha'), sha6)
    const resetList = await get(`${at}/repos/${REPO}/commits?sha=task-1`)
    check(
      'and the discarded commit left the history',
      Array.isArray(resetList) && !resetList.some((c) => String(field(c, 'sha')) === sha8),
      sha8,
    )
    // Abandoned, not destroyed: nothing points at it, and it still answers,
    // which is what the vendor does with a dangling commit.
    const dangling = await get(`${at}/repos/${REPO}/git/commits/${sha8}`)
    eq('the abandoned commit is still readable by sha', field(dangling, 'sha'), sha8)

    // ---- two commits telling the same tree and message apart only by their
    // author are two commits, even when a move freed the first one's sequence.
    const t9 = await stage(at, 'tasks/nine.md', '# nine\n')
    const nineA = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task nine',
      tree: t9,
      author: AUTHOR,
    })
    const sha9a = String(field(nineA.body, 'sha') ?? '')
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-3', sha: '' })
    await fetch(`${at}/repos/${REPO}/git/refs/heads/task-3`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha9a }),
    })
    const nineB = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task nine',
      tree: t9,
      author: { name: 'Sam Iyer', email: 'sam@example.com', date: '2025-09-06T10:00:00+08:00' },
    })
    check(
      'a same-tree same-message commit by another author gets its own sha',
      String(field(nineB.body, 'sha')) !== sha9a,
      sha9a,
    )

    // ---- a reset is a reset even when the requested commit's row lives on
    // another branch: it is older than the branch's commits, so the update is
    // not a fast forward, and forcing it discards the newer commits without
    // taking anything from the branch that holds the requested one.
    const tK = await stage(at, 'tasks/ten.md', '# ten\n')
    const ten = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task ten',
      tree: tK,
    })
    const shaK = String(field(ten.body, 'sha') ?? '')
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-4', sha: '' })
    await fetch(`${at}/repos/${REPO}/git/refs/heads/task-4`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaK }),
    })
    const crossSoft = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-4`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6 }),
    })
    check(
      'a cross-branch backward update without force is refused',
      crossSoft.status === 422,
      String(crossSoft.status),
    )
    const crossForced = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-4`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: sha6, force: true }),
    })
    check('and lands when forced', crossForced.status === 200, String(crossForced.status))
    const crossRef = await get(`${at}/repos/${REPO}/git/ref/heads/task-4`)
    eq(
      'the head is the requested commit after the reset',
      field(field(crossRef, 'object'), 'sha'),
      sha6,
    )
    const crossList = await get(`${at}/repos/${REPO}/commits?sha=task-4`)
    check(
      'the newer commit left the reset branch',
      Array.isArray(crossList) && !crossList.some((c) => String(field(c, 'sha')) === shaK),
      shaK,
    )
    const donorList = await get(`${at}/repos/${REPO}/commits?sha=task-1`)
    check(
      'and the branch holding the commit keeps it',
      Array.isArray(donorList) && String(field(donorList[0] ?? null, 'sha')) === sha6,
      String(field((Array.isArray(donorList) ? donorList[0] : null) ?? null, 'sha')),
    )

    // ---- a client may prepare several commits before touching any ref. Each
    // states the one it builds on, so the two form a chain and attaching them
    // in turn is an ordinary fast forward, however long the ref sat still.
    const trunkHead = String(
      field(field(await get(`${at}/repos/${REPO}/git/ref/heads/${trunk}`), 'object'), 'sha'),
    )
    const tw = await stage(at, 'tasks/twelve.md', '# twelve\n')
    const twelve = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task twelve',
      tree: tw,
      parents: [trunkHead],
    })
    const shaTw = String(field(twelve.body, 'sha') ?? '')
    const th = await stage(at, 'tasks/thirteen.md', '# thirteen\n')
    const thirteen = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task thirteen',
      tree: th,
      parents: [shaTw],
    })
    const shaTh = String(field(thirteen.body, 'sha') ?? '')
    const parked1 = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaTw }),
    })
    check(
      'attaching a prepared commit needs no force with another prepared above',
      parked1.status === 200,
      String(parked1.status),
    )
    const trunkRef1 = await get(`${at}/repos/${REPO}/git/ref/heads/${trunk}`)
    eq('and the ref reports it', field(field(trunkRef1, 'object'), 'sha'), shaTw)
    const parked2 = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaTh }),
    })
    check(
      'attaching the second prepared commit advances',
      parked2.status === 200,
      String(parked2.status),
    )
    const trunkRef2 = await get(`${at}/repos/${REPO}/git/ref/heads/${trunk}`)
    eq('and the ref reports the advance', field(field(trunkRef2, 'object'), 'sha'), shaTh)
    const wholeChain = await get(`${at}/repos/${REPO}/commits`)
    check(
      'the branch lists the whole chain it was walked onto',
      Array.isArray(wholeChain) &&
        wholeChain.some((c) => String(field(c, 'sha')) === shaTh) &&
        wholeChain.some((c) => String(field(c, 'sha')) === shaTw),
      String(Array.isArray(wholeChain) ? wholeChain.length : -1),
    )

    // ---- a commit that does NOT build on the head is a divergence, not an
    // advance, so pointing the ref at it is forced even though it is the
    // newest thing in the repository. This is the difference stated parents
    // buy: order of creation is not ancestry.
    const ts = await stage(at, 'tasks/sibling.md', '# sibling\n')
    const sibling = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add a sibling',
      tree: ts,
      parents: [shaTw],
    })
    const shaSib = String(field(sibling.body, 'sha') ?? '')
    const diverge = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaSib }),
    })
    check('a divergent sibling is refused unforced', diverge.status === 422, String(diverge.status))
    const forcedSib = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaSib, force: true }),
    })
    check('and lands when forced', forcedSib.status === 200, String(forcedSib.status))

    // ---- a /contents write advanced its ref the moment it landed, so it is
    // attached history: a backward PATCH past it is forced, and forcing
    // discards it like any other commit the reset abandons.
    const tF = await stage(at, 'tasks/fourteen.md', '# fourteen\n')
    const fourteen = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Add task fourteen',
      tree: tF,
    })
    const shaF = String(field(fourteen.body, 'sha') ?? '')
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-5', sha: '' })
    await fetch(`${at}/repos/${REPO}/git/refs/heads/task-5`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaF }),
    })
    const put = await fetch(`${at}/repos/${REPO}/contents/tasks/fifteen.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Add fifteen via contents',
        content: Buffer.from('# fifteen\n').toString('base64'),
        branch: 'task-5',
      }),
    })
    check('a contents write lands on the branch', put.status === 201, String(put.status))
    const pastSoft = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-5`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaF }),
    })
    check(
      'a backward PATCH past a contents commit is refused without force',
      pastSoft.status === 422,
      String(pastSoft.status),
    )
    const pastForced = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-5`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaF, force: true }),
    })
    check('and lands when forced', pastForced.status === 200, String(pastForced.status))
    const pastRef = await get(`${at}/repos/${REPO}/git/ref/heads/task-5`)
    eq('the ref reports the reset commit', field(field(pastRef, 'object'), 'sha'), shaF)
    const pastList = await get(`${at}/repos/${REPO}/commits?sha=task-5`)
    check(
      'and the contents commit left the history',
      Array.isArray(pastList) &&
        !pastList.some(
          (c) => String(field(field(c, 'commit'), 'message')) === 'Add fifteen via contents',
        ),
      'Add fifteen via contents',
    )

    // ---- a /contents write after a forced reset cannot reproduce the sha of
    // the commit the reset abandoned: the address covers the bytes, so the
    // same message on the same parent with different content is a different
    // commit.
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-6', sha: '' })
    const base6 = String(
      field(field(await get(`${at}/repos/${REPO}/git/ref/heads/task-6`), 'object'), 'sha'),
    )
    const w1 = await fetch(`${at}/repos/${REPO}/contents/tasks/reused.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'One message',
        content: Buffer.from('first\n').toString('base64'),
        branch: 'task-6',
      }),
    })
    const firstSha = String(field(field(await w1.json(), 'commit'), 'sha'))
    if (base6 !== '') {
      await fetch(`${at}/repos/${REPO}/git/refs/heads/task-6`, {
        method: 'PATCH',
        headers: HEADERS,
        body: JSON.stringify({ sha: base6, force: true }),
      })
    }
    const w2 = await fetch(`${at}/repos/${REPO}/contents/tasks/reused.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'One message',
        content: Buffer.from('second, different bytes\n').toString('base64'),
        branch: 'task-6',
      }),
    })
    const secondSha = String(field(field(await w2.json(), 'commit'), 'sha'))
    check(
      'a contents commit after a reset cannot reuse an abandoned sha',
      firstSha !== secondSha && secondSha !== '',
      `${firstSha} vs ${secondSha}`,
    )

    // ---- a commit prepared before the branch moved on is stale: the ref has
    // advanced through /contents since, so pointing back at it is a reset and
    // needs force, whatever order the two were created in.
    const tStale = await stage(at, 'tasks/stale.md', '# stale\n')
    const staleHead = String(
      field(field(await get(`${at}/repos/${REPO}/git/ref/heads/task-6`), 'object'), 'sha'),
    )
    const stale = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Prepared before the write',
      tree: tStale,
      parents: [staleHead],
    })
    const shaStale = String(field(stale.body, 'sha') ?? '')
    await fetch(`${at}/repos/${REPO}/contents/tasks/after.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Written after the commit was prepared',
        content: Buffer.from('after\n').toString('base64'),
        branch: 'task-6',
      }),
    })
    const staleSoft = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-6`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaStale }),
    })
    check(
      'a stale prepared commit is refused once a contents write moved the ref',
      staleSoft.status === 422,
      String(staleSoft.status),
    )
    const staleForced = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-6`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaStale, force: true }),
    })
    check('and lands when forced', staleForced.status === 200, String(staleForced.status))

    // ---- a branch can be created directly at a commit no ref names yet,
    // which is the two-step a client takes when it builds a branch from
    // scratch: commit, then point a new ref at it. The branch starts at that
    // commit and carries its tree, rather than inheriting some other ref's.
    const tN = await stage(at, 'tasks/newbranch.md', '# new branch\n')
    const newborn = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Commit for a branch that does not exist yet',
      tree: tN,
    })
    const shaN = String(field(newborn.body, 'sha') ?? '')
    const atCommit = await post(`${at}/repos/${REPO}/git/refs`, {
      ref: 'refs/heads/task-7',
      sha: shaN,
    })
    check(
      'a ref can be created at a dangling commit',
      atCommit.status === 201,
      String(atCommit.status),
    )
    eq('and the new ref reports that commit', field(field(atCommit.body, 'object'), 'sha'), shaN)
    const bornRef = await get(`${at}/repos/${REPO}/git/ref/heads/task-7`)
    eq('which survives a re-read', field(field(bornRef, 'object'), 'sha'), shaN)
    const bornList = await get(`${at}/repos/${REPO}/commits?sha=task-7`)
    check(
      'the branch history starts at that commit',
      Array.isArray(bornList) && String(field(bornList[0] ?? null, 'sha')) === shaN,
      String(field((Array.isArray(bornList) ? bornList[0] : null) ?? null, 'sha')),
    )
    const bornFile = await fetch(`${at}/repos/${REPO}/contents/tasks/newbranch.md?ref=task-7`, {
      headers: HEADERS,
    })
    check("and carries that commit's tree", bornFile.status === 200, String(bornFile.status))

    // ---- a seeded branch carries files and no stored commit, and the ref
    // endpoint answers for it with a synthesized root. That root is the ref's
    // position, so it is what a first update is judged against: a commit that
    // does not build on it would discard the seeded tree, which is a reset.
    const reseed = await fetch(`${at}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenants: [TENANT], fixture: 'v1' }),
    })
    check('the fixture is seeded again', reseed.status === 200, String(reseed.status))
    const seededRoot = String(
      field(field(await get(`${at}/repos/${REPO}/git/ref/heads/${trunk}`), 'object'), 'sha'),
    )
    check('a seeded branch answers with a root commit', seededRoot !== '', seededRoot)

    // A commit that states no parent at all is a root commit, which is what an
    // empty `parents` means: it is not the absent field, and it must not be
    // quietly re-parented onto the branch head.
    const tR = await stage(at, 'tasks/rootish.md', '# rootish\n')
    const rootish = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'A root commit',
      tree: tR,
      parents: [],
    })
    const shaRootish = String(field(rootish.body, 'sha') ?? '')
    const implied = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'A root commit',
      tree: tR,
    })
    check(
      'an empty parents list is not the same commit as an absent one',
      String(field(implied.body, 'sha')) !== shaRootish,
      `${shaRootish} vs ${String(field(implied.body, 'sha'))}`,
    )

    const overwrite = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaRootish }),
    })
    check(
      'a commit that does not build on the seeded root is refused',
      overwrite.status === 422,
      String(overwrite.status),
    )
    const keptRef = await get(`${at}/repos/${REPO}/git/ref/heads/${trunk}`)
    eq(
      'and the branch still answers with its root',
      field(field(keptRef, 'object'), 'sha'),
      seededRoot,
    )

    // The same update, from a commit that DOES build on that root, is an
    // ordinary advance: this is the flow every client takes on a fresh repo.
    const onRoot = await post(`${at}/repos/${REPO}/git/commits`, {
      message: 'Built on the seeded root',
      tree: tR,
      parents: [seededRoot],
    })
    const shaOnRoot = String(field(onRoot.body, 'sha') ?? '')
    const advanced = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaOnRoot }),
    })
    check(
      'a commit built on the root advances unforced',
      advanced.status === 200,
      String(advanced.status),
    )
    const forcedOver = await fetch(`${at}/repos/${REPO}/git/refs/heads/${trunk}`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaRootish, force: true }),
    })
    check(
      'and the refused one lands when forced',
      forcedOver.status === 200,
      String(forcedOver.status),
    )

    // ---- a commit created with `parents: []` IS a root, so a branch standing
    // on it stands on nothing further. The synthesized root is the floor for a
    // chain that never reaches one of its own, not a parent stapled under
    // every history.
    const rootedList = await get(`${at}/repos/${REPO}/commits?sha=${trunk}`)
    check(
      'a stored root commit is the end of its branch history',
      Array.isArray(rootedList) &&
        rootedList.length === 1 &&
        String(field(rootedList[0] ?? null, 'sha')) === shaRootish,
      String(Array.isArray(rootedList) ? rootedList.length : -1),
    )

    // ---- a commit written through /contents is an object like any other, so
    // a ref can be pointed at it. It reached the branch by advancing the ref,
    // which is the one thing that used to make it unnameable: it carried no
    // staged tree, and the ref endpoint read a missing tree as a missing
    // commit.
    await post(`${at}/repos/${REPO}/git/refs`, { ref: 'refs/heads/task-8', sha: '' })
    const c1 = await fetch(`${at}/repos/${REPO}/contents/tasks/first.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Add the first file',
        content: Buffer.from('# first\n').toString('base64'),
        branch: 'task-8',
      }),
    })
    const shaC1 = String(field(field((await c1.json()) as JsonValue, 'commit'), 'sha') ?? '')
    check('a contents write records a commit', shaC1 !== '', shaC1)
    const selfMove = await fetch(`${at}/repos/${REPO}/git/refs/heads/task-8`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ sha: shaC1 }),
    })
    check(
      'a ref can be moved onto a contents commit',
      selfMove.status === 200,
      String(selfMove.status),
    )

    // ---- and that commit is a SNAPSHOT: a branch created at it carries the
    // files it recorded, not whatever the branch it came from holds now.
    const c2 = await fetch(`${at}/repos/${REPO}/contents/tasks/second.md`, {
      method: 'PUT',
      headers: HEADERS,
      body: JSON.stringify({
        message: 'Add the second file',
        content: Buffer.from('# second\n').toString('base64'),
        branch: 'task-8',
      }),
    })
    check('the branch advances past it', c2.status === 201, String(c2.status))
    const snap = await post(`${at}/repos/${REPO}/git/refs`, {
      ref: 'refs/heads/task-8-snap',
      sha: shaC1,
    })
    check('a ref can be created at the older one', snap.status === 201, String(snap.status))
    eq('and reports it', field(field(snap.body, 'object'), 'sha'), shaC1)
    const kept = await fetch(`${at}/repos/${REPO}/contents/tasks/first.md?ref=task-8-snap`, {
      headers: HEADERS,
    })
    check(
      'the snapshot carries what that commit recorded',
      kept.status === 200,
      String(kept.status),
    )
    const later = await fetch(`${at}/repos/${REPO}/contents/tasks/second.md?ref=task-8-snap`, {
      headers: HEADERS,
    })
    check('and not what the branch gained afterwards', later.status === 404, String(later.status))

    // REST and GraphQL return comments oldest first.
    const opened = await post(`${at}/repos/${REPO}/issues`, {
      title: 'License info. needed',
      body: 'Could you provide license info.?',
    })
    check('an issue is opened', opened.status === 201, String(opened.status))
    const issueNo = String(field(opened.body, 'number') ?? '')
    const empty = await get(`${at}/repos/${REPO}/issues/${issueNo}/comments`)
    eq('a fresh issue lists no comments', empty, [])
    for (const body of ['first', 'second']) {
      const said = await post(`${at}/repos/${REPO}/issues/${issueNo}/comments`, { body })
      check(`a comment is posted (${body})`, said.status === 201, String(said.status))
    }
    const thread = await get(`${at}/repos/${REPO}/issues/${issueNo}/comments`)
    const bodies = Array.isArray(thread) ? thread.map((c) => field(c, 'body')) : []
    eq('and both come back oldest first', bodies, ['first', 'second'])
    check(
      'each carries the author a grader checks',
      Array.isArray(thread) && thread.every((c) => field(field(c, 'user'), 'login') !== null),
      JSON.stringify(thread).slice(0, 200),
    )
    const noSuch = await fetch(`${at}/repos/${REPO}/issues/4242/comments`, { headers: HEADERS })
    check('an issue that is not there is 404', noSuch.status === 404, String(noSuch.status))

    // ---- `user:` and `org:` NARROW, which is the only reason to ask with one.
    // A caller scoped to one account and handed every account's repositories
    // cannot tell from the answer that it was not scoped at all.
    const OTHER = 'integ-archive'
    const born = await post(`${at}/orgs/${OTHER}/repos`, { name: 'repo-archived' })
    check('a repo is created under a second owner', born.status === 201, String(born.status))

    const found = async (q: string): Promise<JsonValue[]> => {
      const body = await get(`${at}/search/repositories?q=${encodeURIComponent(q)}`)
      const items = field(body, 'items')
      return Array.isArray(items) ? items.map((r) => field(r, 'full_name')).sort() : []
    }

    eq('`user:` lists that account and no other', await found('user:integ'), [
      'integ/data-v1',
      'integ/repo-cli',
      'integ/repo-trunc',
      'integ/repo-v1',
    ])
    eq('`org:` scopes the same way', await found(`org:${OTHER}`), [`${OTHER}/repo-archived`])
    eq('an account holding nothing is empty, not everything', await found('user:nobody'), [])
    eq('two of them OR together', await found(`user:nobody org:${OTHER}`), [
      `${OTHER}/repo-archived`,
    ])
    // The scope ANDs with the terms: `repo` matches all four rows by name, and
    // the owner is what keeps the fourth out.
    eq('a term widens only within the scope', await found('user:integ repo'), [
      'integ/repo-cli',
      'integ/repo-trunc',
      'integ/repo-v1',
    ])
    // Unscoped, that same term reaches every owner -- the looseness the fake
    // keeps on purpose, so that a caller hunting a row is shown it.
    eq('and reaches every owner when nothing scopes it', await found('repo'), [
      `${OTHER}/repo-archived`,
      'integ/repo-cli',
      'integ/repo-trunc',
      'integ/repo-v1',
    ])

    // ---- code search answers a query that names no repository, over every
    // repository the tenant holds, because an authenticated caller of the live
    // API is answered over all of GitHub rather than refused. The scope rules
    // below were measured against api.github.com on 2026-09-24. This block sits
    // after `found('repo')`, which `Repo-Mixed` would otherwise join, and before
    // the reset that reseeds.
    const codeSearch = async (
      q: string | null,
      prefix = '',
    ): Promise<{ status: number; body: JsonValue; items: string[] }> => {
      const query = q === null ? '' : `?q=${encodeURIComponent(q)}`
      const r = await fetch(`${at}${prefix}/search/code${query}`, { headers: HEADERS })
      const body = (await r.json()) as JsonValue
      const rows = field(body, 'items')
      // Keyed by the item's own `repository`, so an item filed under the wrong
      // repository reads as a different hit.
      const items = Array.isArray(rows)
        ? rows.map(
            (i) =>
              `${String(field(field(i, 'repository'), 'full_name'))}/${String(field(i, 'path'))}`,
          )
        : []
      return { status: r.status, body, items }
    }
    const hits = async (q: string): Promise<JsonValue> => {
      const r = await codeSearch(q)
      return r.status === 200 ? r.items : `HTTP ${String(r.status)}`
    }
    const MARK = 'quokkaseed'

    eq(
      'an unscoped query is answered, not refused',
      await codeSearch(MARK).then((r) => [r.status, r.body]),
      [200, { total_count: 0, incomplete_results: false, items: [] }],
    )

    const mixed = await post(`${at}/orgs/${OTHER}/repos`, { name: 'Repo-Mixed' })
    check('a mixed-case repo is created', mixed.status === 201, String(mixed.status))
    const CASED_OWNER = 'Integ-Case'
    const cased = await post(`${at}/orgs/${CASED_OWNER}/repos`, { name: 'zz-repo' })
    check('a repo is created under a mixed-case owner', cased.status === 201, String(cased.status))
    const write = async (repo: string, path: string, text: string): Promise<JsonValue> => {
      const r = await fetch(`${at}/repos/${repo}/contents/${path}`, {
        method: 'PUT',
        headers: HEADERS,
        body: JSON.stringify({
          message: `add ${path}`,
          content: Buffer.from(text).toString('base64'),
        }),
      })
      check(`a file is written to ${repo}`, r.status === 201, String(r.status))
      return field(field((await r.json()) as JsonValue, 'content'), 'sha')
    }
    // Three owners, one of them mixed-case, a mixed-case name, and `alpha` in
    // only two files. The repositories created last sort first by full name,
    // and `Integ-Case/zz-repo` sorts first by full name but last by name, so
    // creation order, name order and full-name order all read differently.
    await write(`${CASED_OWNER}/zz-repo`, 'docs/cased.md', `${MARK}\n`)
    const mixedSha = await write(`${OTHER}/Repo-Mixed`, 'notes/mixed.md', `${MARK}\n`)
    await write(`${OTHER}/repo-archived`, 'notes/shared.md', `${MARK} alpha\n`)
    await write('integ/repo-cli', 'notes/shared.md', `${MARK} alpha\n`)
    await write('integ/repo-v1', 'docs/shared.md', `${MARK}\n`)
    const MIXED = `${OTHER}/Repo-Mixed/notes/mixed.md`
    const ARCHIVED = `${OTHER}/repo-archived/notes/shared.md`
    const CLI = 'integ/repo-cli/notes/shared.md'
    const V1 = 'integ/repo-v1/docs/shared.md'
    const CASED = `${CASED_OWNER}/zz-repo/docs/cased.md`
    const ALL = [CASED, MIXED, ARCHIVED, CLI, V1]

    const everything = await codeSearch(MARK)
    eq('unscoped, every repository is searched, in full-name order', everything.items, ALL)
    eq('and the count is every hit', field(everything.body, 'total_count'), 5)
    const hitRows = field(everything.body, 'items')
    const repoOf = (row: JsonValue | undefined): JsonValue => {
      const repo = field(row ?? null, 'repository')
      return { name: field(repo, 'name'), full_name: field(repo, 'full_name') }
    }
    eq(
      'each hit names its own repository (first)',
      repoOf(Array.isArray(hitRows) ? hitRows[0] : undefined),
      {
        name: 'zz-repo',
        full_name: `${CASED_OWNER}/zz-repo`,
      },
    )
    eq(
      'each hit names its own repository (last)',
      repoOf(Array.isArray(hitRows) ? hitRows.at(-1) : undefined),
      {
        name: 'repo-v1',
        full_name: 'integ/repo-v1',
      },
    )
    for (const prefix of ['', '/api/v3']) {
      const r = await codeSearch('"Mixture-of-Depths"', prefix)
      eq(
        `a query matching nothing is a 200 with nothing (${prefix || '/'})`,
        [r.status, r.body],
        [200, { total_count: 0, incomplete_results: false, items: [] }],
      )
    }

    // `user:` and `org:` narrow and OR together; an owner compares
    // case-insensitively on both sides, as `searchRepos` does.
    eq('`user:` narrows code search to that owner', await hits(`user:integ ${MARK}`), [CLI, V1])
    eq('`org:` narrows the same way', await hits(`org:${OTHER} ${MARK}`), [MIXED, ARCHIVED])
    eq('an owner value compares case-insensitively', await hits(`user:INTEG-Archive ${MARK}`), [
      MIXED,
      ARCHIVED,
    ])
    eq('and so does the owner it is compared with', await hits(`org:integ-case ${MARK}`), [CASED])
    eq('an owner holding nothing is empty, not everything', await hits(`user:nobody ${MARK}`), [])
    eq('two owners OR together', await hits(`user:nobody org:${OTHER} ${MARK}`), [MIXED, ARCHIVED])

    // Several `repo:` OR together; with an owner as well, the two groups AND.
    eq(
      'several `repo:` OR together',
      await hits(`repo:integ/repo-cli repo:${OTHER}/repo-archived ${MARK}`),
      [ARCHIVED, CLI],
    )
    const twice = await codeSearch(`repo:integ/repo-cli repo:integ/repo-cli ${MARK}`)
    eq(
      'a repo named twice is searched once',
      [twice.items, field(twice.body, 'total_count')],
      [[CLI], 1],
    )
    eq('`repo:` and `user:` intersect', await hits(`repo:integ/repo-cli user:integ ${MARK}`), [CLI])
    eq(
      '`repo:` and `org:` intersect',
      await hits(`repo:integ/repo-cli repo:${OTHER}/repo-archived org:integ ${MARK}`),
      [CLI],
    )
    // Live refuses a disjoint intersection with a query-parse 422; an empty
    // answer is the looser equivalent and carries no engine artefact.
    eq(
      'a disjoint intersection is empty',
      await hits(`repo:integ/repo-cli user:${OTHER} ${MARK}`),
      [],
    )
    eq(
      'a missing repo among several is skipped',
      await hits(`repo:integ/repo-cli repo:integ/no-such ${MARK}`),
      [CLI],
    )
    eq('a query naming only a missing repo is empty', await hits(`repo:integ/no-such ${MARK}`), [])
    eq(
      'an owner does not widen a missing repository',
      await hits(`repo:integ/no-such user:integ ${MARK}`),
      [],
    )
    eq('a `repo:` value is taken verbatim', await hits(`repo:${OTHER}/Repo-Mixed ${MARK}`), [MIXED])

    // Qualifier names are exact and case-sensitive, as live reads them;
    // anything else is a term, split by the tokenizer.
    eq('a word holding `::` stays terms', await hits(`${MARK}::alpha`), [ARCHIVED, CLI])
    eq(
      'an uppercase qualifier name is a term',
      await hits(`repo:integ/repo-v1 REPO:integ/repo-cli ${MARK}`),
      [],
    )
    eq('a negated qualifier is a term', await hits(`-repo:integ/repo-cli ${MARK}`), [])
    // Content and metadata filters are dropped rather than matched as words,
    // which only ever widens; live narrows by them.
    for (const name of ['language', 'extension', 'filename', 'in', 'size', 'fork']) {
      eq(`\`${name}:\` is dropped`, await hits(`repo:integ/repo-cli ${name}:x ${MARK}`), [CLI])
    }
    eq('and dropping one does not scope', await hits(`language:x ${MARK}`), ALL)
    // Live refuses an empty qualifier value with a query-parse 422.
    eq('an empty `user:` is dropped', await hits(`user: ${MARK}`), ALL)
    eq('an empty `repo:` is dropped', await hits(`repo: ${MARK}`), ALL)
    // Live lists every file in scope; the fake matches files by terms only.
    eq('a query of only a scope is empty', await hits('user:integ'), [])
    eq('a query of only a dropped filter is empty', await hits('language:python'), [])

    eq('`path:` narrows each repository', await hits(`path:notes ${MARK}`), [MIXED, ARCHIVED, CLI])
    eq('a term compares case-insensitively', await hits(`repo:integ/repo-cli QuokkaSeed`), [CLI])
    eq(
      'a `path:` value is taken verbatim',
      await hits(`repo:integ/repo-cli path:Notes ${MARK}`),
      [],
    )
    const one = await codeSearch(`repo:${OTHER}/Repo-Mixed ${MARK}`)
    const blobs = field(one.body, 'items')
    eq(
      'a hit carries the blob it names',
      Array.isArray(blobs)
        ? blobs.map((row) => ({
            name: field(row, 'name'),
            path: field(row, 'path'),
            sha: field(row, 'sha'),
            score: field(row, 'score'),
            repository: repoOf(row),
          }))
        : blobs,
      [
        {
          name: 'mixed.md',
          path: 'notes/mixed.md',
          sha: mixedSha,
          score: 1,
          repository: { name: 'Repo-Mixed', full_name: `${OTHER}/Repo-Mixed` },
        },
      ],
    )
    for (const prefix of ['', '/api/v3']) {
      for (const q of ['', '  ', null]) {
        const r = await codeSearch(q, prefix)
        eq(
          `an empty query is refused (${JSON.stringify(q)}, ${prefix || '/'})`,
          [r.status, field(r.body, 'message')],
          [422, 'Validation Failed'],
        )
      }
    }

    const commentsReset = await fetch(`${at}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenants: [TENANT], fixture: 'comments' }),
    })
    check('comment metadata fixture is seeded', commentsReset.status === 200)
    const query = `query($cursor: String) {
      repository(owner: "integ", name: "repo-comments") {
        issueOrPullRequest(number: 1) { ... on Issue {
          comments(first: 1, after: $cursor) {
            nodes { body author { login } authorAssociation includesCreatedEdit
              isMinimized minimizedReason viewerDidAuthor reactionGroups { content users { totalCount } } }
            pageInfo { hasNextPage endCursor }
          }
        } }
      }
    }`
    const graph = async (cursor: JsonValue): Promise<JsonValue> => {
      const response = await post(`${at}/graphql`, { query, variables: { cursor } })
      eq('GraphQL response has no errors', field(response.body, 'errors'), null)
      return field(
        field(field(field(response.body, 'data'), 'repository'), 'issueOrPullRequest'),
        'comments',
      )
    }
    const firstPage = await graph(null)
    const nodes = field(firstPage, 'nodes') as JsonValue[]
    eq('first GraphQL page respects its limit', nodes.length, 1)
    eq('GraphQL preserves nullable author and comment metadata', nodes[0] ?? null, {
      body: 'comment 1',
      author: null,
      authorAssociation: 'CONTRIBUTOR',
      includesCreatedEdit: true,
      isMinimized: true,
      minimizedReason: 'OUTDATED',
      viewerDidAuthor: false,
      reactionGroups: [
        { content: 'THUMBS_UP', users: { totalCount: 2 } },
        { content: 'LAUGH', users: { totalCount: 0 } },
      ],
    })
    eq('first page has a continuation', field(field(firstPage, 'pageInfo'), 'hasNextPage'), true)
    const lastPage = await graph(field(field(firstPage, 'pageInfo'), 'endCursor'))
    eq(
      'cursor advances to the last comment',
      (field(lastPage, 'nodes') as JsonValue[]).map((row) => field(row, 'body')),
      ['comment 2'],
    )
    eq('last page terminates pagination', field(field(lastPage, 'pageInfo'), 'hasNextPage'), false)

    // ---- GraphQL repository lists honour orderBy and filters, and a fork's
    // parent is found by identity, so renaming the source keeps it
    const v1Seed = await fetch(`${at}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenants: [TENANT], fixture: 'v1' }),
    })
    check('the v1 fixture is seeded again', v1Seed.status === 200)
    const repositoryNames = async (login: string, args: string): Promise<JsonValue[]> => {
      const r = await post(`${at}/graphql`, {
        query: `{ repositoryOwner(login: "${login}") { repositories(first: 10${args}) { nodes { name } } } }`,
      })
      eq(`repositories(${args}) has no errors`, field(r.body, 'errors'), null)
      const page = field(field(field(r.body, 'data'), 'repositoryOwner'), 'repositories')
      return (field(page, 'nodes') as JsonValue[]).map((node) => field(node, 'name'))
    }
    eq(
      'repositories order by name ascending',
      await repositoryNames('integ', ', orderBy: { field: NAME, direction: ASC }'),
      ['data-v1', 'repo-cli', 'repo-trunc', 'repo-v1'],
    )
    eq(
      'repositories order by name descending',
      await repositoryNames('integ', ', orderBy: { field: NAME, direction: DESC }'),
      ['repo-v1', 'repo-trunc', 'repo-cli', 'data-v1'],
    )
    eq(
      'repositories a push order ties are listed by name',
      await repositoryNames('integ', ', orderBy: { field: PUSHED_AT, direction: DESC }'),
      ['data-v1', 'repo-cli', 'repo-trunc', 'repo-v1'],
    )
    const forked = await post(`${at}/repos/integ/repo-v1/forks`, { name: 'v1-fork' })
    check('the fork is created', forked.status < 300, String(forked.status))
    const renamed = await fetch(`${at}/repos/integ/repo-v1`, {
      method: 'PATCH',
      headers: HEADERS,
      body: JSON.stringify({ name: 'repo-v1-moved' }),
    })
    check('the source is renamed', renamed.status === 200, String(renamed.status))
    const parent = await post(`${at}/graphql`, {
      query:
        '{ repository(owner: "integ-user", name: "v1-fork") { isFork parent { name owner { login } } } }',
    })
    eq('a fork names its parent under the name it carries now', field(parent.body, 'data'), {
      repository: { isFork: true, parent: { name: 'repo-v1-moved', owner: { login: 'integ' } } },
    })
    eq(
      'isFork narrows a repository list to forks',
      await repositoryNames('integ-user', ', isFork: true'),
      ['v1-fork'],
    )
    eq(
      'isFork: false leaves the forks out',
      await repositoryNames('integ-user', ', isFork: false'),
      [],
    )

    // ---- a pull request over GraphQL: every field gh pr view/list read, its
    // reviews and review requests, the issue its body closes, and the checks
    // rolled up on its head commit, a page at a time
    const cliSeed = await fetch(`${at}/reset`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tenants: [TENANT], fixture: 'cli' }),
    })
    check('the cli fixture is seeded', cliSeed.status === 200)
    const repoCli = `${at}/repos/integ/repo-cli`
    const tracked = await post(`${repoCli}/issues`, { title: 'tracked' })
    eq('an issue for the pull request to close', field(tracked.body, 'number'), 1)
    const docsPull = await post(`${repoCli}/pulls`, {
      title: 'docs',
      head: 'docs',
      base: 'main',
      body: 'Fixes #1',
    })
    eq('the pull request is opened', field(docsPull.body, 'number'), 2)
    const approve = await post(`${repoCli}/pulls/2/reviews`, { event: 'APPROVE' })
    eq(
      'an author may not approve their own pull request',
      [approve.status, field(approve.body, 'errors')],
      [422, ['Can not approve your own pull request']],
    )
    const bareReview = await post(`${repoCli}/pulls/2/reviews`, { event: 'COMMENT' })
    eq('a comment review needs a body', bareReview.status, 422)
    const review = await post(`${repoCli}/pulls/2/reviews`, { event: 'COMMENT', body: 'lgtm' })
    eq(
      'a comment review is recorded as COMMENTED',
      [review.status, field(review.body, 'state'), field(review.body, 'body')],
      [200, 'COMMENTED', 'lgtm'],
    )
    const own = await post(`${repoCli}/pulls/2/requested_reviewers`, { reviewers: ['integ-user'] })
    eq(
      'a review cannot be requested of the author',
      [own.status, field(own.body, 'message')],
      [422, 'Review cannot be requested from pull request author.'],
    )
    const asked = await post(`${repoCli}/pulls/2/requested_reviewers`, {
      reviewers: ['octo-reviewer'],
    })
    eq('a review is requested of someone else', asked.status, 201)
    const pullGraph = async (selection: string): Promise<JsonValue> => {
      const r = await post(`${at}/graphql`, {
        query: `{ repository(owner: "integ", name: "repo-cli") { ${selection} } }`,
      })
      return r.body
    }
    const pr = await pullGraph(
      'pullRequest(number: 2) { state closed number files(first: 100) { nodes { path additions ' +
        'deletions } } reviews(first: 100) { nodes { state body author { login } } } ' +
        'latestReviews(first: 100) { nodes { state } } reviewRequests(first: 100) { nodes { ' +
        'requestedReviewer { __typename ... on User { login } } } } closingIssuesReferences(' +
        'first: 100) { nodes { number } } author { login ... on User { name } } ' +
        'headRepositoryOwner { login ... on User { name } } mergedBy { login } }',
    )
    eq('a pull request answers every field it is asked for', field(pr, 'data'), {
      repository: {
        pullRequest: {
          state: 'OPEN',
          closed: false,
          number: 2,
          files: { nodes: [{ path: 'README.md', additions: 1, deletions: 0 }] },
          reviews: {
            nodes: [{ state: 'COMMENTED', body: 'lgtm', author: { login: 'integ-user' } }],
          },
          latestReviews: { nodes: [] },
          reviewRequests: {
            nodes: [{ requestedReviewer: { __typename: 'User', login: 'octo-reviewer' } }],
          },
          closingIssuesReferences: { nodes: [{ number: 1 }] },
          author: { login: 'integ-user', name: 'integ-user' },
          headRepositoryOwner: { login: 'integ' },
          mergedBy: null,
        },
      },
    })
    const issueAsPull = await pullGraph('pullRequest(number: 1) { number }')
    eq(
      'an issue number is no pull request',
      (field(issueAsPull, 'errors') as JsonValue[]).map((e) => [
        field(e, 'message'),
        field(e, 'path'),
      ]),
      [['Could not resolve to a PullRequest with the number of 1.', ['repository', 'pullRequest']]],
    )
    const pullLists = await pullGraph(
      'open: pullRequests(states: [OPEN], first: 10) { totalCount nodes { number } } ' +
        'merged: pullRequests(states: MERGED, first: 10) { totalCount }',
    )
    eq('pullRequests narrows by state', field(pullLists, 'data'), {
      repository: { open: { totalCount: 1, nodes: [{ number: 2 }] }, merged: { totalCount: 0 } },
    })
    const owned = await post(`${at}/graphql`, {
      query:
        '{ repositoryOwner(login: "integ") { repositories(first: 100) { nodes { name ' +
        'pullRequests(states: [OPEN], first: 10) { nodes { number repository { name } } } ' +
        'issues(first: 1) { pageInfo { hasNextPage } } } } } }',
    })
    const cli = (
      field(
        field(field(field(owned.body, 'data'), 'repositoryOwner'), 'repositories'),
        'nodes',
      ) as JsonValue[]
    ).find((repo) => field(repo, 'name') === 'repo-cli')
    eq(
      'a repository reached through its owner answers its connections as a top-level one does',
      [field(owned.body, 'errors'), field(cli ?? null, 'pullRequests')],
      [null, { nodes: [{ number: 2, repository: { name: 'repo-cli' } }] }],
    )
    const cards = await pullGraph(
      'pullRequest(number: 2) { projectCards(first: 100) { totalCount } }',
    )
    eq(
      'project cards are refused as the vendor refuses Projects (classic)',
      (field(cards, 'errors') as JsonValue[]).map((e) => field(e, 'path')),
      [['repository', 'pullRequest', 'projectCards']],
    )
    const contexts = async (after: string): Promise<JsonValue> =>
      field(
        field(
          (
            field(
              field(
                field(
                  field(
                    await pullGraph(
                      'pullRequest(number: 2) { commits(last: 1) { nodes { commit { ' +
                        `statusCheckRollup { contexts(first: 2${after}) { nodes { __typename } ` +
                        'pageInfo { hasNextPage endCursor } } } } } } }',
                    ),
                    'data',
                  ),
                  'repository',
                ),
                'pullRequest',
              ),
              'commits',
            ) as { nodes: JsonValue[] }
          ).nodes[0] ?? null,
          'commit',
        ),
        'statusCheckRollup',
      )
    const firstChecks = field(await contexts(''), 'contexts')
    eq(
      'the head commit rolls up the check runs first',
      (field(firstChecks, 'nodes') as JsonValue[]).map((node) => field(node, '__typename')),
      ['CheckRun', 'CheckRun'],
    )
    const cursor = field(field(firstChecks, 'pageInfo'), 'endCursor') as string
    const lastChecks = field(await contexts(`, after: "${cursor}"`), 'contexts')
    eq(
      'the next page of the rollup is the commit status',
      [
        (field(lastChecks, 'nodes') as JsonValue[]).map((node) => field(node, '__typename')),
        field(field(lastChecks, 'pageInfo'), 'hasNextPage'),
      ],
      [['StatusContext'], false],
    )
    const tracked1 = await pullGraph(
      'issue(number: 1) { state stateReason closed closedAt closedByPullRequestsReferences(' +
        'first: 100) { nodes { number } } }',
    )
    eq('an issue names the pull request that closes it', field(tracked1, 'data'), {
      repository: {
        issue: {
          state: 'OPEN',
          stateReason: null,
          closed: false,
          closedAt: null,
          closedByPullRequestsReferences: { nodes: [{ number: 2 }] },
        },
      },
    })
    const reason = async (state: string): Promise<JsonValue> => {
      const r = await fetch(`${repoCli}/issues/1`, {
        method: 'PATCH',
        headers: HEADERS,
        body: JSON.stringify({ state }),
      })
      check(`the issue is set ${state}`, r.status === 200, String(r.status))
      const graph = await pullGraph('issue(number: 1) { state stateReason closedAt }')
      return field(field(field(graph, 'data'), 'repository'), 'issue')
    }
    eq('closing records why and when', await reason('closed'), {
      state: 'CLOSED',
      stateReason: 'COMPLETED',
      closedAt: '2026-01-01T00:02:00Z',
    })
    eq('reopening records that it was reopened', await reason('open'), {
      state: 'OPEN',
      stateReason: 'REOPENED',
      closedAt: null,
    })
    const either = await pullGraph(
      'a: issueOrPullRequest(number: 1) { __typename } ' +
        'b: issueOrPullRequest(number: 2) { __typename ... on PullRequest { headRefName } }',
    )
    eq('issueOrPullRequest answers an issue or a pull request', field(either, 'data'), {
      repository: {
        a: { __typename: 'Issue' },
        b: { __typename: 'PullRequest', headRefName: 'docs' },
      },
    })
    const neither = await pullGraph('issueOrPullRequest(number: 99) { __typename }')
    eq(
      'a number that is neither is refused',
      (field(neither, 'errors') as JsonValue[]).map((e) => field(e, 'message')),
      ['Could not resolve to an issue or pull request with the number of 99.'],
    )
    const narrowed = await pullGraph(
      'all: issues(states: [OPEN, CLOSED], first: 10) { totalCount nodes { number } } ' +
        'labelled: issues(first: 10, filterBy: { labels: ["nope"] }) { totalCount }',
    )
    eq('issues narrows by labels', field(narrowed, 'data'), {
      repository: { all: { totalCount: 1, nodes: [{ number: 1 }] }, labelled: { totalCount: 0 } },
    })
    process.stdout.write(`github selftest: ${String(checks)} checks passed\n`)
  } finally {
    fake.child.kill('SIGTERM')
  }
}

await main()
await metadataRepository()
