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

import type { LangfuseAccessor } from '../../accessor/langfuse.ts'
import { IndexEntry } from '../../cache/index/config.ts'
import { type DirListing, makeReaddir } from '../hierarchy/readdir.ts'
import type { ScopeMatch } from '../hierarchy/scope.ts'
import { jsonlBytes } from '../render/json.ts'
import {
  fetchDatasetItems,
  fetchDatasetRuns,
  fetchDatasets,
  fetchPrompts,
  fetchSessions,
  fetchTraces,
} from './client.ts'
import { TOP_LEVEL_DIRS, detectScope } from './scope.ts'

// Mirrors LangfuseConfig.default_trace_limit in python.
const DEFAULT_TRACE_LIMIT = 100

function pickString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === 'string' ? value : ''
}

function promptVersions(record: Record<string, unknown>): string[] {
  const value = record.versions
  if (!Array.isArray(value)) return []
  const numbers: number[] = []
  for (const entry of value) {
    const parsed = typeof entry === 'number' ? entry : Number(entry)
    if (Number.isFinite(parsed)) numbers.push(parsed)
  }
  return numbers.sort((a, b) => a - b).map(String)
}

/**
 * Whether a trace listing may have left traces out.
 *
 * It is one page of at most `defaultTraceLimit` traces from
 * `defaultFromTimestamp` on, so a full page or a set window is a truncated
 * view, not the directory: cached as complete it would prove an older
 * trace absent while read fetches it by id. Mirrors python's `_bounded`.
 */
function bounded(accessor: LangfuseAccessor, traces: readonly Record<string, unknown>[]): boolean {
  const limit = accessor.config.defaultTraceLimit ?? DEFAULT_TRACE_LIMIT
  const from = accessor.config.defaultFromTimestamp
  return traces.length >= limit || (from !== undefined && from !== '')
}

function traceEntries(traces: readonly Record<string, unknown>[]): [string, IndexEntry][] {
  return traces.map((t): [string, IndexEntry] => {
    const traceId = pickString(t, 'id')
    const filename = `${traceId}.json`
    return [
      filename,
      new IndexEntry({
        id: traceId,
        name: traceId,
        resourceType: 'langfuse/trace',
        vfsName: filename,
      }),
    ]
  })
}

async function listTraces(accessor: LangfuseAccessor, _match: ScopeMatch): Promise<DirListing> {
  const limit = accessor.config.defaultTraceLimit ?? DEFAULT_TRACE_LIMIT
  // No implicit time window: an unset defaultFromTimestamp lists whatever the
  // project holds, up to defaultTraceLimit. A rolling default would hide
  // traces that read() happily serves, and python applies no window either.
  const opts: { limit: number; fromTimestamp?: string } = { limit }
  const from = accessor.config.defaultFromTimestamp
  if (from !== undefined && from !== '') opts.fromTimestamp = from
  const traces = await fetchTraces(accessor.transport, opts)
  // The list endpoint returns trace summaries while a read renders the full
  // trace with its observations, so a size here would cost one fetchTrace per
  // entry. Traces and prompts stay size-unknown until a read hydrates them;
  // the dataset .jsonl files are sized because their listing already carries
  // every item.
  return { entries: traceEntries(traces), seeds: {}, partial: bounded(accessor, traces) }
}

async function listSessions(
  accessor: LangfuseAccessor,
  _match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const sessions = await fetchSessions(accessor.transport)
  return sessions.map((s): [string, IndexEntry] => {
    const sessionId = pickString(s, 'id')
    return [
      sessionId,
      new IndexEntry({
        id: sessionId,
        name: sessionId,
        resourceType: 'langfuse/session',
        vfsName: sessionId,
      }),
    ]
  })
}

async function listSessionTraces(
  accessor: LangfuseAccessor,
  match: ScopeMatch,
): Promise<DirListing> {
  const limit = accessor.config.defaultTraceLimit ?? DEFAULT_TRACE_LIMIT
  const opts: { sessionId: string; limit: number; fromTimestamp?: string } = {
    sessionId: match.slots.session_id ?? '',
    limit,
  }
  const from = accessor.config.defaultFromTimestamp
  if (from !== undefined && from !== '') opts.fromTimestamp = from
  const traces = await fetchTraces(accessor.transport, opts)
  return { entries: traceEntries(traces), seeds: {}, partial: bounded(accessor, traces) }
}

