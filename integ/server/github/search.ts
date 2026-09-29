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

import type { Ctx, JsonValue, KitRoute, Reply } from '../kit/typescript/index.ts'
import { API_PREFIXES } from './config.ts'
import type { C } from './config.ts'
import { combinedStatus } from './actions.ts'
import { issueJson } from './issues.ts'
import { pullJson } from './pulls.ts'
import { blobSha, commitJson } from './wire.ts'
import {
  allRepos,
  metaOf,
  scope,
  commitList,
  repoByName,
  searchTree,
  treeOfBranch,
} from './store.ts'
import type { RepoRow } from './store.ts'
import { authedRoute, everywhere, fail, route, paged, type Handler } from './http.ts'
import { repoJson } from './repos.ts'

const TOKEN_RE = /[A-Za-z0-9_]+/g

// Content and metadata filters of the code-search grammar. The fake does not
// evaluate them, so they are dropped, which only ever widens; matched as words instead, they would demand the literal tokens
// `language` and `python` and answer almost nothing.
const WIDENING_QUALIFIERS = new Set(['language', 'extension', 'filename', 'in', 'size', 'fork'])

function starsOf(repo: RepoRow): number {
  const value = metaOf(repo).stargazers_count
  return typeof value === 'number' ? value : 0
}

function descriptionOf(repo: RepoRow): string {
  const value = metaOf(repo).description
  return typeof value === 'string' ? value : ''
}

interface RepoQuery {
  owners: string[]
  terms: string[]
}

// `user:` and `org:` are honoured, because they NARROW: GitHub answers
// `user:integ-user` with that account's repositories and nobody else's, and a
// caller handed every account's instead reads the surplus as fact. The rest of
// the grammar (`in:name`, `language:`, `fork:`) is still dropped, which only
// ever widens. What is left over is matched against the name and the
// description, because a repository is found by what it says it does at least
// as often as by what it is called. Terms OR together rather than AND, which is
// looser than GitHub and errs towards showing a caller the row it is looking
// for; a hyphenated term also matches its parts.
function repoQuery(query: string): RepoQuery {
  const owners: string[] = []
  const terms: string[] = []
  for (const word of query.split(/\s+/).filter((w) => w !== '')) {
    const at = word.indexOf(':')
    if (at >= 0) {
      const owner = word.slice(at + 1)
      // Several of them OR together, the way GitHub reads them.
      if ((word.slice(0, at) === 'user' || word.slice(0, at) === 'org') && owner !== '') {
        owners.push(owner)
      }
      continue
    }
    terms.push(word)
    for (const part of word.split(/[-_]/)) if (part.length > 2) terms.push(part)
  }
  return { owners, terms }
}

// Substring rather than GitHub's own qualifier grammar, which nothing here
// parses. It is here at all because the alternative is a 404, and a caller
// reads that as "no such repository": an agent looking for the fork it just
// made would conclude it had not made one.
async function searchRepos(ctx: Ctx<C>): Promise<Reply> {
  // Lowercased before it is split, so a login compares case-insensitively the
  // way GitHub's own do.
  const query = (ctx.query.get('q') ?? '').toLowerCase()
  const { owners, terms } = repoQuery(query)
  const repos = await allRepos(ctx.db, ctx.tenant)
  const matched = repos.filter((repo) => {
    if (owners.length > 0 && !owners.includes(repo.owner.toLowerCase())) return false
    const haystack = `${repo.fullName} ${descriptionOf(repo)}`.toLowerCase()
    return terms.length === 0 || terms.some((t) => haystack.includes(t))
  })
  // GitHub's default is relevance, which is not modelled; `sort=stars` is,
  // because a task that asks for "the most starred" is asking for exactly
  // this ordering.
  if (ctx.query.get('sort') === 'stars') {
    const sign = (ctx.query.get('order') ?? 'desc') === 'asc' ? 1 : -1
    matched.sort((a, b) => sign * (starsOf(a) - starsOf(b)))
  } else {
    matched.sort((a, b) => (a.fullName < b.fullName ? -1 : a.fullName > b.fullName ? 1 : 0))
  }
  const items = matched.map(repoJson)
  return searchReply(ctx, items)
}

interface CodeQuery {
  repos: string[]
  owners: string[]
  terms: string[]
  pathFilter: string | null
}

