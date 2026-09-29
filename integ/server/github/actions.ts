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
import { commitSha } from './wire.ts'
import { scope } from './store.ts'
import type { RepoRow } from './store.ts'
import {
  authedRoute,
  everywhere,
  fail,
  jsonBodyOf,
  pagedReply,
  param,
  route,
  str,
  withRepo,
} from './http.ts'

const DISPATCHED_AT = '2026-01-01T00:04:00Z'

interface WorkflowRow {
  id: number
  name: string
  path: string
  state: string
}

interface RunRow {
  id: number
  name: string
  displayTitle: string
  workflowId: number
  runNumber: number
  runAttempt: number
  event: string
  headBranch: string
  headSha: string
  status: string
  conclusion: string | null
  createdAt: string
  updatedAt: string
  runStartedAt: string | null
}

interface CheckRow {
  id: number
  name: string
  status: string
  conclusion: string
  startedAt: string
  completedAt: string
  detailsUrl: string
  summary: string
  appName: string
}

export interface StatusRow {
  context: string
  state: string
  targetUrl: string
  description: string
  createdAt: string
  updatedAt: string
}

function workflowJson(row: WorkflowRow): JsonValue {
  return { id: row.id, name: row.name, path: row.path, state: row.state }
}

function runJson(repo: RepoRow, row: RunRow): JsonValue {
  return {
    id: row.id,
    name: row.name,
    display_title: row.displayTitle,
    workflow_id: row.workflowId,
    run_number: row.runNumber,
    run_attempt: row.runAttempt,
    event: row.event,
    head_branch: row.headBranch,
    head_sha: row.headSha,
    status: row.status,
    conclusion: row.conclusion,
    created_at: row.createdAt,
    updated_at: row.updatedAt,
    run_started_at: row.runStartedAt,
    html_url: `https://github.com/${repo.fullName}/actions/runs/${String(row.id)}`,
  }
}

function checkJson(row: CheckRow): JsonValue {
  return {
    id: row.id,
    name: row.name,
    status: row.status,
    conclusion: row.conclusion,
    started_at: row.startedAt,
    completed_at: row.completedAt,
    details_url: row.detailsUrl,
    output: { summary: row.summary },
    app: { name: row.appName },
  }
}

function statusJson(row: StatusRow): JsonValue {
  return {
    context: row.context,
    state: row.state,
    target_url: row.targetUrl,
    description: row.description,
    created_at: row.createdAt,
    updated_at: row.updatedAt,
  }
}

async function workflowRows(ctx: Ctx<C>, repo: RepoRow): Promise<WorkflowRow[]> {
  return (await ctx.db.githubWorkflow.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'asc' },
  })) as WorkflowRow[]
}

// A workflow is named on the line by its id, its display name or its file's
// base name, and `gh workflow run ci.yml` uses the last of the three.
async function findWorkflow(
  ctx: Ctx<C>,
  repo: RepoRow,
  value: string,
): Promise<WorkflowRow | null> {
  const rows = await workflowRows(ctx, repo)
  const match = rows.find((r) => {
    const base = r.path.slice(r.path.lastIndexOf('/') + 1)
    return value === String(r.id) || value === r.name || value === base
  })
  return match ?? null
}

// Runs come back newest first, which is where a dispatch inserts itself.
async function runRows(ctx: Ctx<C>, repo: RepoRow): Promise<RunRow[]> {
  return (await ctx.db.githubRun.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'desc' },
  })) as RunRow[]
}

async function runById(ctx: Ctx<C>, repo: RepoRow, id: number): Promise<RunRow | null> {
  return (await ctx.db.githubRun.findFirst({
    where: { ...scope(ctx.tenant), repo: repo.fullName, id },
  })) as RunRow | null
}

async function topSeq(ctx: Ctx<C>, repo: RepoRow): Promise<number> {
  const row = await ctx.db.githubRun.findFirst({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'desc' },
  })
  return row === null ? -1 : row.seq
}

async function listWorkflows(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const rows = await workflowRows(ctx, repo)
  return pagedReply(ctx, rows.map(workflowJson), 'workflows')
}

async function getWorkflow(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const row = await findWorkflow(ctx, repo, param(ctx, 'workflow'))
  return row === null ? fail(404, 'Not Found') : { status: 200, body: workflowJson(row) }
}

// A dispatch answers 204 with no body, and the run it queues is what the
// caller polls for afterwards.
async function dispatchWorkflow(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const workflow = await findWorkflow(ctx, repo, param(ctx, 'workflow'))
  if (workflow === null) return fail(404, 'Not Found')
  const ref = str(jsonBodyOf(ctx), 'ref')
  if (ref === '') return fail(422, 'No ref found')
  const rows = await runRows(ctx, repo)
  const id = 201 + rows.length
  await ctx.db.githubRun.create({
    data: {
      tenant: ctx.tenant,
      repo: repo.fullName,
      id,
      name: workflow.name,
      displayTitle: `${workflow.name} dispatch`,
      workflowId: workflow.id,
      runNumber: rows.length + 1,
      runAttempt: 1,
      event: 'workflow_dispatch',
      headBranch: ref,
      headSha: commitSha(ref),
      status: 'queued',
      conclusion: null,
      createdAt: DISPATCHED_AT,
      updatedAt: DISPATCHED_AT,
      runStartedAt: null,
      seq: (await topSeq(ctx, repo)) + 1,
    },
  })
  return { status: 204 }
}