async function listPrompts(
  accessor: LangfuseAccessor,
  _match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const prompts = await fetchPrompts(accessor.transport)
  const seen = new Set<string>()
  const entries: [string, IndexEntry][] = []
  for (const p of prompts) {
    const promptName = pickString(p, 'name')
    if (seen.has(promptName)) continue
    seen.add(promptName)
    entries.push([
      promptName,
      new IndexEntry({
        id: promptName,
        name: promptName,
        resourceType: 'langfuse/prompt',
        vfsName: promptName,
      }),
    ])
  }
  return entries
}

async function listPromptVersions(
  accessor: LangfuseAccessor,
  match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const promptName = match.slots.prompt_name ?? ''
  const prompts = await fetchPrompts(accessor.transport)
  const entries: [string, IndexEntry][] = []
  for (const p of prompts) {
    if (pickString(p, 'name') !== promptName) continue
    // The list endpoint returns PromptMeta, which carries every version of a
    // prompt in a `versions` array; there is no scalar `version`.
    for (const version of promptVersions(p)) {
      const filename = `${version}.json`
      entries.push([
        filename,
        new IndexEntry({
          id: `${promptName}/${version}`,
          name: version,
          resourceType: 'langfuse/prompt_version',
          vfsName: filename,
        }),
      ])
    }
  }
  return entries
}

async function listDatasets(
  accessor: LangfuseAccessor,
  _match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const datasets = await fetchDatasets(accessor.transport)
  return datasets.map((d): [string, IndexEntry] => {
    const datasetName = pickString(d, 'name')
    return [
      datasetName,
      new IndexEntry({
        id: datasetName,
        name: datasetName,
        resourceType: 'langfuse/dataset',
        vfsName: datasetName,
      }),
    ]
  })
}

async function listDataset(
  accessor: LangfuseAccessor,
  match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const datasetName = match.slots.dataset_name ?? ''
  // One dataset_items call per dataset directory actually entered: the
  // dataset listing carries no item payloads, so items.jsonl can only be
  // sized here, and only for datasets the caller opens.
  const items = await fetchDatasetItems(accessor.transport, datasetName)
  return [
    [
      'items.jsonl',
      new IndexEntry({
        id: `${datasetName}/items`,
        name: 'items.jsonl',
        resourceType: 'langfuse/dataset_items',
        vfsName: 'items.jsonl',
        size: jsonlBytes(items).byteLength,
      }),
    ],
    [
      'runs',
      new IndexEntry({
        id: `${datasetName}/runs`,
        name: 'runs',
        resourceType: 'langfuse/dataset_runs_dir',
        vfsName: 'runs',
      }),
    ],
  ]
}

async function listDatasetRuns(
  accessor: LangfuseAccessor,
  match: ScopeMatch,
): Promise<[string, IndexEntry][]> {
  const datasetName = match.slots.dataset_name ?? ''
  const runs = await fetchDatasetRuns(accessor.transport, datasetName)
  return runs.map((r): [string, IndexEntry] => {
    const runName = pickString(r, 'name')
    const filename = `${runName}.jsonl`
    // The listing already carries the run document read() renders, so each
    // run file's exact size is free here.
    return [
      filename,
      new IndexEntry({
        id: runName,
        name: runName,
        resourceType: 'langfuse/dataset_run',
        vfsName: filename,
        size: jsonlBytes([r]).byteLength,
      }),
    ]
  })
}

export const readdir = makeReaddir<LangfuseAccessor>(detectScope, {
  listers: {
    traces: listTraces,
    sessions: listSessions,
    session: listSessionTraces,
    prompts: listPrompts,
    prompt: listPromptVersions,
    datasets: listDatasets,
    dataset: listDataset,
    runs: listDatasetRuns,
  },
  staticRoot: TOP_LEVEL_DIRS,
})
