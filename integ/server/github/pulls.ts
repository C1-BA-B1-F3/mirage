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
import {
  PROJECTS_CLASSIC_GONE,
  closedNumbers,
  commitPerson,
  commitSha,
  issueNodeId,
  nodeId,
  ownerNode,
  page,
  pullNodeId,
  reactionGroups,
  userNode,
} from './wire.ts'
import type { PageArgs } from './wire.ts'
import { commitList, nextNumber, scope } from './store.ts'
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

const CREATED_AT = '2026-01-01T00:00:00Z'
const EDITED_AT = '2026-01-01T00:02:00Z'
const MERGED_AT = '2026-01-01T00:03:00Z'

// The one diff the fake serves, for a caller that asks for a pull request as
// `application/vnd.github.diff` rather than as JSON.
const SAMPLE_DIFF =
  'diff --git a/README.md b/README.md\n' +
  '--- a/README.md\n+++ b/README.md\n' +
  '@@ -1 +1,2 @@\n # repo-v1\n+change\n'

export interface PullRow {
  number: number
  title: string
  body: string
  state: string
  user: string
  head: string
  base: string
  draft: boolean
  merged: boolean
  headSha: string
  reviewersJson: string
  createdAt: string
  updatedAt: string
}

interface ReviewRow {
  id: number
  user: string
  body: string
  state: string
  commitId: string
  submittedAt: string
}

// The review states the vendor records for the event a caller posts, and the
// refusal it gives an author who reviews their own pull request with one.
const REVIEW_STATES: Record<string, string> = {
  APPROVE: 'APPROVED',
  REQUEST_CHANGES: 'CHANGES_REQUESTED',
  COMMENT: 'COMMENTED',
}
const OWN_REVIEW_REFUSALS: Record<string, string> = {
  APPROVE: 'Can not approve your own pull request',
  REQUEST_CHANGES: 'Can not request changes on your own pull request',
}
const REVIEWED_AT = '2026-01-01T00:04:00Z'

// The counts are fixed rather than derived from the branch: nothing in the
// fake diffs two trees, and a caller that renders them wants a stable number.
export function pullJson(repo: RepoRow, row: PullRow): JsonValue {
  return {
    number: row.number,
    title: row.title,
    body: row.body,
    state: row.state,
    draft: row.draft,
    user: { login: row.user },
    labels: [],
    base: { ref: row.base },
    head: { ref: row.head, sha: row.headSha },
    mergeable: true,
    additions: 1,
    deletions: 0,
    changed_files: 1,
    merged_at: row.merged ? MERGED_AT : null,
    created_at: row.createdAt,
    updated_at: row.updatedAt,
    html_url: `https://github.com/${repo.fullName}/pull/${String(row.number)}`,
  }
}

export async function pullRow(
  db: C,
  tenant: string,
  repo: RepoRow,
  number: number,
): Promise<PullRow | null> {
  return (await db.githubPull.findFirst({
    where: { ...scope(tenant), repo: repo.fullName, number },
  })) as PullRow | null
}

async function found(ctx: Ctx<C>, repo: RepoRow): Promise<PullRow | null> {
  const number = numberParam(ctx)
  return number === null ? null : await pullRow(ctx.db, ctx.tenant, repo, number)
}

async function listPulls(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const rows = (await ctx.db.githubPull.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'desc' },
  })) as PullRow[]
  const wanted = ctx.query.get('state') ?? 'open'
  let kept = rows.filter((r) => wanted === 'all' || r.state === wanted)
  const base = ctx.query.get('base') ?? ''
  const head = ctx.query.get('head') ?? ''
  if (base !== '') kept = kept.filter((r) => r.base === base)
  if (head !== '') kept = kept.filter((r) => r.head === head)
  return pagedReply(
    ctx,
    kept.map((r) => pullJson(repo, r)),
  )
}

async function createPull(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const body = jsonBodyOf(ctx)
  const title = str(body, 'title')
  const head = str(body, 'head')
  const base = str(body, 'base')
  if (title === '' || head === '' || base === '') return fail(422, 'Validation Failed')
  const number = await nextNumber(ctx.db, ctx.tenant, repo)
  const row: PullRow = {
    number,
    title,
    body: str(body, 'body'),
    state: 'open',
    user: DEFAULT_LOGIN,
    head,
    base,
    draft: body.draft === true,
    merged: false,
    headSha: commitSha(head),
    reviewersJson: '[]',
    createdAt: CREATED_AT,
    updatedAt: CREATED_AT,
  }
  await ctx.db.githubPull.create({
    data: { tenant: ctx.tenant, repo: repo.fullName, ...row, seq: number },
  })
  return { status: 201, body: pullJson(repo, row) }
}

