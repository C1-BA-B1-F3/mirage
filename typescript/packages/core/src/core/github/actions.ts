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

import type { GitHubTransport } from './client.ts'
import { githubPages } from './paginate.ts'
import type { RepoRef } from './repo.ts'
import { decodeBase64 } from '../../utils/base64.ts'

const WORKFLOW_LOOKUP = 100
// gh reads every page of a run's jobs, however many there are.
const ALL_JOBS = Number.MAX_SAFE_INTEGER
const ENC = new TextEncoder()

function actions(ref: RepoRef, tail: string): string {
  return `/repos/${ref.owner}/${ref.repo}/actions/${tail}`
}

export async function resolveWorkflow(
  transport: GitHubTransport,
  ref: RepoRef,
  workflow: string,
): Promise<string> {
  if (/^\d+$/.test(workflow) || workflow.endsWith('.yml') || workflow.endsWith('.yaml')) {
    return workflow
  }
  const rows = await listWorkflows(transport, ref, WORKFLOW_LOOKUP)
  const wanted = workflow.toLowerCase()
  const match = rows.find(
    (row) => (typeof row.name === 'string' ? row.name.toLowerCase() : '') === wanted,
  )
  if (match === undefined) throw new Error(`could not find any workflows named ${workflow}`)
  const id = match.id
  return typeof id === 'number' || typeof id === 'string' ? String(id) : ''
}

export async function listRuns(
  transport: GitHubTransport,
  ref: RepoRef,
  params: Record<string, string>,
  limit: number,
  workflow?: string,
): Promise<Record<string, unknown>[]> {
  const tail =
    workflow === undefined
      ? 'runs'
      : `workflows/${encodeURIComponent(await resolveWorkflow(transport, ref, workflow))}/runs`
  return githubPages(transport, actions(ref, tail), { params, limit, key: 'workflow_runs' })
}

export function getRun(transport: GitHubTransport, ref: RepoRef, runId: number): Promise<unknown> {
  return transport.get(actions(ref, `runs/${String(runId)}`))
}

export function rerun(
  transport: GitHubTransport,
  ref: RepoRef,
  runId: number,
  suffix: string,
  body?: unknown,
): Promise<unknown> {
  return transport.request('POST', actions(ref, `runs/${String(runId)}/${suffix}`), body)
}

export function rerunJob(
  transport: GitHubTransport,
  ref: RepoRef,
  jobId: number,
  debug: boolean,
): Promise<unknown> {
  return transport.request('POST', actions(ref, `jobs/${String(jobId)}/rerun`), {
    enable_debug_logging: debug,
  })
}

export function listWorkflows(
  transport: GitHubTransport,
  ref: RepoRef,
  limit: number,
  include?: (row: Record<string, unknown>) => boolean,
): Promise<Record<string, unknown>[]> {
  return githubPages(transport, actions(ref, 'workflows'), {
    limit,
    key: 'workflows',
    ...(include === undefined ? {} : { include }),
  })
}

export async function getWorkflow(
  transport: GitHubTransport,
  ref: RepoRef,
  workflow: string,
): Promise<unknown> {
  const selector = await resolveWorkflow(transport, ref, workflow)
  return transport.get(actions(ref, `workflows/${encodeURIComponent(selector)}`))
}

export async function dispatchWorkflow(
  transport: GitHubTransport,
  ref: RepoRef,
  workflow: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  const selector = await resolveWorkflow(transport, ref, workflow)
  return transport.request(
    'POST',
    actions(ref, `workflows/${encodeURIComponent(selector)}/dispatches`),
    body,
  )
}

/** A run's jobs, every page of them, as `gh run view` reads them. */
export function listJobs(
  transport: GitHubTransport,
  ref: RepoRef,
  runId: number,
): Promise<Record<string, unknown>[]> {
  return githubPages(transport, actions(ref, `runs/${String(runId)}/jobs`), {
    limit: ALL_JOBS,
    key: 'jobs',
  })
}

// A body a transport handed back as bytes, text, or nothing.
function bytesOf(data: unknown): Uint8Array {
  if (data instanceof Uint8Array) return data
  if (data instanceof ArrayBuffer) return new Uint8Array(data)
  return typeof data === 'string' ? ENC.encode(data) : new Uint8Array(0)
}

/** A completed run's log archive, the zip GitHub ships its logs as. */
export async function runLogArchive(
  transport: GitHubTransport,
  ref: RepoRef,
  runId: number,
): Promise<Uint8Array> {
  return bytesOf(await transport.get(actions(ref, `runs/${String(runId)}/logs`)))
}

/** One job's whole log, where gh turns when the archive holds none for it. */
export async function jobLog(
  transport: GitHubTransport,
  ref: RepoRef,
  jobId: number,
): Promise<Uint8Array> {
  return bytesOf(await transport.get(actions(ref, `jobs/${String(jobId)}/logs`)))
}

/**
 * A workflow file's bytes as the repository holds it, at `gitRef` or the
 * default branch: the one read `gh workflow view --yaml` makes.
 */
export async function workflowContent(
  transport: GitHubTransport,
  ref: RepoRef,
  path: string,
  gitRef?: string,
): Promise<Uint8Array> {
  const params = gitRef === undefined || gitRef === '' ? undefined : { ref: gitRef }
  const data = (await transport.get(
    `/repos/${ref.owner}/${ref.repo}/contents/${path}`,
    params,
  )) as {
    content?: unknown
  } | null
  const content = data?.content
  return typeof content === 'string' ? decodeBase64(content.replace(/\s/g, '')) : new Uint8Array(0)
}