// The scope qualifiers narrow, so they are honoured: several `repo:` OR
// together, `user:` and `org:` OR together, and the two groups AND, the way
// the live API reads them. A name is matched exactly and case-sensitively, as
// the live API does (`REPO:x` is a term there too), so `std::vector` and
// `-repo:x` fall through to the tokenizer. An empty value is dropped, as in
// `repoQuery`. `repo:` and `path:` values are kept as written, because both
// are compared exactly; owners and terms are lowercased.
function codeQuery(query: string): CodeQuery {
  const repos: string[] = []
  const owners: string[] = []
  const terms: string[] = []
  let pathFilter: string | null = null
  for (const word of query.split(/\s+/).filter((w) => w !== '')) {
    const at = word.indexOf(':')
    const name = at >= 0 ? word.slice(0, at) : ''
    const value = word.slice(at + 1)
    if (name === 'repo') {
      if (value !== '' && !repos.includes(value)) repos.push(value)
    } else if (name === 'user' || name === 'org') {
      if (value !== '') owners.push(value.toLowerCase())
    } else if (name === 'path') {
      pathFilter = value
    } else if (!WIDENING_QUALIFIERS.has(name)) {
      terms.push(...(word.toLowerCase().match(TOKEN_RE) ?? []))
    }
  }
  return { repos, owners, terms, pathFilter }
}

// Code search reads only the default branch, which is where the fake builds
// its term index. A query that names no scope is answered over every
// repository the tenant holds, because an authenticated caller of the live
// API is answered over all of GitHub rather than refused; here that is
// usually `total_count: 0`. A `repo:` group disjoint from the owner group
// answers empty where live refuses it with a query-parse 422. Live refuses an
// empty qualifier value the same way; here it is dropped, which widens. A
// query naming only missing repositories answers 200 with nothing. An empty
// `q` is refused as live refuses
// it, without the `errors` array, which no caller reads.
async function searchCode(ctx: Ctx<C>): Promise<Reply> {
  const query = (ctx.query.get('q') ?? '').trim()
  if (query === '') return fail(422, 'Validation Failed')
  const { repos, owners, terms, pathFilter } = codeQuery(query)
  let scope: RepoRow[]
  if (repos.length > 0) {
    const named = await Promise.all(repos.map((name) => repoByName(ctx.db, ctx.tenant, name)))
    scope = named.filter((repo): repo is RepoRow => repo !== null)
  } else {
    scope = await allRepos(ctx.db, ctx.tenant)
  }
  if (owners.length > 0) scope = scope.filter((repo) => owners.includes(repo.owner.toLowerCase()))
  // Full-name order rather than relevance, which is not modelled, so the
  // answer is the same on every run.
  scope.sort((a, b) => (a.fullName < b.fullName ? -1 : a.fullName > b.fullName ? 1 : 0))
  const items: JsonValue[] = []
  for (const repo of scope) {
    const files = await treeOfBranch(ctx.db, ctx.tenant, repo, repo.defaultBranch)
    for (const path of searchTree(files, terms, pathFilter)) {
      const data = files.get(path)
      if (data === undefined) continue
      const text = data.toString(),
        folded = text.replace(/[A-Z]/g, (c) => c.toLowerCase())
      items.push({
        name: path.slice(path.lastIndexOf('/') + 1),
        path,
        sha: blobSha(data),
        score: 1.0,
        repository: repoJson(repo),
        html_url: `https://github.com/${repo.fullName}/blob/${repo.defaultBranch}/${path}`,
        text_matches: [
          {
            object_type: 'FileContent',
            property: 'content',
            fragment: text,
            matches: terms.flatMap((term) => {
              const found: JsonValue[] = []
              for (
                let at = folded.indexOf(term);
                at >= 0;
                at = folded.indexOf(term, at + term.length)
              )
                found.push({
                  text: text.slice(at, at + term.length),
                  indices: [
                    Buffer.byteLength(text.slice(0, at)),
                    Buffer.byteLength(text.slice(0, at + term.length)),
                  ],
                })
              return found
            }),
          },
        ],
      })
    }
  }
  return searchReply(ctx, items)
}

function validatedSearch(handler: Handler): Handler {
  return async (ctx) => {
    const { qualifiers } = tokens(ctx.query.get('q') ?? '')
    const names = qualifiers.get('repo') ?? []
    const repos = await Promise.all(names.map((name) => repoByName(ctx.db, ctx.tenant, name)))
    if (names.length > 0 && repos.every((repo) => repo === null)) {
      return {
        status: 422,
        body: {
          message: 'Validation Failed',
          errors: [
            {
              message:
                'The listed users and repositories cannot be searched either because the resources do not exist or you do not have permission to view them.',
              resource: 'Search',
              field: 'q',
              code: 'invalid',
            },
          ],
          documentation_url: 'https://docs.github.com/v3/search/',
          status: '422',
        },
      }
    }
    return handler(ctx)
  }
}