async function getPull(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  if ((ctx.headers.accept ?? '').includes('diff')) {
    return {
      status: 200,
      body: Buffer.from(SAMPLE_DIFF),
      headers: { 'Content-Type': 'text/plain' },
    }
  }
  return { status: 200, body: pullJson(repo, row) }
}

async function editPull(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  const body = jsonBodyOf(ctx)
  const next: PullRow = { ...row, updatedAt: EDITED_AT }
  if ('title' in body) next.title = str(body, 'title')
  if ('body' in body) next.body = str(body, 'body')
  if ('state' in body) next.state = str(body, 'state')
  if ('base' in body) next.base = str(body, 'base')
  await ctx.db.githubPull.updateMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, number: row.number },
    data: next,
  })
  return { status: 200, body: pullJson(repo, next) }
}

// A merge takes an optional expected head sha, and refuses when it does not
// match: that is how the vendor reports a branch that moved under the caller.
async function mergePull(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  const expected = str(jsonBodyOf(ctx), 'sha')
  if (expected !== '' && expected !== row.headSha) return fail(409, 'Head branch was modified')
  await ctx.db.githubPull.updateMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, number: row.number },
    data: { state: 'closed', merged: true },
  })
  return {
    status: 200,
    body: {
      sha: commitSha('merge'),
      merged: true,
      message: 'Pull Request successfully merged',
    },
  }
}

function reviewJson(repo: RepoRow, number: number, row: ReviewRow): JsonValue {
  return {
    id: row.id,
    node_id: nodeId('017:PullRequestReview', row.id),
    user: { login: row.user },
    body: row.body,
    state: row.state,
    html_url: `https://github.com/${repo.fullName}/pull/${String(number)}#pullrequestreview-${String(row.id)}`,
    commit_id: row.commitId,
    submitted_at: row.submittedAt,
    author_association: 'NONE',
  }
}

async function reviewRows(
  ctx: { db: C; tenant: string },
  repo: RepoRow,
  number: number,
): Promise<ReviewRow[]> {
  return (await ctx.db.githubReview.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, pullNumber: number },
    orderBy: { seq: 'asc' },
  })) as ReviewRow[]
}

async function listReviews(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  const rows = await reviewRows(ctx, repo, row.number)
  return pagedReply(
    ctx,
    rows.map((review) => reviewJson(repo, row.number, review)),
  )
}

// A review names an event and, for any but an approval, a body. The author
// of a pull request may comment on it but neither approve it nor ask for
// changes, which is the vendor's rule for the one account the fake has.
async function createReview(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  const body = jsonBodyOf(ctx)
  const event = str(body, 'event')
  const state = REVIEW_STATES[event]
  const text = str(body, 'body')
  if (state === undefined || (event !== 'APPROVE' && text === '')) {
    return fail(422, 'Unprocessable Entity')
  }
  const refusal = row.user === DEFAULT_LOGIN ? OWN_REVIEW_REFUSALS[event] : undefined
  if (refusal !== undefined) {
    return {
      status: 422,
      body: {
        message: 'Unprocessable Entity',
        errors: [refusal],
        documentation_url: 'https://docs.github.com/rest',
      },
    }
  }
  const seq = (await reviewRows(ctx, repo, row.number)).length + 1
  const review: ReviewRow = {
    id: 8000 + row.number * 100 + seq,
    user: DEFAULT_LOGIN,
    body: text,
    state,
    commitId: str(body, 'commit_id') || row.headSha,
    submittedAt: REVIEWED_AT,
  }
  await ctx.db.githubReview.create({
    data: { tenant: ctx.tenant, repo: repo.fullName, pullNumber: row.number, ...review, seq },
  })
  return { status: 200, body: reviewJson(repo, row.number, review) }
}

// The vendor refuses a review request of the pull request's own author, and
// records every other login once, in the order asked.
async function requestReviewers(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await found(ctx, repo)
  if (row === null) return fail(404, 'Not Found')
  const asked = jsonBodyOf(ctx).reviewers
  const logins = Array.isArray(asked) ? asked.filter((l): l is string => typeof l === 'string') : []
  if (logins.includes(row.user)) {
    return fail(422, 'Review cannot be requested from pull request author.')
  }
  const reviewers = [...new Set([...(JSON.parse(row.reviewersJson) as string[]), ...logins])]
  const next: PullRow = { ...row, reviewersJson: JSON.stringify(reviewers) }
  await ctx.db.githubPull.updateMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, number: row.number },
    data: { reviewersJson: next.reviewersJson },
  })
  return { status: 201, body: pullJson(repo, next) }
}

