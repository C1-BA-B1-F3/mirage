import { grepSearchOptions } from '../../commands/builtin/grep_pushdown.ts'
import type { LangfuseAccessor } from '../../accessor/langfuse.ts'
import { compilePattern } from '../../commands/builtin/grep_pattern.ts'
import { fetchDatasets, fetchPrompts, fetchSessions, fetchTraces } from './client.ts'
import { SEARCH_KINDS } from './scope.ts'
import type { Searcher } from '../hierarchy/search.ts'
import type { SearchQuery } from '../../vfs/types.ts'

function pickString(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === 'string' ? value : ''
}

function compiled(query: SearchQuery): RegExp {
  const options = grepSearchOptions(query)
  return compilePattern(query.query, options.ignoreCase, options.fixedString, options.wholeWord)
}

function filterTraces(traces: readonly Record<string, unknown>[], pattern: RegExp): string[] {
  const lines: string[] = []
  for (const t of traces) {
    const traceId = pickString(t, 'id')
    const lineJson = JSON.stringify(t)
    if (!pattern.test(lineJson)) continue
    lines.push(`traces/${traceId}.json:${lineJson}`)
  }
  return lines
}

function filterSessions(sessions: readonly Record<string, unknown>[], pattern: RegExp): string[] {
  const lines: string[] = []
  for (const s of sessions) {
    const sessionId = pickString(s, 'id')
    if (!pattern.test(sessionId)) continue
    lines.push(`sessions/${sessionId}:${JSON.stringify(s)}`)
  }
  return lines
}

function filterPrompts(prompts: readonly Record<string, unknown>[], pattern: RegExp): string[] {
  const lines: string[] = []
  const seen = new Set<string>()
  for (const p of prompts) {
    const promptName = pickString(p, 'name')
    if (seen.has(promptName)) continue
    if (!pattern.test(promptName)) continue
    seen.add(promptName)
    lines.push(`prompts/${promptName}:${JSON.stringify(p)}`)
  }
  return lines
}

function filterDatasets(datasets: readonly Record<string, unknown>[], pattern: RegExp): string[] {
  const lines: string[] = []
  for (const d of datasets) {
    const datasetName = pickString(d, 'name')
    if (!pattern.test(datasetName)) continue
    lines.push(`datasets/${datasetName}:${JSON.stringify(d)}`)
  }
  return lines
}

// The search push-down answers from the list endpoints (one call instead
// of one read per entry), so it greps listing summaries: a pattern that
// only occurs in a trace's observation bodies needs a file read to match.
const tracesSearcher: Searcher<LangfuseAccessor> = async (accessor, _match, query) => {
  const limit = accessor.config.defaultSearchLimit ?? 50
  const traces = await fetchTraces(accessor.transport, { limit })
  return filterTraces(traces, compiled(query))
}

const sessionsSearcher: Searcher<LangfuseAccessor> = async (accessor, _match, query) => {
  const limit = accessor.config.defaultSearchLimit ?? 50
  const sessions = await fetchSessions(accessor.transport, { limit })
  return filterSessions(sessions, compiled(query))
}

const promptsSearcher: Searcher<LangfuseAccessor> = async (accessor, _match, query) =>
  filterPrompts(await fetchPrompts(accessor.transport), compiled(query))

const datasetsSearcher: Searcher<LangfuseAccessor> = async (accessor, _match, query) =>
  filterDatasets(await fetchDatasets(accessor.transport), compiled(query))

const CONTAINERS: Readonly<Record<string, Searcher<LangfuseAccessor>>> = {
  traces: tracesSearcher,
  sessions: sessionsSearcher,
  prompts: promptsSearcher,
  datasets: datasetsSearcher,
}

export const SEARCHERS: Readonly<Record<string, Searcher<LangfuseAccessor>>> = Object.fromEntries(
  Object.entries(SEARCH_KINDS).flatMap(([kind, container]) => {
    const searcher = CONTAINERS[container]
    return searcher === undefined ? [] : [[kind, searcher] as const]
  }),
)
