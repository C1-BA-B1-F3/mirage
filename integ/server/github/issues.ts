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
import { API_PREFIXES, DEFAULT_LOGIN } from './config.ts'
import type { C } from './config.ts'
import { nextNumber, scope } from './store.ts'
import type { RepoRow } from './store.ts'
import {
  authedRoute,
  everywhere,
  fail,
  jsonBodyOf,
  numberParam,
  pagedReply,
  route,
  str,
  withRepo,
} from './http.ts'
import { pullJson, pullRow } from './pulls.ts'

// Both timestamps are fixed rather than taken from the clock: a golden renders
// them, so a real one would make every case that files an issue unassertable.
const CREATED_AT = '2026-01-01T00:00:00Z'
const EDITED_AT = '2026-01-01T00:02:00Z'

export interface IssueRow {
  number: number
  title: string
  body: string
  state: string
  user: string
  labelsJson: string
  assigneesJson: string
  createdAt: string
  updatedAt: string
}

function names(json: string): string[] {
  const parsed = JSON.parse(json) as JsonValue
  return Array.isArray(parsed) ? parsed.map((v) => String(v)) : []
}

// The vendor takes a label or assignee list as bare names and reports it as a
// list of objects, so the column stores the names and each render wraps them.
function nameList(value: JsonValue | undefined): string {
  return JSON.stringify(Array.isArray(value) ? value.map((v) => String(v)) : [])
}

export function issueJson(repo: RepoRow, row: IssueRow): JsonValue {
  return {
    number: row.number,
    title: row.title,
    body: row.body,
    state: row.state,
    created_at: row.createdAt,
    updated_at: row.updatedAt,
    user: { login: row.user },
    assignees: names(row.assigneesJson).map((login) => ({ login })),
    labels: names(row.labelsJson).map((name) => ({ name })),
    html_url: `https://github.com/${repo.fullName}/issues/${String(row.number)}`,
  }
}

export async function issueRow(
  db: C,
  tenant: string,
  repo: RepoRow,
  number: number,
): Promise<IssueRow | null> {
  return (await db.githubIssue.findFirst({
    where: { ...scope(tenant), repo: repo.fullName, number },
  })) as IssueRow | null
}

async function listIssues(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const rows = (await ctx.db.githubIssue.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'desc' },
  })) as IssueRow[]
  const wanted = ctx.query.get('state') ?? 'open'
  const creator = ctx.query.get('creator') ?? ''
  const assignee = ctx.query.get('assignee') ?? ''
  const labels = (ctx.query.get('labels') ?? '').split(',').filter((v) => v !== '')
  let kept = rows.filter((r) => wanted === 'all' || r.state === wanted)
  if (creator !== '') kept = kept.filter((r) => r.user === creator)
  if (assignee !== '') kept = kept.filter((r) => names(r.assigneesJson).includes(assignee))
  if (labels.length > 0) {
    kept = kept.filter((r) => {
      const have = new Set(names(r.labelsJson))
      return labels.every((want) => have.has(want))
    })
  }
  return pagedReply(
    ctx,
    kept.map((r) => issueJson(repo, r)),
  )
}

async function createIssue(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const body = jsonBodyOf(ctx)
  const title = str(body, 'title').trim()
  if (title === '') return fail(422, 'Invalid request.\n\n"title" wasn\'t supplied.')
  const number = await nextNumber(ctx.db, ctx.tenant, repo)
  const row: IssueRow = {
    number,
    title,
    body: str(body, 'body'),
    state: 'open',
    user: DEFAULT_LOGIN,
    labelsJson: nameList(body.labels),
    assigneesJson: nameList(body.assignees),
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
  }
  await ctx.db.githubIssue.create({
    data: { tenant: ctx.tenant, repo: repo.fullName, ...row, seq: number },
  })
  return { status: 201, body: issueJson(repo, row) }
}

// Reading issue N when N is a pull request answers the pull as an issue, which
// is what the vendor does: every pull request is an issue, and the extra
// `pull_request` key is how a caller tells the two apart.
async function getIssue(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const number = numberParam(ctx)
  if (number === null) return fail(404, 'Not Found')
  const row = await issueRow(ctx.db, ctx.tenant, repo, number)
  if (row !== null) return { status: 200, body: issueJson(repo, row) }
  const pull = await pullRow(ctx.db, ctx.tenant, repo, number)
  if (pull === null) return fail(404, 'Not Found')
  const json = pullJson(repo, pull)
  return {
    status: 200,
    // A reference the client follows, so it carries the run the request came
    // in on. Without it, resolving a pull request from a scoped issue read
    // queries the default run and can answer from another repository state.
    body: {
      ...(json as Record<string, JsonValue>),
      pull_request: { url: `${ctx.runPrefix}${ctx.url.pathname}` },
    },
  }
}

async function editIssue(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const number = numberParam(ctx)
  if (number === null) return fail(404, 'Not Found')
  const row = await issueRow(ctx.db, ctx.tenant, repo, number)
  if (row === null) return fail(404, 'Not Found')
  const body = jsonBodyOf(ctx)
  const next: IssueRow = { ...row, updatedAt: EDITED_AT }
  if ('title' in body) next.title = str(body, 'title')
  if ('body' in body) next.body = str(body, 'body')
  if ('state' in body) next.state = str(body, 'state')
  if ('labels' in body) next.labelsJson = nameList(body.labels)
  if ('assignees' in body) next.assigneesJson = nameList(body.assignees)
  await ctx.db.githubIssue.updateMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, number },
    data: next,
  })
  return { status: 200, body: issueJson(repo, next) }
}

