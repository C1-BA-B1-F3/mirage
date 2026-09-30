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
  accountsOf,
  allRepos,
  metaOf,
  scope,
  commitList,
  repoByName,
  searchTree,
  treeOfBranch,
} from './store.ts'
import type { AccountRow, RepoRow } from './store.ts'
import {
  authedRoute,
  everywhere,
  fail,
  route,
  paged,
  validationFailed,
  type Handler,
} from './http.ts'
import { accountJson, repoDate, repoJson } from './repos.ts'

const TOKEN_RE = /[A-Za-z0-9_]+/g

// Content and metadata filters of the code-search grammar. The fake does not
// evaluate them, so they are dropped, which only ever widens; matched as words instead, they would demand the literal tokens
// `language` and `python` and answer almost nothing.
const WIDENING_QUALIFIERS = new Set(['language', 'extension', 'filename', 'in', 'size', 'fork'])

function numberOf(repo: RepoRow, key: string): number {
  const value = metaOf(repo)[key]
  return typeof value === 'number' ? value : 0
}

function textOf(repo: RepoRow, key: string): string {
  const value = metaOf(repo)[key]
  return typeof value === 'string' ? value : ''
}

function topicsOf(repo: RepoRow): string[] {
  const value = metaOf(repo).topics
  return Array.isArray(value) ? value.map((t) => String(t).toLowerCase()) : []
}

// What `in:` chooses among. Without it all three are searched, as GitHub
// searches a repository's name, description and topics. The name is the full
// name, so a term can find a repository by its owner too.
const REPO_FIELDS: Record<string, (repo: RepoRow) => string> = {
  name: (repo) => repo.fullName,
  description: (repo) => textOf(repo, 'description'),
  topics: (repo) => topicsOf(repo).join(' '),
}

const REPO_DATES = ['created', 'pushed', 'updated']
const REPO_COUNTS: Record<string, (repo: RepoRow) => number> = {
  stars: (repo) => numberOf(repo, 'stargazers_count'),
  forks: (repo) => numberOf(repo, 'forks_count'),
  topics: (repo) => topicsOf(repo).length,
}

// Every qualifier the fake holds data for narrows the way GitHub's does, and
// several of one qualifier all have to hold, except the names. Several
// `repo:` OR together, `user:` and `org:` OR together, and the two groups
// AND, as code search measured them. Dates are the ones `repositoryNode`
// reports; counts are stars, forks and topics. `language:` narrows only a
// repository that states one, because a language nobody stated is unknown
// rather than different. `fork:only` keeps forks; `fork:true`, which asks for
// forks as well, changes nothing, since forks are never left out here. What
// the fake holds nothing of (a license, a size, followers, issue labels) is
// dropped, which only ever widens.
function repoMatches(repo: RepoRow, q: Map<string, string[]>): boolean {
  const meta = metaOf(repo)
  const all = (key: string, test: (value: string) => boolean): boolean =>
    (q.get(key) ?? []).every(test)
  const names = q.get('repo') ?? []
  if (names.length > 0 && !names.includes(repo.fullName.toLowerCase())) return false
  const owners = [...(q.get('user') ?? []), ...(q.get('org') ?? [])].filter((o) => o !== '')
  if (owners.length > 0 && !owners.includes(repo.owner.toLowerCase())) return false
  for (const key of REPO_DATES) {
    if (!all(key, (value) => dateMatches(repoDate(repo, `${key}_at`), value))) return false
  }
  for (const [key, count] of Object.entries(REPO_COUNTS)) {
    if (!all(key, (value) => countMatches(count(repo), value))) return false
  }
  if (!all('topic', (value) => topicsOf(repo).includes(value))) return false
  if (!all('archived', (value) => String(meta.archived === true) === value)) return false
  if (!all('fork', (value) => value !== 'only' || meta.fork === true)) return false
  const visibility = meta.private === true ? 'private' : 'public'
  if (!all('is', (value) => !['public', 'private'].includes(value) || value === visibility))
    return false
  const language = textOf(repo, 'language').toLowerCase()
  const languages = q.get('language') ?? []
  return language === '' || languages.length === 0 || languages.includes(language)
}