export function searchRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => [
    route('GET', `${p}/meta`, async () => ({ status: 200, body: { installed_version: '3.16.0' } })),
    route<C>('GET', `${p}/search/issues`, authedRoute(validatedSearch(searchIssues))),
    route<C>('GET', `${p}/search/commits`, authedRoute(validatedSearch(searchCommits))),
    route<C>('GET', `${p}/search/code`, authedRoute(searchCode)),
    route<C>('GET', `${p}/search/repositories`, authedRoute(searchRepos)),
  ])
}

function record(value: JsonValue): Record<string, JsonValue> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value : {}
}

function searchReply(ctx: Ctx<C>, items: JsonValue[]): Reply {
  const page = paged(ctx, items)
  if (page === null) return fail(422, 'Validation Failed')
  return {
    status: 200,
    body: { total_count: items.length, incomplete_results: false, items: page.items },
    headers: page.headers,
  }
}

function tokens(query: string): { words: string[]; qualifiers: Map<string, string[]> } {
  const words: string[] = [],
    qualifiers = new Map<string, string[]>()
  for (const token of query.match(/(?:[^\s"]|"(?:\\.|[^"\\])*")+/g) ?? []) {
    const at = token.indexOf(':')
    const raw = at < 0 ? token : token.slice(at + 1)
    const value = raw.startsWith('"') ? String(JSON.parse(raw)) : raw
    if (at < 0) words.push(value.toLowerCase())
    else {
      const key = token.slice(0, at)
      qualifiers.set(key, [...(qualifiers.get(key) ?? []), value])
    }
  }
  return { words, qualifiers }
}

function dateMatches(value: string, query: string): boolean {
  const range = query.split('..')
  if (range.length === 2)
    return dateMatches(value, `>=${range[0]}`) && dateMatches(value, `<=${range[1]}`)
  const match = /^(>=|<=|>|<)?(.*)$/.exec(query)
  const boundary = match?.[2] ?? '',
    date = value.slice(0, boundary.length)
  switch (match?.[1]) {
    case '>':
      return date > boundary
    case '<':
      return date < boundary
    case '>=':
      return date >= boundary
    case '<=':
      return date <= boundary
    default:
      return date === boundary
  }
}

function countMatches(value: number, query: string): boolean {
  const range = query.split('..')
  if (range.length === 2)
    return (
      (range[0] === '*' || value >= Number(range[0])) &&
      (range[1] === '*' || value <= Number(range[1]))
    )
  const match = /^(>=|<=|>|<)?(\d+)$/.exec(query)
  const bound = Number(match?.[2])
  switch (match?.[1]) {
    case '>':
      return value > bound
    case '<':
      return value < bound
    case '>=':
      return value >= bound
    case '<=':
      return value <= bound
    default:
      return value === bound
  }
}

// Every qualifier the fake holds rows for narrows the way GitHub's does, the
// rolled-up commit status included; nothing here is ever locked, so
// `is:locked` answers nothing. Milestones, projects, reactions, mentions and
// reviews have no rows behind them, so those qualifiers are dropped, which
// only ever widens.
async function searchIssues(ctx: Ctx<C>): Promise<Reply> {
  const { words, qualifiers: q } = tokens(ctx.query.get('q') ?? '')
  const items: Record<string, JsonValue>[] = []
  for (const repo of await allRepos(ctx.db, ctx.tenant)) {
    if (q.has('repo') && !q.get('repo')?.includes(repo.fullName)) continue
    if (q.has('user') && !q.get('user')?.includes(repo.owner)) continue
    const issues = await ctx.db.githubIssue.findMany({
      where: { ...scope(ctx.tenant), repo: repo.fullName },
      orderBy: { seq: 'desc' },
    })
    const pulls = await ctx.db.githubPull.findMany({
      where: { ...scope(ctx.tenant), repo: repo.fullName },
      orderBy: { seq: 'desc' },
    })
    const comments = await ctx.db.githubComment.findMany({
      where: { ...scope(ctx.tenant), repo: repo.fullName },
    })
    const status = q.has('status') ? (await combinedStatus(ctx, repo)).state : ''
    const candidates: Record<string, JsonValue>[] = [
      ...issues.map((row) => record(issueJson(repo, row))),
      ...pulls.map((row) => {
        const item = record(pullJson(repo, row))
        return {
          ...item,
          pull_request: { html_url: item.html_url ?? '', merged_at: item.merged_at ?? null },
        }
      }),
    ]
    for (const item of candidates) {
      const pull = item.pull_request !== undefined
      const thread = comments.filter((row) => row.issueNumber === item.number)
      if (q.get('type')?.includes(pull ? 'issue' : 'pr')) continue
      if (q.has('state') && !q.get('state')?.includes(String(item.state))) continue
      if (q.has('author') && !q.get('author')?.includes(String(record(item.user ?? null).login)))
        continue
      if (
        q.has('label') &&
        !q
          .get('label')
          ?.every((name) =>
            (item.labels as JsonValue[]).some((label) => record(label).name === name),
          )
      )
        continue
      if (
        q.has('assignee') &&
        !((item.assignees as JsonValue[]) ?? []).some((user) =>
          q.get('assignee')?.includes(String(record(user).login)),
        )
      )
        continue
      if (
        q.has('created') &&
        !q.get('created')?.every((date) => dateMatches(String(item.created_at), date))
      )
        continue
      if (
        q.has('updated') &&
        !q.get('updated')?.every((date) => dateMatches(String(item.updated_at), date))
      )
        continue
      if (q.has('draft') && String(item.draft ?? false) !== q.get('draft')?.[0]) continue
      if (q.get('is')?.includes('merged') && !item.merged_at) continue
      if (q.get('is')?.includes('unmerged') && item.merged_at) continue
      if (q.get('is')?.includes('locked')) continue
      if (
        q.has('merged') &&
        !q
          .get('merged')
          ?.every((date) => item.merged_at && dateMatches(String(item.merged_at), date))
      )
        continue
      if (q.has('status') && (!pull || !q.get('status')?.includes(status))) continue
      if (q.has('base') && record(item.base ?? null).ref !== q.get('base')?.[0]) continue
      if (q.has('head') && record(item.head ?? null).ref !== q.get('head')?.[0]) continue
      if (q.get('no')?.includes('label') && (item.labels as JsonValue[]).length > 0) continue
      if (q.get('no')?.includes('assignee') && ((item.assignees as JsonValue[]) ?? []).length > 0)
        continue
      if (q.has('comments') && !q.get('comments')?.every((n) => countMatches(thread.length, n)))
        continue
      if (
        q.has('commenter') &&
        !q.get('commenter')?.every((login) => thread.some((row) => row.user === login))
      )
        continue
      const haystack = `${String(item.title)} ${String(item.body)}`.toLowerCase()
      if (!words.every((word) => haystack.includes(word))) continue
      items.push({
        ...item,
        repository_url: `https://api.github.com/repos/${repo.fullName}`,
        node_id: `${pull ? 'PR' : 'I'}_${repo.fullName}_${String(item.number)}`,
        comments: thread.length,
        locked: false,
      })
    }
  }
  const sort = ctx.query.get('sort'),
    sign = ctx.query.get('order') === 'asc' ? 1 : -1
  if (sort === 'comments') items.sort((a, b) => sign * (Number(a.comments) - Number(b.comments)))
  else if (sort === 'created' || sort === 'updated')
    items.sort((a, b) => sign * String(a[`${sort}_at`]).localeCompare(String(b[`${sort}_at`])))
  return searchReply(ctx, items)
}

// Commit search reads only the default branch, as GitHub's does.
async function searchCommits(ctx: Ctx<C>): Promise<Reply> {
  const { words, qualifiers: q } = tokens(ctx.query.get('q') ?? '')
  const items: Record<string, JsonValue>[] = []
  for (const repo of await allRepos(ctx.db, ctx.tenant)) {
    if (q.has('repo') && !q.get('repo')?.includes(repo.fullName)) continue
    if (q.has('user') && !q.get('user')?.includes(repo.owner)) continue
    for (const row of await commitList(ctx.db, ctx.tenant, repo, repo.defaultBranch)) {
      if (!words.every((word) => row.message.toLowerCase().includes(word))) continue
      if (q.has('author') && !q.get('author')?.includes(row.authorLogin)) continue
      if (q.has('hash') && !row.sha.startsWith(q.get('hash')?.[0] ?? '')) continue
      const item = record(commitJson(row))
      items.push({
        ...item,
        node_id: `C_${row.sha}`,
        repository: repoJson(repo),
        html_url: `https://github.com/${repo.fullName}/commit/${row.sha}`,
        parents: row.parentSha ? [{ sha: row.parentSha }] : [],
      })
    }
  }
  return searchReply(ctx, items)
}