// A comment hangs off a number that may name either an issue or a pull, and
// the id counts every comment in the repository rather than in the thread.
async function createComment(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const number = numberParam(ctx)
  if (number === null) return fail(404, 'Not Found')
  const issue = await issueRow(ctx.db, ctx.tenant, repo, number)
  const pull = issue === null ? await pullRow(ctx.db, ctx.tenant, repo, number) : null
  if (issue === null && pull === null) return fail(404, 'Not Found')
  const where = { ...scope(ctx.tenant), repo: repo.fullName }
  const id = (await ctx.db.githubComment.count({ where })) + 1
  const body = str(jsonBodyOf(ctx), 'body')
  await ctx.db.githubComment.create({
    data: {
      tenant: ctx.tenant,
      repo: repo.fullName,
      issueNumber: number,
      id,
      body,
      user: DEFAULT_LOGIN,
      createdAt: CREATED_AT,
      seq: id,
    },
  })
  return {
    status: 201,
    body: {
      id,
      body,
      user: { login: DEFAULT_LOGIN },
      html_url: `https://github.com/${repo.fullName}/issues/${String(number)}#issuecomment-${String(id)}`,
    },
  }
}

/**
 * Every comment on one issue, oldest first.
 *
 * Oldest first is the vendor's order and it is the whole of what a caller
 * reads this for: `comments[-1]` is "what was said last", which is how a
 * grader asks whether the reply it wanted is the reply that landed. Sorting
 * the other way would leave every such check reading the opening comment.
 *
 * The shape matches what `createComment` returns, plus `created_at`, so a
 * caller that posts and then lists sees one comment described one way.
 */
async function listComments(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const number = numberParam(ctx)
  if (number === null) return fail(404, 'Not Found')
  const issue = await issueRow(ctx.db, ctx.tenant, repo, number)
  const pull = issue === null ? await pullRow(ctx.db, ctx.tenant, repo, number) : null
  if (issue === null && pull === null) return fail(404, 'Not Found')
  const rows = await ctx.db.githubComment.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, issueNumber: number },
    orderBy: { seq: 'asc' },
  })
  return pagedReply(
    ctx,
    rows.map((row) => ({
      id: row.id,
      body: row.body,
      created_at: row.createdAt,
      updated_at: row.createdAt,
      node_id: Buffer.from(`012:IssueComment${row.id}`).toString('base64'),
      author_association: 'NONE',
      user: { login: row.user },
      html_url: `https://github.com/${repo.fullName}/issues/${String(number)}#issuecomment-${String(row.id)}`,
    })),
  )
}

function commentCursor(id: number): string {
  return Buffer.from(`comment:${id}`).toString('base64')
}

/**
 * The GraphQL `issueOrPullRequest` node for one number, null when the
 * repository holds neither: its type and a page of its comments, oldest first.
 */
export async function issueOrPullRequestNode(
  ctx: Ctx<C>,
  repo: RepoRow,
  number: number,
): Promise<Record<string, unknown> | null> {
  const issue = await issueRow(ctx.db, ctx.tenant, repo, number)
  const pull = issue === null ? await pullRow(ctx.db, ctx.tenant, repo, number) : null
  if (issue === null && pull === null) return null
  return {
    __typename: issue === null ? 'PullRequest' : 'Issue',
    comments: async ({ first, after }: { first: number; after?: string }) => {
      if (first < 1 || first > 100) throw new Error('first must be between 1 and 100')
      const rows = await ctx.db.githubComment.findMany({
        where: { ...scope(ctx.tenant), repo: repo.fullName, issueNumber: number },
        orderBy: { seq: 'asc' },
      })
      const start = after ? rows.findIndex((row) => commentCursor(row.id) === after) + 1 : 0
      if (after && start === 0) throw new Error('Invalid cursor')
      const page = rows.slice(start, start + first)
      return {
        nodes: page.map((row) => ({
          id: Buffer.from(`012:IssueComment${row.id}`).toString('base64'),
          author: { login: row.user },
          authorAssociation: 'NONE',
          body: row.body,
          createdAt: row.createdAt,
          includesCreatedEdit: false,
          isMinimized: false,
          minimizedReason: null,
          reactionGroups: [],
          url: `https://github.com/${repo.fullName}/issues/${number}#issuecomment-${row.id}`,
          viewerDidAuthor: row.user === DEFAULT_LOGIN,
          ...(JSON.parse(row.metaJson) as Record<string, JsonValue>),
        })),
        pageInfo: {
          hasNextPage: start + first < rows.length,
          endCursor: page.length ? commentCursor(page[page.length - 1]!.id) : null,
        },
      }
    },
  }
}

export function issueRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => [
    route<C>('GET', `${p}/repos/:owner/:repo/issues`, authedRoute(withRepo(listIssues))),
    route<C>('POST', `${p}/repos/:owner/:repo/issues`, authedRoute(withRepo(createIssue)), {
      write: true,
    }),
    route<C>('GET', `${p}/repos/:owner/:repo/issues/:number`, authedRoute(withRepo(getIssue))),
    route<C>('PATCH', `${p}/repos/:owner/:repo/issues/:number`, authedRoute(withRepo(editIssue)), {
      write: true,
    }),
    route<C>(
      'GET',
      `${p}/repos/:owner/:repo/issues/:number/comments`,
      authedRoute(withRepo(listComments)),
    ),
    route<C>(
      'POST',
      `${p}/repos/:owner/:repo/issues/:number/comments`,
      authedRoute(withRepo(createComment)),
      { write: true },
    ),
  ])
}