// A repository is found by what it says it does at least as often as by what
// it is called, so the terms are matched against its description and topics
// as well as its name, or against the fields `in:` names. Terms OR together
// rather than AND, which is looser than GitHub and errs towards showing a
// caller the row it is looking for; a hyphenated term also matches its parts.
// It is here at all because the alternative is a 404, and a caller reads that
// as "no such repository": an agent looking for the fork it just made would
// conclude it had not made one.
async function searchRepos(ctx: Ctx<C>): Promise<Reply> {
  // Lowercased before it is split, so a login compares case-insensitively the
  // way GitHub's own do.
  const { words, qualifiers: q } = tokens((ctx.query.get('q') ?? '').toLowerCase())
  const terms = words.flatMap((word) => [word, ...word.split(/[-_]/).filter((p) => p.length > 2)])
  const fields = (q.get('in') ?? []).filter((field) => field in REPO_FIELDS)
  const read = (fields.length > 0 ? fields : Object.keys(REPO_FIELDS)).flatMap((field) => {
    const fn = REPO_FIELDS[field]
    return fn === undefined ? [] : [fn]
  })
  const repos = await allRepos(ctx.db, ctx.tenant)
  const matched = repos.filter((repo) => {
    if (!repoMatches(repo, q)) return false
    const haystack = read
      .map((field) => field(repo))
      .join(' ')
      .toLowerCase()
    return terms.length === 0 || terms.some((t) => haystack.includes(t))
  })
  // GitHub's default is relevance, which is not modelled; the other orders
  // are, because a task that asks for "the most starred" is asking for
  // exactly this ordering.
  const sort = ctx.query.get('sort')
  const sign = (ctx.query.get('order') ?? 'desc') === 'asc' ? 1 : -1
  if (sort === 'stars' || sort === 'forks') {
    const count = REPO_COUNTS[sort] ?? (() => 0)
    matched.sort((a, b) => sign * (count(a) - count(b)))
  } else if (sort === 'updated') {
    matched.sort(
      (a, b) => sign * repoDate(a, 'updated_at').localeCompare(repoDate(b, 'updated_at')),
    )
  } else {
    matched.sort((a, b) => (a.fullName < b.fullName ? -1 : a.fullName > b.fullName ? 1 : 0))
  }
  return searchReply(ctx, matched.map(repoJson))
}

// Accounts are searched by what the fake holds of them: `type:user` or
// `type:org`, `in:login`, `in:name` and `in:email` (all three without it),
// `fullname:`, `created:` and `repos:`, the number of repositories an account
// owns here. Location, language, followers and sponsorship have nothing behind
// them, so they are dropped, which only ever widens. Every term has to hit, as
// on GitHub. Relevance is not modelled, so an exact login leads and the rest
// follow in login order, unless `sort` asks for `joined` or `repositories`.
// An empty `q` is refused as code search's is.
async function searchUsers(ctx: Ctx<C>): Promise<Reply> {
  const query = (ctx.query.get('q') ?? '').trim()
  if (query === '') return fail(422, 'Validation Failed')
  const { words, qualifiers: q } = tokens(query)
  const repos = await allRepos(ctx.db, ctx.tenant)
  const owned = (account: AccountRow): number =>
    repos.filter((repo) => repo.owner.toLowerCase() === account.login.toLowerCase()).length
  const asked = (q.get('in') ?? []).map((field) => field.toLowerCase())
  const fields = ['login', 'name', 'email'].filter((f) => asked.length === 0 || asked.includes(f))
  const read = (account: AccountRow): string =>
    fields
      .map((f) => (f === 'login' ? account.login : f === 'name' ? account.name : account.email))
      .join(' ')
      .toLowerCase()
  const all = (key: string, test: (value: string) => boolean): boolean =>
    (q.get(key) ?? []).every(test)
  const matched = (await accountsOf(ctx.db, ctx.tenant)).filter((account) => {
    const type = account.type === 'User' ? 'user' : 'org'
    const types = (q.get('type') ?? []).map((value) => value.toLowerCase())
    if (types.length > 0 && !types.includes(type)) return false
    if (!all('fullname', (value) => account.name.toLowerCase().includes(value.toLowerCase())))
      return false
    if (!all('created', (value) => dateMatches(account.createdAt, value))) return false
    if (!all('repos', (value) => countMatches(owned(account), value))) return false
    return words.every((word) => read(account).includes(word))
  })
  const sort = ctx.query.get('sort')
  const sign = ctx.query.get('order') === 'asc' ? 1 : -1
  const exact = (account: AccountRow): number =>
    words.includes(account.login.toLowerCase()) ? 0 : 1
  matched.sort((a, b) => {
    if (sort === 'joined') return sign * a.createdAt.localeCompare(b.createdAt)
    if (sort === 'repositories') return sign * (owned(a) - owned(b))
    return exact(a) - exact(b) || a.login.toLowerCase().localeCompare(b.login.toLowerCase())
  })
  return searchReply(
    ctx,
    matched.map((account) => {
      const { login, id, node_id, html_url, type, site_admin } = record(accountJson(account, repos))
      return { login, id, node_id, html_url, type, site_admin, score: 1.0 } as JsonValue
    }),
  )
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
      return validationFailed(
        [
          {
            message:
              'The listed users and repositories cannot be searched either because the resources do not exist or you do not have permission to view them.',
            resource: 'Search',
            field: 'q',
            code: 'invalid',
          },
        ],
        'https://docs.github.com/v3/search/',
      )
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
    route<C>('GET', `${p}/search/users`, authedRoute(searchUsers)),
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
    return (
      (range[0] === '*' || dateMatches(value, `>=${range[0]}`)) &&
      (range[1] === '*' || dateMatches(value, `<=${range[1]}`))
    )
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
      ...(await Promise.all(
        pulls.map(async (row) => {
          const item = record(await pullJson(ctx, repo, row))
          return {
            ...item,
            pull_request: { html_url: item.html_url ?? '', merged_at: item.merged_at ?? null },
          }
        }),
      )),
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