function reviewNode(repo: RepoRow, number: number, row: ReviewRow): Record<string, unknown> {
  return {
    id: nodeId('017:PullRequestReview', row.id),
    author: userNode(row.user),
    authorAssociation: 'NONE',
    body: row.body,
    state: row.state,
    submittedAt: row.submittedAt,
    commit: { oid: row.commitId },
    reactionGroups: reactionGroups(),
    url: `https://github.com/${repo.fullName}/pull/${String(number)}#pullrequestreview-${String(row.id)}`,
  }
}

/**
 * The one commit behind a pull request's head, as GraphQL reports it: the
 * change README.md carries, by the pull request's author, and the repository's
 * checks and statuses rolled up against it. Nothing in the fake diffs two
 * trees, which is why the counts, the file and the commit are fixed.
 */
function headCommit(
  ctx: { db: C; tenant: string },
  repo: RepoRow,
  row: PullRow,
): Record<string, unknown> {
  const where = { ...scope(ctx.tenant), repo: repo.fullName }
  const person = commitPerson(row.user, row.createdAt) as { name: string; email: string }
  return {
    oid: row.headSha,
    messageHeadline: 'Update README.md',
    messageBody: '',
    committedDate: row.createdAt,
    authoredDate: row.createdAt,
    authors: {
      nodes: [{ name: person.name, email: person.email, user: userNode(row.user) }],
    },
    statusCheckRollup: {
      contexts: async ({ first, after }: PageArgs) => {
        const checks = await ctx.db.githubCheck.findMany({ where, orderBy: { seq: 'asc' } })
        const statuses = await ctx.db.githubStatus.findMany({ where, orderBy: { seq: 'asc' } })
        const contexts = [
          ...checks.map((check) => ({
            __typename: 'CheckRun',
            name: check.name,
            status: check.status.toUpperCase(),
            conclusion: check.conclusion === '' ? null : check.conclusion.toUpperCase(),
            startedAt: check.startedAt,
            completedAt: check.completedAt,
            detailsUrl: check.detailsUrl,
            checkSuite: { workflowRun: { event: 'pull_request', workflow: { name: 'CI' } } },
          })),
          ...statuses.map((status) => ({
            __typename: 'StatusContext',
            context: status.context,
            state: status.state.toUpperCase(),
            targetUrl: status.targetUrl,
            createdAt: status.createdAt,
            description: status.description,
          })),
        ]
        return page(contexts, first, after)
      },
    },
  }
}

/**
 * One pull request as GraphQL's `PullRequest` reports it, for every field
 * `gh pr view --json` and `gh pr list --json` read. The comments come from
 * the caller, since issues own them; `repository` is the GraphQL node of the
 * repository the pull request lives in, which is also its head's, as the fake
 * opens every pull request between two of one repository's branches.
 */