async function listRuns(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  let rows = await runRows(ctx, repo)
  const named = param(ctx, 'workflow')
  if (named !== '') {
    const workflow = await findWorkflow(ctx, repo, named)
    rows = workflow === null ? [] : rows.filter((r) => r.workflowId === workflow.id)
  }
  const filters: Array<[string, (r: RunRow) => string]> = [
    ['branch', (r) => r.headBranch],
    ['head_sha', (r) => r.headSha],
    ['event', (r) => r.event],
    ['status', (r) => r.status],
  ]
  for (const [key, read] of filters) {
    const value = ctx.query.get(key) ?? ''
    if (value !== '') rows = rows.filter((r) => read(r) === value)
  }
  return pagedReply(
    ctx,
    rows.map((r) => runJson(repo, r)),
    'workflow_runs',
  )
}

function idParam(ctx: Ctx<C>, name: string): number | null {
  const raw = param(ctx, name)
  return /^\d+$/.test(raw) ? Number.parseInt(raw, 10) : null
}

async function getRun(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const id = idParam(ctx, 'run_id')
  const row = id === null ? null : await runById(ctx, repo, id)
  return row === null ? fail(404, 'Not Found') : { status: 200, body: runJson(repo, row) }
}

// Rerunning queues the run again under a new attempt. A job id names a job the
// fake does not model, so that spelling is accepted and changes nothing rather
// than 404ing on a job the caller can see in a run it just read.
async function rerun(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const byJob = param(ctx, 'job_id') !== ''
  const id = idParam(ctx, 'run_id')
  const row = id === null ? null : await runById(ctx, repo, id)
  if (row === null) return byJob ? { status: 201 } : fail(404, 'Not Found')
  await ctx.db.githubRun.updateMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName, id: row.id },
    data: { runAttempt: row.runAttempt + 1, status: 'queued', conclusion: null },
  })
  return { status: 201 }
}

async function checkRuns(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const rows = (await ctx.db.githubCheck.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'asc' },
  })) as CheckRow[]
  return pagedReply(ctx, rows.map(checkJson), 'check_runs')
}

// The rolled-up state of a commit's statuses. Failure wins over pending, which
// wins over success, and no statuses at all reads as pending rather than as a
// green commit nothing has reported on.
export async function combinedStatus(
  ctx: Ctx<C>,
  repo: RepoRow,
): Promise<{ state: string; rows: StatusRow[] }> {
  const rows = (await ctx.db.githubStatus.findMany({
    where: { ...scope(ctx.tenant), repo: repo.fullName },
    orderBy: { seq: 'asc' },
  })) as StatusRow[]
  const states = new Set(rows.map((r) => r.state))
  let state = 'success'
  if (states.has('error') || states.has('failure')) state = 'failure'
  else if (rows.length === 0 || states.has('pending')) state = 'pending'
  return { state, rows }
}

async function commitStatus(ctx: Ctx<C>, repo: RepoRow): Promise<Reply> {
  const { state, rows } = await combinedStatus(ctx, repo)
  return {
    status: 200,
    body: {
      state,
      sha: param(ctx, 'sha'),
      total_count: rows.length,
      statuses: rows.map(statusJson),
    },
  }
}

export function actionRoutes(): KitRoute<C>[] {
  return everywhere<C>(API_PREFIXES, (p) => {
    const actions = `${p}/repos/:owner/:repo/actions`
    return [
      route<C>('GET', `${actions}/workflows`, authedRoute(withRepo(listWorkflows))),
      route<C>('GET', `${actions}/workflows/:workflow`, authedRoute(withRepo(getWorkflow))),
      route<C>(
        'POST',
        `${actions}/workflows/:workflow/dispatches`,
        authedRoute(withRepo(dispatchWorkflow)),
        { write: true },
      ),
      route<C>('GET', `${actions}/workflows/:workflow/runs`, authedRoute(withRepo(listRuns))),
      route<C>('GET', `${actions}/runs`, authedRoute(withRepo(listRuns))),
      route<C>('GET', `${actions}/runs/:run_id`, authedRoute(withRepo(getRun))),
      route<C>('POST', `${actions}/runs/:run_id/rerun`, authedRoute(withRepo(rerun)), {
        write: true,
      }),
      route<C>('POST', `${actions}/runs/:run_id/rerun-failed-jobs`, authedRoute(withRepo(rerun)), {
        write: true,
      }),
      route<C>('POST', `${actions}/jobs/:job_id/rerun`, authedRoute(withRepo(rerun)), {
        write: true,
      }),
      route<C>(
        'GET',
        `${p}/repos/:owner/:repo/commits/:sha/check-runs`,
        authedRoute(withRepo(checkRuns)),
      ),
      route<C>(
        'GET',
        `${p}/repos/:owner/:repo/commits/:sha/status`,
        authedRoute(withRepo(commitStatus)),
      ),
    ]
  })
}