export async function pullRequestNode(
  ctx: { db: C; tenant: string },
  repo: RepoRow,
  row: PullRow,
  repository: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const state = row.merged ? 'MERGED' : row.state === 'closed' ? 'CLOSED' : 'OPEN'
  const open = state === 'OPEN'
  const base = await commitList(ctx.db, ctx.tenant, repo, row.base)
  const reviews = await reviewRows(ctx, repo, row.number)
  const latest = new Map<string, ReviewRow>()
  for (const review of reviews) if (review.user !== row.user) latest.set(review.user, review)
  const referenced = closedNumbers(row.body)
  const closing = (
    await ctx.db.githubIssue.findMany({
      where: { ...scope(ctx.tenant), repo: repo.fullName, number: { in: referenced } },
      orderBy: { seq: 'asc' },
    })
  ).map((issue) => ({
    id: issueNodeId(repo.seq, issue.number),
    number: issue.number,
    url: `https://github.com/${repo.fullName}/issues/${String(issue.number)}`,
    repository,
  }))
  const commit = headCommit(ctx, repo, row)
  return {
    id: pullNodeId(repo.seq, row.number),
    fullDatabaseId: String(3_000_000 + repo.seq * 1000 + row.number),
    number: row.number,
    title: row.title,
    body: row.body,
    state,
    closed: !open,
    url: `https://github.com/${repo.fullName}/pull/${String(row.number)}`,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
    closedAt: open ? null : row.merged ? MERGED_AT : row.updatedAt,
    mergedAt: row.merged ? MERGED_AT : null,
    baseRefName: row.base,
    baseRefOid: base[0]?.sha ?? '',
    headRefName: row.head,
    headRefOid: row.headSha,
    isDraft: row.draft,
    isCrossRepository: false,
    maintainerCanModify: false,
    mergeable: open ? 'MERGEABLE' : 'UNKNOWN',
    mergeStateStatus: !open ? 'UNKNOWN' : row.draft ? 'DRAFT' : 'CLEAN',
    reviewDecision: null,
    additions: 1,
    deletions: 0,
    changedFiles: 1,
    author: userNode(row.user),
    mergedBy: row.merged ? userNode(DEFAULT_LOGIN) : null,
    repository,
    headRepository: repository,
    headRepositoryOwner: {
      __typename: repo.owner === DEFAULT_LOGIN ? 'User' : 'Organization',
      ...ownerNode(repo.owner),
      name: repo.owner === DEFAULT_LOGIN ? repo.owner : null,
    },
    autoMergeRequest: null,
    mergeCommit: row.merged ? { oid: commitSha('merge') } : null,
    potentialMergeCommit: open ? { oid: commitSha(`merge:${String(row.number)}`) } : null,
    milestone: null,
    assignees: ({ first, after }: PageArgs) => page([], first, after),
    labels: ({ first, after }: PageArgs) => page([], first, after),
    reactionGroups: reactionGroups(),
    reviews: ({ first, after }: PageArgs) =>
      page(
        reviews.map((review) => reviewNode(repo, row.number, review)),
        first,
        after,
      ),
    latestReviews: ({ first, after }: PageArgs) =>
      page(
        [...latest.values()].map((review) => reviewNode(repo, row.number, review)),
        first,
        after,
      ),
    reviewRequests: ({ first, after }: PageArgs) =>
      page(
        (JSON.parse(row.reviewersJson) as string[]).map((login) => ({
          requestedReviewer: userNode(login),
        })),
        first,
        after,
      ),
    files: ({ first, after }: PageArgs) =>
      page(
        [{ path: 'README.md', additions: 1, deletions: 0, changeType: 'MODIFIED' }],
        first,
        after,
      ),
    commits: ({ first, last, after }: PageArgs & { last?: number | null }) => {
      const connection = page([{ commit }], last ?? first, after)
      return { ...connection, totalCount: 1 }
    },
    closingIssuesReferences: ({ first, after }: PageArgs) => page(closing, first, after),
    projectCards: () => {
      throw new Error(PROJECTS_CLASSIC_GONE)
    },
    projectItems: ({ first, after }: PageArgs) => page([], first, after),
  }
}

export interface PullRequestsArgs extends PageArgs {
  states?: string[] | null
  baseRefName?: string | null
  headRefName?: string | null
}

/**
 * The pull requests GraphQL's `pullRequests` lists: narrowed by state and by
 * base and head branch, newest first, a page at a time. `nodes` turns each row
 * into its node, which the caller composes with what it owns.
 */
export async function pullRequestConnection(
  ctx: { db: C; tenant: string },
  repo: RepoRow,
  args: PullRequestsArgs,
  nodes: (row: PullRow) => Promise<Record<string, unknown>>,
): Promise<Record<string, unknown>> {
  const rows = (await ctx.db.githubPull.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'desc' },
  })) as PullRow[]
  const states = args.states ?? ['OPEN', 'CLOSED', 'MERGED']
  const kept = rows.filter((row) => {
    const state = row.merged ? 'MERGED' : row.state === 'closed' ? 'CLOSED' : 'OPEN'
    if (!states.includes(state)) return false
    if (args.baseRefName && row.base !== args.baseRefName) return false
    return !args.headRefName || row.head === args.headRefName
  })
  const connection = page(kept, args.first ?? 0, args.after)
  return { ...connection, nodes: await Promise.all(connection.nodes.map(nodes)) }
}

export function pullRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => [
    route<C>('GET', `${p}/repos/:owner/:repo/pulls`, authedRoute(withRepo(listPulls))),
    route<C>('POST', `${p}/repos/:owner/:repo/pulls`, authedRoute(withRepo(createPull)), {
      write: true,
    }),
    route<C>('GET', `${p}/repos/:owner/:repo/pulls/:number`, authedRoute(withRepo(getPull))),
    route<C>('PATCH', `${p}/repos/:owner/:repo/pulls/:number`, authedRoute(withRepo(editPull)), {
      write: true,
    }),
    route<C>(
      'PUT',
      `${p}/repos/:owner/:repo/pulls/:number/merge`,
      authedRoute(withRepo(mergePull)),
      {
        write: true,
      },
    ),
    route<C>(
      'GET',
      `${p}/repos/:owner/:repo/pulls/:number/reviews`,
      authedRoute(withRepo(listReviews)),
    ),
    route<C>(
      'POST',
      `${p}/repos/:owner/:repo/pulls/:number/reviews`,
      authedRoute(withRepo(createReview)),
      { write: true },
    ),
    route<C>(
      'POST',
      `${p}/repos/:owner/:repo/pulls/:number/requested_reviewers`,
      authedRoute(withRepo(requestReviewers)),
      { write: true },
    ),
  ])
}
